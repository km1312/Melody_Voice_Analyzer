"""The matrix runner: calls x models x mode x variant x seeds.

Each cell gets its own folder under runs/<tag>/, holding the variant's
prompt pack, the raw outputs, the verified insights and a `cell.json`
record with ids and numbers only. Finished cells are skipped, so a matrix
can be resumed after any interruption.

Guard rails (PRD section 10): a model with `egress: remote`, or a manual
entry marked `requires_cloud_ok`, never touches a call whose consent does
not say `cloud_ok: true`.

    python -m bench.run --models bench/models.yaml --tag first
"""

import argparse
import json
import time
from pathlib import Path

from revolv.interpret import context as context_module
from revolv.interpret.manual_import import run_record
from revolv.interpret.pack import build_pack
from revolv.interpret.runner import run_interpretation

from . import bench_dir
from .variants import apply as apply_variant
from .variants import render_overrides


def load_models(path):
    import yaml

    with open(path, encoding="utf-8") as f:
        models = yaml.safe_load(f) or []
    return [m for m in models if m.get("enabled", True)]


def load_call(call_dir):
    call_dir = Path(call_dir)
    with open(call_dir / "call.json", encoding="utf-8") as f:
        segments = json.load(f)
    with open(call_dir / "call.analysis.json", encoding="utf-8") as f:
        report = json.load(f)
    context = context_module.load(call_dir / "context.json")
    meta_path = call_dir / "meta.json"
    meta = {}
    if meta_path.exists():
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    meta.setdefault("source", str(call_dir / "call"))
    meta.setdefault("media_seconds",
                    (report.get("summary") or {}).get("media_seconds"))
    return segments, report, context, meta


def cloud_blocked(model, context, meta):
    """True when this model may not see this call (PR-11)."""
    needs_consent = (model.get("egress") == "remote"
                     or model.get("requires_cloud_ok"))
    if not needs_consent:
        return False
    consent = (context.get("consent") or {}).get("cloud_ok") \
        or meta.get("cloud_ok")
    return not bool(consent)


def cell_name(call_id, model_id, mode, variant, seed):
    return "{0}__{1}__{2}__{3}__s{4}".format(call_id, model_id, mode,
                                             variant, seed)


def provider_for(model, providers=None):
    if providers and model["id"] in providers:
        return providers[model["id"]]
    kind = model.get("provider")
    if kind == "manual":
        return None
    if kind == "openai_compat":
        from revolv.interpret.providers.openai_compat import \
            OpenAICompatProvider

        return OpenAICompatProvider(model["base_url"],
                                    model=model.get("model", ""))
    raise SystemExit("Phase 1 has no adapter for provider {0!r}; remote "
                     "adapters arrive with Phase 2.".format(kind))


def run_cell(cell_dir, model, segments, report, context, meta, mode,
             variant, seed, providers=None):
    """One cell. Returns the record written to cell.json."""
    cell_dir = Path(cell_dir)
    record_path = cell_dir / "cell.json"
    if record_path.exists():
        with open(record_path, encoding="utf-8") as f:
            record = json.load(f)
        if record.get("status") in ("ok", "skipped_cloud"):
            return record

    record = {"model": model["id"], "mode": mode, "variant": variant,
              "seed": seed, "status": "pending", "started": time.time()}
    cell_dir.mkdir(parents=True, exist_ok=True)

    if cloud_blocked(model, context, meta):
        record["status"] = "skipped_cloud"
        record["reason"] = ("consent.cloud_ok is not true for this call, "
                            "and this model would send it off the machine")
        _write(record_path, record)
        return record

    v_segments, v_report, overrides = apply_variant(variant, segments,
                                                    report)
    v_meta = dict(meta, analysis=v_report, numbers_file=True)

    provider = provider_for(model, providers)
    with render_overrides(overrides):
        if provider is None:
            # Manual: write the pack; verify a response file if one has been
            # dropped in, else leave the cell awaiting.
            pack = build_pack(v_segments, v_meta, cell_dir, "call",
                              context=context)
            record["pack"] = pack.name
            response = cell_dir / "response.json"
            if not response.exists():
                record["status"] = "awaiting_manual"
                _write(record_path, record)
                return record
            from revolv.interpret.manual_import import import_response

            result = import_response(
                v_segments, v_meta, cell_dir, "call",
                response.read_text(encoding="utf-8"), context=context,
                run=_bench_run(model, mode, seed, context))
        else:
            result = run_interpretation(v_segments, v_meta, cell_dir,
                                        "call", provider, context=context,
                                        mode=mode)

    record["seconds"] = round(time.time() - record["started"], 2)
    if result.problems:
        record["status"] = "failed"
        record["problems"] = len(result.problems)
    else:
        record["status"] = "ok"
        document = result.document
        record["run_id"] = document["run"]["run_id"]
        record["prompt_version"] = document["run"]["prompt_version"]
        record["verifier"] = document["verifier"]
        record["kept"] = len(document["insights"])
        record["nothing_notable"] = sum(
            1 for s in document.get("speakers") or []
            if s.get("nothing_notable"))
        record["speakers_described"] = len(document.get("speakers") or [])
        record["tokens_in"] = document["run"].get("tokens_in")
        record["tokens_out"] = document["run"].get("tokens_out")
        record["readings"] = [_reading_key_parts(i)
                              for i in document["insights"]]
        record["action_items"] = len(
            (document.get("notes") or {}).get("action_items") or [])
    _write(record_path, record)
    return record


def _bench_run(model, mode, seed, context):
    run = run_record(provider=model.get("provider", "manual"),
                     model=model.get("model", ""), mode=mode,
                     params={"seed": seed}, context=context)
    return run


def _reading_key_parts(insight):
    """What test-retest matching needs, content-free."""
    return {"speaker": insight.get("speaker"),
            "layer": insight.get("layer"),
            "likelihood": insight.get("likelihood"),
            "turns": sorted({e.get("turn_id")
                             for e in insight.get("evidence") or []})}


def _write(path, record):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2)


def run_matrix(models, calls_dir, runs_dir, modes=("single_pass",),
               variants=("full",), seeds=(1,), providers=None, log=print):
    calls_dir, runs_dir = Path(calls_dir), Path(runs_dir)
    records = []
    for call_dir in sorted(p for p in calls_dir.iterdir() if p.is_dir()):
        segments, report, context, meta = load_call(call_dir)
        for model in models:
            for mode in modes:
                for variant in variants:
                    for seed in seeds:
                        name = cell_name(call_dir.name, model["id"], mode,
                                         variant, seed)
                        record = run_cell(runs_dir / name, model, segments,
                                          report, context, meta, mode,
                                          variant, seed,
                                          providers=providers)
                        record["call"] = call_dir.name
                        record["cell"] = name
                        records.append(record)
                        log("{0}: {1}".format(name, record["status"]))
    return records


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m bench.run")
    parser.add_argument("--models", default="bench/models.yaml")
    parser.add_argument("--tag", default=time.strftime("%Y-%m-%d"))
    parser.add_argument("--modes", nargs="+", default=["single_pass"])
    parser.add_argument("--variants", nargs="+", default=["full"])
    parser.add_argument("--seeds", nargs="+", type=int, default=[1, 2, 3, 4, 5])
    args = parser.parse_args(argv)

    root = bench_dir()
    records = run_matrix(load_models(args.models), root / "calls",
                         root / "runs" / args.tag, modes=args.modes,
                         variants=args.variants, seeds=args.seeds)
    from .report import build_report

    report_dir = root / "reports" / args.tag
    build_report(records, report_dir)
    print("Report in {0}".format(report_dir))
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
