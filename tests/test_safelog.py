import pytest

from revolv.safelog import UnsafeLogValue, log_event


def test_ids_counts_and_durations_pass(capsys):
    line = log_event("pack_built", call="a1b2c3", turns=41, seconds=1.25,
                     prosody=True, model=None)
    assert line == ("[melody] pack_built call=a1b2c3 turns=41 seconds=1.25 "
                    "prosody=true model=none")
    assert capsys.readouterr().out.strip() == line


def test_emit_callback_receives_the_line():
    seen = []
    log_event("verify_done", emit=seen.append, kept=4, dropped=7)
    assert seen == ["[melody] verify_done kept=4 dropped=7"]


def test_free_text_is_refused():
    with pytest.raises(UnsafeLogValue):
        log_event("bad", note="this is a sentence from a call")


def test_long_tokens_are_refused():
    with pytest.raises(UnsafeLogValue):
        log_event("bad", token="x" * 41)


def test_unloggable_types_are_refused():
    with pytest.raises(UnsafeLogValue):
        log_event("bad", data={"quote": "hello"})
    with pytest.raises(UnsafeLogValue):
        log_event("bad", items=["a", "b"])


def test_event_name_follows_the_same_rule():
    with pytest.raises(UnsafeLogValue):
        log_event("two words")
