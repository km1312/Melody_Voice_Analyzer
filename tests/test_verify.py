"""The verifier, rule by rule, plus the golden response (PRD 7.4, M4)."""

import pytest

from revolv.interpret import verify as verify_module
from revolv.interpret import view as view_module
from revolv.interpret.verify import parse_response, verify


@pytest.fixture(scope="module")
def ctx(request):
    """View, report and the fixture's landmark turns, shared per module."""
    report = request.getfixturevalue("fixture_report")
    segments = request.getfixturevalue("fixture_segments")
    meta = dict(request.getfixturevalue("fixture_meta"), analysis=report,
                numbers_file=True)
    view = view_module.build(report, segments, meta)

    cluster_mid = None
    for mid, moment in view.moments.items():
        if any(e["feature"] == "medial_fillers" for e in moment["evidence"]):
            cluster_mid = mid
    assert cluster_mid
    cluster_tid = view.moments[cluster_mid]["turn_id"]

    s0_moments = [(mid, m) for mid, m in sorted(view.moments.items())
                  if view.turns[m["turn_id"]]["speaker"] == "SPEAKER_00"
                  and any(e["feature"] != "medial_fillers"
                          for e in m["evidence"])]
    assert len(s0_moments) >= 4
    return {"view": view, "report": report, "meta": meta,
            "segments": segments, "cluster_mid": cluster_mid,
            "cluster_tid": cluster_tid, "s0_moments": s0_moments}


def quote_of(view, tid, words=8, skip=0):
    return " ".join(view.turns[tid]["text"].split()[skip:skip + words])


def sound_reading(ctx, ident="ins_001"):
    view = ctx["view"]
    tid, mid = ctx["cluster_tid"], ctx["cluster_mid"]
    return {
        "id": ident, "layer": "unsaid", "speaker": "SPEAKER_01",
        "topic_id": "tp1",
        "claim": "May have an unvoiced reservation here; worth checking.",
        "likelihood": "roughly even chance", "evidence_confidence": "low",
        "evidence": [
            {"turn_id": tid, "quote": quote_of(view, tid),
             "channel": "lexical", "moment_ids": [],
             "description": "soft agreement"},
            {"turn_id": tid, "quote": "", "channel": "timing",
             "moment_ids": [],
             "description": "replies far above their usual"},
            {"turn_id": tid, "quote": "", "channel": "disfluency",
             "moment_ids": [mid], "description": "cluster of fillers"},
        ],
        "alternatives": ["Thinking time on a hard question"],
        "follow_up": "What would make this feel solid to you?",
    }


def s0_reading(ctx, index, confidence="moderate", ident=None):
    view = ctx["view"]
    mid, moment = ctx["s0_moments"][index % len(ctx["s0_moments"])]
    tid = moment["turn_id"]
    return {
        "id": ident or "s0_{0}".format(index), "layer": "stance_commitment",
        "speaker": "SPEAKER_00", "topic_id": "tp1",
        "claim": "The commitment here may be softer than the words.",
        "likelihood": "likely", "evidence_confidence": confidence,
        "evidence": [
            {"turn_id": tid, "quote": quote_of(view, tid, 6),
             "channel": "lexical", "moment_ids": [], "description": "hedge"},
            {"turn_id": tid, "quote": "", "channel": "prosody",
             "moment_ids": [mid], "description": "delivery shifted"},
        ],
        "alternatives": ["Ordinary emphasis"],
        "follow_up": "Shall we put a date on it?",
    }


def draft_with(insights, **extra):
    draft = {
        "topics": [{"id": "tp1", "label": "The plan",
                    "spans": [["T001", "T010"]], "raised_by": "SPEAKER_00"}],
        "notes": {"summary": "A synthetic review call.", "decisions": [],
                  "action_items": [], "open_questions": [], "key_numbers": []},
        "speakers": [],
        "insights": insights,
    }
    draft.update(extra)
    return draft


def run(ctx, insights, context=None, **kw):
    return verify(draft_with(insights), ctx["view"], ctx["report"],
                  context=context, **kw)


# -- rule-by-rule -----------------------------------------------------------

def test_sound_reading_is_kept_and_enriched(ctx):
    result = run(ctx, [sound_reading(ctx)])
    assert len(result.kept) == 1
    kept = result.kept[0]
    assert kept["channels"] == ["disfluency", "lexical", "timing"]
    assert kept["verified"]["reply_latency_s"] >= 2.0
    assert kept["verified"]["median_reply_s"] > 0
    assert kept["verified"]["moments"][0]["id"] == ctx["cluster_mid"]
    assert any(n["feature"] == "medial_fillers"
               for n in kept["verified"]["moments"][0]["notes"])
    assert kept["audio_range"]["start_ms"] == \
        ctx["view"].turns[ctx["cluster_tid"]]["start_ms"] - 1500
    assert kept["key"]


def test_no_baseline_speaker_is_dropped(ctx):
    reading = sound_reading(ctx)
    reading["speaker"] = "SPEAKER_02"
    result = run(ctx, [reading])
    assert not result.kept
    assert result.dropped[0]["reason"] == "no_baseline"


