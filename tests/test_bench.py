"""The benchmark harness on the fixture call, offline throughout (M10)."""

import json
import shutil

import pytest

from bench import metrics, report as report_module
from bench import variants
from bench.judge import agreement, build_prompt, judge_pair
from bench.run import cloud_blocked, load_models, run_cell, run_matrix
from revolv.interpret import view as view_module
from test_runner import FakeProvider


@pytest.fixture()
def call_dir(tmp_path, fixture_dir):
    calls = tmp_path / "calls" / "fixture_call"
    calls.mkdir(parents=True)
    for name in ("call.json", "call.analysis.json", "meta.json"):
        shutil.copy(fixture_dir / name, calls / name)
    return calls


LOCAL_MODEL = {"id": "fake-local", "provider": "openai_compat",
               "base_url": "http://127.0.0.1:8080/v1", "model": "fake",
               "egress": "loopback"}


# -- variants ---------------------------------------------------------------

def _view_text(segments, report, meta, variant):
    v_segments, v_report, overrides = variants.apply(variant, segments,
                                                     report)
    v_meta = dict(meta, analysis=v_report, numbers_file=True)
    with variants.render_overrides(overrides):
        return view_module.build(v_report, v_segments, v_meta).text


def _body(text):
    """The transcript body; the legend always explains the marks it may
    carry, so the ablation assertions look past it."""
    return text.split("## Transcript", 1)[1]


def test_variants_strip_what_they_claim(fixture_segments, fixture_report,
                                        fixture_meta):
    full = _view_text(fixture_segments, fixture_report, fixture_meta, "full")
    assert "## Moments" in full
    assert "s silence)" in _body(full) and " um " in _body(full)

    no_notes = _view_text(fixture_segments, fixture_report, fixture_meta,
                          "no_notes")
    assert "## Moments" not in no_notes
    assert "than usual" not in _body(no_notes)
    assert "s silence)" in _body(no_notes)    # timing survives

    no_timing = _view_text(fixture_segments, fixture_report, fixture_meta,
                           "no_timing")
    assert "s silence)" not in _body(no_timing)
    assert "(..." not in _body(no_timing)     # in-turn pause marks gone
    assert " um " in _body(no_timing)         # verbatim survives

    clean = _view_text(fixture_segments, fixture_report, fixture_meta,
                       "clean")
    assert " um " not in _body(clean)
    assert " s- " not in _body(clean)
    assert "[laughter]" not in _body(clean)


def test_variants_never_touch_the_originals(fixture_segments,
                                            fixture_report, fixture_meta):
    before = json.dumps(fixture_report, sort_keys=True)
    variants.apply("clean", fixture_segments, fixture_report)
    assert json.dumps(fixture_report, sort_keys=True) == before


# -- guard rails ------------------------------------------------------------

def test_cloud_guard():
    remote = {"egress": "remote"}
    manual = {"provider": "manual", "requires_cloud_ok": True}
    local = {"egress": "loopback"}
    no_consent = {"consent": {"cloud_ok": False}}
    consent = {"consent": {"cloud_ok": True}}
    assert cloud_blocked(remote, no_consent, {})
    assert cloud_blocked(manual, no_consent, {})
    assert not cloud_blocked(remote, consent, {})
    assert not cloud_blocked(local, no_consent, {})


def test_models_yaml_parses():
    models = load_models("bench/models.yaml")
    ids = {m["id"] for m in models}
    assert "gpt-oss-20b-local" in ids
    assert "remote-example" not in ids  # enabled: false


# -- the matrix -------------------------------------------------------------

def test_matrix_runs_and_resumes(tmp_path, call_dir, fixture_report):
    runs = tmp_path / "runs"
    provider = FakeProvider(fixture_report)
    records = run_matrix([LOCAL_MODEL], call_dir.parent, runs,
                         seeds=(1, 2), providers={"fake-local": provider},
                         log=lambda m: None)
    assert [r["status"] for r in records] == ["ok", "ok"]
    calls_made = len(provider.calls)
    # Resuming skips finished cells: no new provider calls.
    run_matrix([LOCAL_MODEL], call_dir.parent, runs, seeds=(1, 2),
               providers={"fake-local": provider}, log=lambda m: None)
    assert len(provider.calls) == calls_made
    cell_dirs = sorted(runs.iterdir())
    assert len(cell_dirs) == 2
    record = json.loads((cell_dirs[0] / "cell.json").read_text())
    assert record["kept"] == 1
    assert record["verifier"]["proposed"] == 1
    assert record["readings"][0]["speaker"] == "SPEAKER_01"


def test_manual_cells_await_then_verify(tmp_path, call_dir, fixture_report):
    runs = tmp_path / "runs"
    manual = {"id": "hand", "provider": "manual", "egress": "none"}
    records = run_matrix([manual], call_dir.parent, runs,
                         log=lambda m: None)
    assert records[0]["status"] == "awaiting_manual"
    cell_dir = runs / records[0]["cell"]
    assert (cell_dir / "call.prompt" / "single_pass.txt").exists()

    from test_gui_results import _valid_response

    (cell_dir / "response.json").write_text(_valid_response(fixture_report),
                                            encoding="utf-8")
    records = run_matrix([manual], call_dir.parent, runs,
                         log=lambda m: None)
    assert records[0]["status"] == "ok"


