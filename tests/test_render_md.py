"""The shared renderer: same bytes as before, and ids that strip away."""

import re

from revolv.writers import NUMBERED_LEGEND, moment_id, render_md, turn_id


def _meta_for(fixture_meta, fixture_report):
    return dict(fixture_meta, analysis=fixture_report, numbers_file=True)


def test_plain_render_matches_the_committed_md(fixture_dir, fixture_meta,
                                               fixture_report):
    """write_md's output must be byte-identical across the refactor. The
    committed fixture .md was written by the pre-refactor code path."""
    rendered = render_md(fixture_report, _meta_for(fixture_meta, fixture_report))
    committed = (fixture_dir / "call.md").read_text(encoding="utf-8")
    assert rendered == committed


def _strip_ids(numbered):
    text = numbered.replace("\n" + NUMBERED_LEGEND + "\n", "", 1)
    text = re.sub(r"^- M\d{3,} (\d{2}:\d{2} \S+) T\d{3,} - ", r"- \1 - ",
                  text, flags=re.MULTILINE)
    text = re.sub(r"^\[T\d{3,} (\d{2}:\d{2})\]", r"[\1]", text,
                  flags=re.MULTILINE)
    text = re.sub(r" \{M\d{3,}\}", "", text)
    return text


def test_stripping_ids_recovers_the_plain_md(fixture_meta, fixture_report):
    meta = _meta_for(fixture_meta, fixture_report)
    plain = render_md(fixture_report, meta)
    numbered = render_md(fixture_report, meta, numbered=True)
    assert numbered != plain
    assert _strip_ids(numbered) == plain


def test_ids_are_deterministic(fixture_meta, fixture_report):
    meta = _meta_for(fixture_meta, fixture_report)
    first = render_md(fixture_report, meta, numbered=True)
    second = render_md(fixture_report, meta, numbered=True)
    assert first == second


def test_id_formats():
    assert turn_id(0) == "T001"
    assert turn_id(56) == "T057"
    assert turn_id(1205) == "T1206"
    assert moment_id(1) == "M001"
    assert moment_id(17) == "M017"


def test_numbered_legend_present_only_in_numbered_mode(fixture_meta,
                                                       fixture_report):
    meta = _meta_for(fixture_meta, fixture_report)
    assert NUMBERED_LEGEND in render_md(fixture_report, meta, numbered=True)
    assert NUMBERED_LEGEND not in render_md(fixture_report, meta)