def test_unknown_speaker_is_dropped(ctx):
    reading = sound_reading(ctx)
    reading["speaker"] = "SPEAKER_31"
    result = run(ctx, [reading])
    assert result.dropped[0]["reason"] == "unknown_speaker"


def test_me_speaker_is_dropped(ctx):
    result = run(ctx, [sound_reading(ctx)], context={"me": "SPEAKER_01"})
    assert result.dropped[0]["reason"] == "about_reader"


def test_invented_quote_drops_the_reading(ctx):
    reading = sound_reading(ctx)
    reading["evidence"][0]["quote"] = "the purple elephant negotiation"
    reading["evidence"] = reading["evidence"][:2]  # lexical + timing only
    result = run(ctx, [reading])
    assert result.dropped[0]["reason"] == "quote_mismatch"
    assert result.evidence_quote_rejected == 1


def test_long_quotes_are_rejected(ctx):
    reading = sound_reading(ctx)
    reading["evidence"][0]["quote"] = " ".join(["word"] * 26)
    reading["evidence"] = reading["evidence"][:2]
    result = run(ctx, [reading])
    assert not result.kept


def test_wrong_speaker_turn_is_rejected(ctx):
    reading = sound_reading(ctx)
    s0_tid = ctx["s0_moments"][0][1]["turn_id"]
    reading["evidence"][0]["turn_id"] = s0_tid
    reading["evidence"][0]["quote"] = quote_of(ctx["view"], s0_tid, 5)
    result = run(ctx, [reading])
    kept_channels = result.kept[0]["channels"] if result.kept else []
    assert "lexical" not in kept_channels


def test_prosody_needs_a_non_filler_moment_on_that_turn(ctx):
    reading = s0_reading(ctx, 0)
    # Cite the cluster moment (medial fillers, another turn entirely).
    reading["evidence"][1]["moment_ids"] = [ctx["cluster_mid"]]
    result = run(ctx, [reading])
    assert not result.kept
    assert result.dropped[0]["reason"] == "convergence"


def test_prosody_only_fails_convergence(ctx):
    reading = s0_reading(ctx, 0)
    reading["evidence"] = [reading["evidence"][1]]
    result = run(ctx, [reading])
    assert result.dropped[0]["reason"] == "convergence"


def test_disfluency_from_quote_span_kinds(ctx):
    view = ctx["view"]
    tid = ctx["cluster_tid"]
    text = view.turns[tid]["text"].split()
    # A span with two "um"s in it: find the first "um" and take neighbours.
    first_um = text.index("um")
    quote = " ".join(text[max(first_um - 1, 0):first_um + 6])
    assert text.count("um") >= 2
    reading = sound_reading(ctx)
    reading["evidence"][2] = {"turn_id": tid, "quote": quote,
                              "channel": "disfluency", "moment_ids": [],
                              "description": "fillers mid-sentence"}
    result = run(ctx, [reading])
    assert result.kept and "disfluency" in result.kept[0]["channels"]


def test_timing_needs_gap_or_pause(ctx):
    reading = s0_reading(ctx, 0)
    tid = reading["evidence"][0]["turn_id"]
    reading["evidence"][1] = {"turn_id": tid, "quote": "",
                              "channel": "timing", "moment_ids": [],
                              "description": "slow reply"}
    result = run(ctx, [reading])
    # That SPEAKER_00 turn has no long gap and no long pause.
    assert not result.kept


def test_likelihood_below_even_chance_drops(ctx):
    reading = sound_reading(ctx)
    reading["likelihood"] = "unlikely"
    result = run(ctx, [reading])
    assert result.dropped[0]["reason"] == "not_likely_enough"


def test_missing_alternative_drops(ctx):
    reading = sound_reading(ctx)
    reading["alternatives"] = ["  "]
    result = run(ctx, [reading])
    assert result.dropped[0]["reason"] == "no_alternative"


def test_banned_wording_drops(ctx):
    for text in ("He is lying about the budget.",
                 "Seems deceptive on pricing.",
                 "An evasive person under pressure.",
                 "Probably hiding a concern."):
        reading = sound_reading(ctx)
        reading["claim"] = text
        result = run(ctx, [reading])
        assert result.dropped[0]["reason"] == "wording", text


def test_caps_keep_the_best_evidenced(ctx):
    readings = [s0_reading(ctx, 0, "high", "a"),
                s0_reading(ctx, 1, "low", "b"),
                s0_reading(ctx, 2, "moderate", "c"),
                s0_reading(ctx, 3, "high", "d"),
                s0_reading(ctx, 4, "moderate", "e")]
    result = run(ctx, readings, max_per_speaker=3)
    assert len(result.kept) == 3
    confidences = [r["evidence_confidence"] for r in result.kept]
    assert confidences == ["high", "high", "moderate"]
    assert result.dropped_by_reason["cap"] == 2


