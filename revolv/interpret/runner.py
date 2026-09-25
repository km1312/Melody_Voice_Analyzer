"""Run interpretation over a provider (FR-9, M9): passes, retries, records.

Single pass or the four-pass chain, one retry per pass that quotes the
validation error, raw outputs saved under the newest prompt pack's
`run_<id>/`, and the draft handed to the same verifier and writers the
Import box uses. A provider whose egress is `remote` is refused outright in
Phase 1; `allow_remote` belongs to Phase 2 and is not even a setting yet.
"""

import json
import time
from pathlib import Path

from .. import safelog
from . import schema as schema_module
from . import verify as verify_module
from .manual_import import import_response, new_run_id, run_record
from .pack import build_pack, fill

PASS_TEMPERATURES = {"pass_a": 0.2, "pass_b": 0.4, "pass_c": 0.2,
                     "pass_d": 0.3, "single_pass": 0.3}
DEFAULT_SEED = 1
DEFAULT_MAX_TOKENS = 6000


class RunError(RuntimeError):
    pass


def _refuse_remote(provider, settings):
    if getattr(provider, "egress", "remote") == "remote" and \
            not (settings or {}).get("allow_remote"):
        raise RunError(
            "Provider {0} would send this call off the machine, and Phase 1 "
            "sends nothing anywhere.".format(getattr(provider, "id", "?")))


def _newest_pack(out_dir, stem):
    candidates = [p for p in Path(out_dir).glob(stem + "*.prompt")
                  if p.is_dir()]
    return max(candidates, key=lambda p: p.stat().st_mtime) \
        if candidates else None


def _complete_json(provider, system, user, schema, name, run_dir, log=None,
                   seed=DEFAULT_SEED, max_tokens=DEFAULT_MAX_TOKENS):
    """One pass: complete, parse, validate; one retry quoting the error."""
    temperature = PASS_TEMPERATURES.get(name, 0.3)
    attempts = []
    prompt = user
    for attempt in (1, 2):
        completion = provider.complete(
            system=system, user=prompt, json_schema=schema,
            temperature=temperature, seed=seed, max_tokens=max_tokens)
        attempts.append(completion)
        raw_path = run_dir / "{0}{1}.json".format(
            name, "" if attempt == 1 else "_retry")
        raw_path.write_text(completion.text, encoding="utf-8")
        stripped = verify_module.strip_response(completion.text)
        try:
            parsed = json.loads(stripped)
            problems = schema_module.problems(parsed, schema)
        except json.JSONDecodeError as exc:
            parsed, problems = None, ["not valid JSON: {0}".format(exc)]
        if not problems:
            safelog.log_event("pass_done", emit=log, stage=name,
                              attempt=attempt,
                              seconds=completion.seconds,
                              tokens_out=completion.tokens_out)
            return parsed, attempts
        if attempt == 1:
            prompt = (user + "\n\nYour previous reply failed validation: "
                      + "; ".join(problems[:3])
                      + "\nReturn the corrected JSON object only.")
    raise RunError("The model's {0} reply failed validation twice: {1}"
                   .format(name, "; ".join(problems[:3])))


def _kept_clusters(pass_b, pass_c, pass_a):
    """Pass C's surviving clusters, joined with their observations for D."""
    observations = {o.get("id"): o
                    for o in pass_a.get("observations") or []}
    clusters = {c.get("id"): c for c in pass_b.get("clusters") or []}
    kept = []
    for review in pass_c.get("reviews") or []:
        if review.get("verdict") == "drop":
            continue
        cluster = clusters.get(review.get("cluster_id"))
        if cluster is None:
            continue
        cited = {ob for reading in cluster.get("readings") or []
                 for ob in reading.get("supports") or []}
        kept.append({
            "cluster": cluster,
            "review": review,
            "observations": [observations[i] for i in sorted(cited)
                             if i in observations],
        })
    return kept


