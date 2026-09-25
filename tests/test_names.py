"""The speaker-name guesser: propose from the words, never assert."""

from revolv.interpret.pack import render_context_block
from revolv.names import guess_me, guess_speaker_names, merge_with_context


def _turn(index, speaker, text):
    return {"index": index, "speaker": speaker, "text": text}


def _dialogue(*texts):
    """Alternating SPEAKER_00 / SPEAKER_01 turns."""
    return [_turn(i, "SPEAKER_{0:02d}".format(i % 2), text)
            for i, text in enumerate(texts)]


def test_self_introduction_names_the_speaker():
    turns = _dialogue(
        "Hi, I'm Kaden, thanks for making the time.",
        "Of course, good to see you.",
    )
    guesses = guess_speaker_names(turns)
    assert guesses["SPEAKER_00"]["name"] == "Kaden"
    assert guesses["SPEAKER_00"]["confidence"] == "high"
    assert guesses["SPEAKER_00"]["evidence"] == [0]


def test_vocatives_name_the_other_speaker():
    turns = _dialogue(
        "Thanks, Brian.",
        "Sure thing.",
        "What do you think, Brian?",
        "I think it works.",
    )
    guesses = guess_speaker_names(turns)
    assert guesses["SPEAKER_01"]["name"] == "Brian"
    assert "SPEAKER_00" not in guesses


def test_one_mention_is_not_enough():
    """A single 'Hi, Grace' to a bystander must not rename anyone — the
    Sanjay-call case from the diarization notes."""
    turns = _dialogue(
        "It's still in progress. Hi, Grace. Good to see you.",
        "Right, so about the report.",
    )
    assert guess_speaker_names(turns) == {}


def test_capitalised_conversation_words_are_not_names():
    turns = _dialogue(
        "Thanks, Man. Okay, Monday. Yes, Perfect.",
        "Thanks, Man. Okay, Monday. Yes, Perfect.",
        "Right, Sure. Hello, Zoom.",
        "Right, Sure. Hello, Zoom.",
    )
    assert guess_speaker_names(turns) == {}


def test_dictionary_terms_count_double():
    turns = _dialogue("Thanks, Chom.", "You're welcome.")
    assert guess_speaker_names(turns) == {}          # one mention: too thin
    guesses = guess_speaker_names(turns, vocabulary=["Chom"])
    assert guesses["SPEAKER_01"]["name"] == "Chom"   # the user named them


def test_one_name_cannot_win_two_speakers():
    turns = [
        _turn(0, "SPEAKER_00", "I'm Brian, hello."),
        _turn(1, "SPEAKER_01", "I'm Brian too, confusingly."),
        _turn(2, "SPEAKER_00", "Ha."),
    ]
    assert guess_speaker_names(turns) == {}          # a dead heat names nobody


def test_typed_names_silence_guesses():
    guesses = {"SPEAKER_00": {"name": "Brian", "votes": 4,
                              "confidence": "high", "evidence": [1]}}
    assert merge_with_context(guesses, {"SPEAKER_00": "Kaden"}) == {}
    assert merge_with_context(guesses, {"SPEAKER_00": "  "}) == guesses
    assert merge_with_context(guesses, {}) == guesses


def _report(*baselines):
    return {"speakers": {label: {"baseline_turns": turns}
                         for label, turns in baselines}}


TWO_MAINS = _report(("SPEAKER_00", 20), ("SPEAKER_01", 25),
                    ("SPEAKER_02", 0))


def test_guess_me_from_the_recordings_title():
    guess = guess_me(TWO_MAINS, {"SPEAKER_01": "Brian"},
                     "2026-09-25 12-32-29 Brian.mkv")
    assert guess["label"] == "SPEAKER_00"
    assert guess["counterpart"] == "SPEAKER_01"
    assert guess["counterpart_name"] == "Brian"
    assert guess["confidence"] == "low"
    # A guessed display name with its question mark works the same.
    assert guess_me(TWO_MAINS, {"SPEAKER_01": "Brian?"},
                    "Brian call.mkv")["label"] == "SPEAKER_00"


def test_guess_me_from_being_addressed():
    """The real 2026-09-25 case: the call is filed as Brian, Brian is never
    addressed by name, but the user is ('Thanks, Caden'), so the guessed
    name differs from the title's and marks the user."""
    guess = guess_me(TWO_MAINS, {"SPEAKER_00": "Caden"},
                     "2026-09-25 12-32-29 Brian.mkv")
    assert guess["label"] == "SPEAKER_00"
    assert guess["counterpart"] == "SPEAKER_01"
    assert guess["counterpart_name"] == "Brian"


def test_guess_me_declines_when_unclear():
    # The title names nobody (no capitalised token), so neither rule fires.
    assert guess_me(TWO_MAINS, {"SPEAKER_01": "Brian"},
                    "team standup.mkv") is None
    # No name on the call and no match either.
    assert guess_me(TWO_MAINS, {}, "Brian.mkv") is None
    # Both mains are named in the title.
    assert guess_me(TWO_MAINS, {"SPEAKER_00": "Kaden",
                                "SPEAKER_01": "Brian"},
                    "Kaden and Brian.mkv") is None
    # Not a two-sided call.
    three = _report(("SPEAKER_00", 20), ("SPEAKER_01", 25),
                    ("SPEAKER_02", 15))
    assert guess_me(three, {"SPEAKER_01": "Brian"}, "Brian.mkv") is None
    one = _report(("SPEAKER_00", 20), ("SPEAKER_01", 0))
    assert guess_me(one, {"SPEAKER_01": "Brian"}, "Brian.mkv") is None


def test_context_block_marks_guesses_unconfirmed():
    guesses = {"SPEAKER_01": {"name": "Brian", "votes": 4,
                              "confidence": "high", "evidence": [1]}}
    block = render_context_block({"meeting_type": "other"}, guessed=guesses)
    assert "SPEAKER_01 may be Brian (guessed from the transcript, " \
           "unconfirmed)" in block
    # A typed name for the same label wins and the guess line disappears.
    block = render_context_block(
        {"meeting_type": "other",
         "speaker_names": {"SPEAKER_01": "Ramsey"}}, guessed=guesses)
    assert "SPEAKER_01 is Ramsey" in block
    assert "guessed" not in block