def test_call_cap(ctx):
    readings = [sound_reading(ctx, "s1")] + \
        [s0_reading(ctx, i, "high", "x{0}".format(i)) for i in range(3)]
    result = run(ctx, readings, max_per_call=2)
    assert len(result.kept) == 2
    assert result.dropped_by_reason["cap"] == 2


def test_note_lines_with_unknown_turns_are_removed(ctx):
    draft = draft_with([], notes={
        "summary": "Fine.",
        "decisions": [{"text": "Ship it", "turn_ids": ["T001"]},
                      {"text": "Phantom", "turn_ids": ["T999"]}],
        "action_items": [{"owner": "SPEAKER_00", "task": "Send the deck",
                          "due": "", "turn_ids": ["T003"]}],
        "open_questions": [{"text": "He was lying though?",
                            "turn_ids": ["T001"]}],
        "key_numbers": [],
    })
    result = verify(draft, ctx["view"], ctx["report"])
    assert [d["text"] for d in result.notes["decisions"]] == ["Ship it"]
    assert result.notes["action_items"][0]["task"] == "Send the deck"
    assert result.notes["open_questions"] == []  # banned wording in a line
    assert result.dropped_by_reason["unverified_note_line"] == 1
    assert result.dropped_by_reason["wording_note_line"] == 1


def test_topics_and_so_what_are_filtered(ctx):
    draft = draft_with(
        [sound_reading(ctx, "ins_keep")],
        topics=[{"id": "tp1", "label": "Real",
                 "spans": [["T001", "T004"], ["T900", "T901"]]},
                {"id": "tp2", "label": "Phantom",
                 "spans": [["T900", "T901"]]}],
        so_what=[{"text": "Follow up on the reservation.",
                  "refs": ["ins_keep", "ins_gone"]}])
    result = verify(draft, ctx["view"], ctx["report"])
    assert [t["id"] for t in result.topics] == ["tp1"]
    assert result.topics[0]["spans"] == [["T001", "T004"]]
    assert result.so_what[0]["refs"] == ["ins_keep"]


def test_model_rejected_work_is_recorded(ctx):
    draft = draft_with([], working={
        "observations": [],
        "rejected": [{"claim": "Too thin", "reason": "voice only"}]})
    result = verify(draft, ctx["view"], ctx["report"])
    assert {"claim": "Too thin", "reason": "model_rejected"} in result.dropped


# -- parse ------------------------------------------------------------------

def test_parse_strips_fences_and_prose():
    text = 'Here you go:\n```json\n{"topics": [], "notes": {"summary": "",' \
           ' "decisions": [], "action_items": [], "open_questions": [],' \
           ' "key_numbers": []}, "speakers": [], "insights": []}\n```'
    draft, problems = parse_response(text)
    assert problems == []
    assert draft["insights"] == []


def test_parse_reports_bad_json_plainly():
    draft, problems = parse_response("not json at all")
    assert draft is None
    assert "not valid JSON" in problems[0]


def test_parse_reports_shape_problems_with_the_key():
    draft, problems = parse_response('{"topics": []}')
    assert problems
    assert "notes" in problems[0]


# -- the golden response (M4.7) --------------------------------------------

def test_golden_response(ctx):
    view = ctx["view"]
    sound = sound_reading(ctx, "ins_sound")

    invented = sound_reading(ctx, "ins_invented")
    invented["evidence"] = [
        {"turn_id": ctx["cluster_tid"],
         "quote": "the purple elephant negotiation", "channel": "lexical",
         "moment_ids": [], "description": "invented"},
        dict(sound["evidence"][1])]

    prosody_only = s0_reading(ctx, 0, ident="ins_prosody_only")
    prosody_only["evidence"] = [prosody_only["evidence"][1]]

    wrong_moment = s0_reading(ctx, 1, ident="ins_wrong_moment")
    wrong_moment["evidence"][1]["moment_ids"] = [ctx["cluster_mid"]]

    banned = sound_reading(ctx, "ins_banned")
    banned["claim"] = "He is concealing his objection."

    unlikely = sound_reading(ctx, "ins_unlikely")
    unlikely["likelihood"] = "very unlikely"

    minor = sound_reading(ctx, "ins_minor")
    minor["speaker"] = "SPEAKER_02"

    five_for_s0 = [s0_reading(ctx, i, "moderate", "ins_s0_{0}".format(i))
                   for i in range(5)]

    draft = draft_with([sound, invented, prosody_only, wrong_moment,
                        banned, unlikely, minor] + five_for_s0)
    result = verify(draft, view, ctx["report"])

    kept_ids = {r["id"] for r in result.kept}
    assert "ins_sound" in kept_ids
    assert len([i for i in kept_ids if i.startswith("ins_s0_")]) == 3
    assert len(result.kept) == 4
    assert result.dropped_by_reason == {
        "quote_mismatch": 1, "convergence": 2, "wording": 1,
        "not_likely_enough": 1, "no_baseline": 1, "cap": 2}
    assert result.proposed == 12