def run_interpretation(segments, meta, out_dir, stem, provider, context=None,
                       mode="single_pass", settings=None, log=None,
                       coaching_slots=None):
    """The whole thing: pack, passes, verify, write. Returns ImportResult."""
    _refuse_remote(provider, settings)
    settings = settings or {}
    out_dir = Path(out_dir)

    pack_dir = _newest_pack(out_dir, stem)
    if pack_dir is None:
        pack_dir = build_pack(segments, meta, out_dir, stem, context=context,
                              log=log, coaching_slots=coaching_slots)
    run_id = new_run_id()
    run_dir = pack_dir / "run_{0}".format(run_id)
    run_dir.mkdir(parents=True, exist_ok=True)

    system = (pack_dir / "system.txt").read_text(encoding="utf-8")
    started = time.time()
    if mode == "multi_pass":
        draft = _run_multi(provider, pack_dir, system, run_dir, log=log)
    else:
        mode = "single_pass"
        user = (pack_dir / "single_pass.txt").read_text(encoding="utf-8")
        draft, _attempts = _complete_json(
            provider, system, user, schema_module.INSIGHTS_DRAFT,
            "single_pass", run_dir, log=log)

    run = run_record(provider=getattr(provider, "id", "?"),
                     model=getattr(provider, "model", ""),
                     mode=mode, params={"seed": DEFAULT_SEED},
                     seconds=time.time() - started, context=context)
    run["run_id"] = run_id
    result = import_response(segments, meta, out_dir, stem,
                             json.dumps(draft), context=context, run=run,
                             log=log,
                             max_per_call=int(settings.get(
                                 "max_insights_per_call", 8)),
                             max_per_speaker=int(settings.get(
                                 "max_insights_per_speaker", 3)))
    return result


def _run_multi(provider, pack_dir, system, run_dir, log=None):
    view_text = (pack_dir / "view.txt").read_text(encoding="utf-8")
    user_a = (pack_dir / "pass_a.txt").read_text(encoding="utf-8")
    pass_a, _ = _complete_json(provider, system, user_a,
                               schema_module.PASS_A, "pass_a", run_dir,
                               log=log)

    template_b = (pack_dir / "pass_b.template.txt").read_text(
        encoding="utf-8")
    user_b = fill(template_b, {"PASS_A_JSON": json.dumps(pass_a)})
    pass_b, _ = _complete_json(provider, system, user_b,
                               schema_module.PASS_B, "pass_b", run_dir,
                               log=log)

    template_c = (pack_dir / "pass_c.template.txt").read_text(
        encoding="utf-8")
    user_c = fill(template_c, {
        "PASS_B_JSON": json.dumps(pass_b),
        "PASS_A_OBSERVATIONS_JSON": json.dumps(
            pass_a.get("observations") or [])})
    pass_c, _ = _complete_json(provider, system, user_c,
                               schema_module.PASS_C, "pass_c", run_dir,
                               log=log)

    template_d = (pack_dir / "pass_d.template.txt").read_text(
        encoding="utf-8")
    user_d = fill(template_d, {
        "PASS_A_FACTS_AND_TOPICS_JSON": json.dumps(
            {"topics": pass_a.get("topics") or [],
             "facts": pass_a.get("facts") or {}}),
        "PASS_C_KEPT_WITH_OBSERVATIONS_JSON": json.dumps(
            _kept_clusters(pass_b, pass_c, pass_a))})
    draft, _ = _complete_json(provider, system, user_d,
                              schema_module.INSIGHTS_DRAFT, "pass_d",
                              run_dir, log=log)
    return draft


def provider_from_settings(settings):
    """The configured provider, or None for manual."""
    name = (settings or {}).get("provider", "manual")
    if name == "manual":
        return None
    if name == "openai_compat":
        from .providers.openai_compat import OpenAICompatProvider

        return OpenAICompatProvider(
            settings.get("provider_base_url", "http://127.0.0.1:8080/v1"),
            model=settings.get("provider_model", ""))
    raise RunError("Unknown provider {0!r}".format(name))


def run_from_cli(json_path, mode=None):
    """`python -m revolv.interpret run <name>.json`."""
    from ..config import Settings
    from .__main__ import _assemble, _context_for

    settings = Settings()
    provider = provider_from_settings(settings)
    if provider is None:
        print("The configured provider is 'manual'. Build the pack, send it "
              "by hand, then `python -m revolv.interpret import`.")
        return 2
    json_path = Path(json_path)
    segments, meta, _sources = _assemble(json_path)
    result = run_interpretation(
        segments, meta, json_path.parent, json_path.stem, provider,
        context=_context_for(json_path),
        mode=mode or settings.get("interpret_mode", "single_pass"),
        settings=settings, log=None)
    if result.problems:
        for problem in result.problems:
            print("  - {0}".format(problem))
        return 1
    print("Wrote {0} ({1} kept, {2} dropped)".format(
        result.insights_path, result.kept, result.dropped))
    return 0
