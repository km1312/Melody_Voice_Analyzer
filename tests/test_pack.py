"""The prompt pack: filled slots, stable hashes, and a clean log (FR-5, PR-4)."""

import json
import re
import shutil

import pytest

from revolv.interpret import pack as pack_module
from revolv.interpret.__main__ import main as cli_main
from revolv.interpret.context import default_context

CANARY = ["flumberwick", "zonkey", "parade"]


def _meta(fixture_meta, fixture_report):
    return dict(fixture_meta, analysis=fixture_report, numbers_file=True)


@pytest.fixture()
def pack_dir(tmp_path, fixture_segments, fixture_meta, fixture_report):
    return pack_module.build_pack(
        fixture_segments, _meta(fixture_meta, fixture_report),
        tmp_path, "call", context=None)


def test_pack_builds_with_no_context_and_no_model(pack_dir):
    for name in ("README.txt", "system.txt", "single_pass.txt", "view.txt",
                 "pass_a.txt", "pass_b.template.txt", "pass_c.template.txt",
                 "pass_d.template.txt", "pack.json"):
        assert (pack_dir / name).exists(), name
    for name in ("pass_a", "pass_b", "pass_c", "insights_draft", "coaching"):
        assert (pack_dir / "schemas" / (name + ".json")).exists(), name


def test_filled_files_have_no_open_slots(pack_dir):
    for name in ("system.txt", "single_pass.txt", "pass_a.txt", "view.txt",
                 "README.txt"):
        assert "{{" not in (pack_dir / name).read_text(encoding="utf-8"), name


def test_templates_keep_only_their_runner_slots(pack_dir):
    for name, allowed in pack_module.PASS_TEMPLATE_SLOTS.items():
        text = (pack_dir / (name + ".template.txt")).read_text(encoding="utf-8")
        assert set(re.findall(r"\{\{([A-Z0-9_]+)\}\}", text)) == allowed


def test_empty_context_renders_not_given(pack_dir):
    system = (pack_dir / "system.txt").read_text(encoding="utf-8")
    assert "Their goal for this call: not given" in system
    assert "They are: not identified" in system
    assert "Names: none" in system
    assert "Meeting type: Other" in system
    assert "No special lens." in system


def test_filled_context_reaches_the_system_prompt(tmp_path, fixture_segments,
                                                  fixture_meta, fixture_report):
    context = default_context()
    context.update(meeting_type="negotiation", goal="Agree the price",
                   me="SPEAKER_00",
                   speaker_names={"SPEAKER_01": "Brian"})
    pack_dir = pack_module.build_pack(
        fixture_segments, _meta(fixture_meta, fixture_report),
        tmp_path, "call", context=context)
    system = (pack_dir / "system.txt").read_text(encoding="utf-8")
    assert "Meeting type: Negotiation" in system
    assert "Agree the price" in system
    assert "They are: SPEAKER_00" in system
    assert "SPEAKER_01 is Brian" in system
    assert "opening bids" in system  # the negotiation lens


def test_pack_json_records_version_hash_and_prosody(pack_dir):
    meta = json.loads((pack_dir / "pack.json").read_text(encoding="utf-8"))
    assert meta["prompt_version"] == "p1.0.0"
    assert re.fullmatch(r"[0-9a-f]{64}", meta["prompt_sha256"])
    assert meta["prosody"] is True
    assert meta["token_estimate"] > 1000


def test_prompt_hash_is_stable_and_lens_sensitive():
    a = pack_module.prompt_sha256()
    b = pack_module.prompt_sha256()
    assert a == b
    negotiation = pack_module.prompt_sha256({"meeting_type": "negotiation"})
    assert negotiation != a


def test_second_build_never_overwrites(tmp_path, fixture_segments,
                                       fixture_meta, fixture_report):
    meta = _meta(fixture_meta, fixture_report)
    first = pack_module.build_pack(fixture_segments, meta, tmp_path, "call")
    second = pack_module.build_pack(fixture_segments, meta, tmp_path, "call")
    assert first.name == "call.prompt"
    # unique_path reads ".prompt" as the suffix, so the counter lands on the
    # stem; either way nothing is overwritten.
    assert second.name == "call (2).prompt"


def test_view_txt_is_the_numbered_view(pack_dir):
    view_text = (pack_dir / "view.txt").read_text(encoding="utf-8")
    assert "[T001 " in view_text
    assert re.search(r"\{M\d{3}\}", view_text)
    for word in CANARY:
        assert word in view_text  # the transcript itself belongs in the pack


def test_pack_build_logs_no_transcript_text(tmp_path, fixture_segments,
                                            fixture_meta, fixture_report,
                                            capsys):
    lines = []
    pack_module.build_pack(fixture_segments,
                           _meta(fixture_meta, fixture_report),
                           tmp_path, "call", log=lines.append)
    logged = "\n".join(lines) + capsys.readouterr().out
    for word in CANARY:
        assert word not in logged
    assert "pack_built" in logged


def test_missing_analysis_raises(tmp_path, fixture_segments, fixture_meta):
    with pytest.raises(pack_module.PackError):
        pack_module.build_pack(fixture_segments, dict(fixture_meta),
                               tmp_path, "call")


# -- the CLI ----------------------------------------------------------------

def test_cli_pack_with_analysis(tmp_path, fixture_dir, capsys):
    shutil.copy(fixture_dir / "call.json", tmp_path / "call.json")
    shutil.copy(fixture_dir / "call.analysis.json",
                tmp_path / "call.analysis.json")
    assert cli_main(["pack", str(tmp_path / "call.json")]) == 0
    pack_meta = json.loads(
        (tmp_path / "call.prompt" / "pack.json").read_text(encoding="utf-8"))
    assert pack_meta["prosody"] is True
    assert set(pack_meta["sources"]) == {"call.json", "call.analysis.json"}


def test_cli_pack_reanalyses_without_prosody(tmp_path, fixture_dir, capsys):
    shutil.copy(fixture_dir / "call.json", tmp_path / "call.json")
    assert cli_main(["pack", str(tmp_path / "call.json")]) == 0
    out = capsys.readouterr().out
    assert "re-analysing" in out
    pack_meta = json.loads(
        (tmp_path / "call.prompt" / "pack.json").read_text(encoding="utf-8"))
    assert pack_meta["prosody"] is False