def test_remote_without_consent_is_skipped(tmp_path, call_dir):
    runs = tmp_path / "runs"
    remote = {"id": "cloud", "provider": "anthropic", "egress": "remote"}
    records = run_matrix([remote], call_dir.parent, runs,
                         log=lambda m: None)
    assert records[0]["status"] == "skipped_cloud"


# -- metrics and report -----------------------------------------------------

def _cells():
    reading = {"speaker": "S1", "layer": "unsaid", "likelihood": "likely",
               "turns": ["T010", "T011"]}
    shifted = dict(reading, likelihood="roughly even chance")
    verifier = {"proposed": 4, "kept": 2,
                "dropped_by_reason": {"convergence": 1, "wording": 1},
                "evidence_proposed": 10, "evidence_quote_rejected": 1}
    return [
        {"status": "ok", "model": "m", "mode": "single_pass",
         "variant": "full", "seed": 1, "call": "c1", "kept": 2,
         "verifier": verifier, "readings": [reading],
         "nothing_notable": 1, "speakers_described": 2, "seconds": 30,
         "tokens_out": 500},
        {"status": "ok", "model": "m", "mode": "single_pass",
         "variant": "full", "seed": 2, "call": "c1", "kept": 2,
         "verifier": verifier, "readings": [shifted],
         "nothing_notable": 1, "speakers_described": 2, "seconds": 34,
         "tokens_out": 480},
        {"status": "failed", "model": "m", "mode": "single_pass",
         "variant": "full", "seed": 3, "call": "c1"},
    ]


def test_deterministic_metrics():
    rows = metrics.deterministic(_cells())
    row = rows[("m", "single_pass", "full")]
    assert row["cells"] == 2                      # failed cells excluded
    assert row["kept_per_call"] == 2
    assert row["quote_mismatch_rate"] == 0.1  # 2 of 20 items over two cells
    assert row["convergence_violation_rate"] == 0.25  # 2 of 8 proposed
    assert row["wording_violations"] == 2
    assert row["abstention_rate"] == 0.5
    assert row["test_retest_jaccard"] == 1.0      # same reading both seeds
    assert row["band_agreement"] == 1.0           # one band apart


def test_reading_matching_needs_half_the_turns():
    a = [{"speaker": "S", "layer": "unsaid", "likelihood": "likely",
          "turns": ["T001", "T002"]}]
    b = [{"speaker": "S", "layer": "unsaid", "likelihood": "likely",
          "turns": ["T002", "T009"]}]
    c = [{"speaker": "S", "layer": "unsaid", "likelihood": "likely",
          "turns": ["T008", "T009"]}]
    assert metrics.match_readings(a, b)
    assert not metrics.match_readings(a, c)


def test_action_item_recall():
    document = {"notes": {"action_items": [
        {"task": "send it", "turn_ids": ["T004"]}]}}
    gold = {"action_items": [{"task": "send", "turn_ids": ["T004"]},
                             {"task": "book", "turn_ids": ["T020"]}]}
    assert metrics.action_item_recall(document, gold) == 0.5


def test_report_carries_numbers_only(tmp_path):
    path = report_module.build_report(_cells(), tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "kept_per_call" in text
    assert "0.1" in text
    assert (tmp_path / "results.csv").exists()
    assert "directional" in text


# -- the judge --------------------------------------------------------------

class FakeJudge:
    id = "judge"
    egress = "none"
    model = "judge-1"

    def __init__(self):
        self.prompts = []

    def complete(self, *, system, user, json_schema=None, temperature=0.2,
                 seed=None, max_tokens=1200):
        from revolv.interpret.providers.base import Completion

        self.prompts.append(user)
        # Always prefer whichever slot holds the text "GOOD".
        prefer = "A" if user.index("GOOD") < user.index("WEAK") else "B"
        reply = {"A": {d: 3 for d in ("faithfulness", "usefulness",
                                      "non_obviousness", "over_reach",
                                      "tone")},
                 "B": {d: 3 for d in ("faithfulness", "usefulness",
                                      "non_obviousness", "over_reach",
                                      "tone")},
                 "prefer": prefer, "why": "test"}
        return Completion(text=json.dumps(reply), tokens_in=1, tokens_out=1,
                          seconds=0.0, model=self.model, provider=self.id)


def test_judge_swaps_and_unswaps():
    judge = FakeJudge()
    verdict = judge_pair(judge, "view", "GOOD output", "WEAK output")
    assert len(judge.prompts) == 2
    # Both orderings named the same underlying output, so it holds.
    assert verdict["prefer"] == "A"


def test_judge_prompt_order_swap():
    normal = build_prompt("v", "AAA", "BBB")
    swapped = build_prompt("v", "AAA", "BBB", swapped=True)
    assert normal.index("AAA") < normal.index("BBB")
    assert swapped.index("BBB") < swapped.index("AAA")


def test_agreement():
    assert agreement(["A", "B", "tie"], ["A", "A", "tie"]) == \
        pytest.approx(2 / 3, abs=0.01)
