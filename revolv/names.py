"""Guess who each diarized speaker is, from what was actually said.

Two cues carry almost all of the signal in real calls. A self-introduction
("I'm Brian", "my name is Brian", "this is Brian" on a call opening) names
the speaker of the turn. A vocative ("thanks, Brian", "Brian, what do you
think?") names someone *else* — credited to the nearest other speaker
around the turn, which is right most of the time in a two-person call and
deliberately under-weighted beyond that, because "Hi, Grace" said to a
bystander must not rename a main speaker (that exact case exists in the
test calls).

These are guesses, and they are treated as guesses everywhere: the UI shows
them with a question mark until the user confirms them in the Context
window, the prompt pack marks them unconfirmed, and nothing here ever
overrides a name the user typed. The raw transcript files are not touched.

Pure functions over the report's turns, so it runs identically from the app
and from a bare `.analysis.json`.
"""

import re
from collections import defaultdict

# A capitalised token after a trigger is not automatically a name. These are
# the capitalised words conversation actually produces in those positions.
_NOT_NAMES = {
    "i", "ok", "okay", "yeah", "yes", "no", "right", "well", "so", "and",
    "but", "oh", "um", "uh", "hi", "hey", "hello", "bye", "thanks", "thank",
    "sorry", "cool", "great", "good", "perfect", "awesome", "sure", "wait",
    "actually", "anyway", "alright", "exactly", "absolutely", "honestly",
    "look", "listen", "man", "guys", "everyone", "everybody", "team", "sir",
    "madam", "buddy", "dude", "god", "jesus", "christ", "monday", "tuesday",
    "wednesday", "thursday", "friday", "saturday", "sunday", "january",
    "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "zoom", "google",
    "teams", "meet", "gotcha", "correct", "true", "interesting", "nice",
    "morning", "afternoon", "evening", "night", "today", "tomorrow",
    "yesterday", "please", "welcome", "cheers", "later", "now", "one",
    "two", "three", "what", "who", "why", "how", "where", "when",
    # Discourse markers a verbatim transcript capitalises at sentence
    # starts; "Like," alone out-voted every real name on the test calls.
    "like", "so", "see", "look", "say", "know", "mean", "guess", "then",
    "also", "maybe", "basically", "obviously", "literally", "totally",
    "definitely", "probably", "again", "though", "still", "fine", "done",
    "wow", "huh", "yep", "nope", "come", "go", "stop", "hold", "hang",
    "first", "second", "next", "last", "plus", "minus", "anyways",
}

_NAME = r"([A-Z][a-z]+(?:-[A-Z][a-z]+)?)"

# Assigns the name to the speaker of the turn.
_SELF_INTRO = re.compile(
    r"\b(?:I'?m|I am|my name is|my name'?s|this is)\s+" + _NAME + r"\b")

# Assigns the name to a nearby *other* speaker. There is deliberately no
# sentence-leading pattern ("Brian, could we..."): discourse openers a
# verbatim transcript capitalises ("Like,", "Look,", "Now,") share that
# exact shape, and on real calls they out-vote every genuine name.
_VOCATIVES = [
    # "thanks, Brian" / "hi Brian" / "bye Brian"
    re.compile(r"\b(?:hi|hey|hello|thanks|thank you|bye|goodbye|yes|no|"
               r"okay|sorry|right|sure|exactly|welcome|morning|afternoon)"
               r"[,!]?\s+" + _NAME + r"\b[,.!?]"),
    # "..., Brian?" / "..., Brian." — a trailing vocative.
    re.compile(r",\s+" + _NAME + r"[.!?]"),
]

SELF_INTRO_VOTES = 3
MIN_VOTES = 2


def _plausible(name):
    return (name and name[0].isupper() and len(name) >= 2
            and name.lower() not in _NOT_NAMES)


def _nearby_other_speaker(turns, index):
    """Who a vocative in turn `index` most likely addresses: the next
    speaker to talk, else the previous one."""
    speaker = turns[index]["speaker"]
    for turn in turns[index + 1:]:
        if turn["speaker"] != speaker:
            return turn["speaker"]
    for turn in reversed(turns[:index]):
        if turn["speaker"] != speaker:
            return turn["speaker"]
    return None


def guess_speaker_names(turns, vocabulary=()):
    """{label: {"name", "confidence", "votes", "evidence"}} for the speakers
    the transcript itself names. Labels with nothing to go on are absent.

    `vocabulary` is the user's Dictionary; a candidate that matches one of
    its terms is a name the user already told the app about, so it counts
    double.
    """
    turns = list(turns or [])
    known = {term.strip().lower() for term in vocabulary if term.strip()}
    votes = defaultdict(lambda: defaultdict(int))
    evidence = defaultdict(lambda: defaultdict(list))

    def vote(label, name, weight, turn_index):
        if label is None or not _plausible(name):
            return
        if name.lower() in known:
            weight *= 2
        votes[label][name.lower().capitalize()] += weight
        evidence[label][name.lower().capitalize()].append(turn_index)

    for position, turn in enumerate(turns):
        text = turn.get("text") or ""
        speaker = turn.get("speaker")
        for match in _SELF_INTRO.finditer(text):
            vote(speaker, match.group(1), SELF_INTRO_VOTES, turn["index"])
        for pattern in _VOCATIVES:
            for match in pattern.finditer(text):
                vote(_nearby_other_speaker(turns, position), match.group(1),
                     1, turn["index"])

    # One winner per speaker, and one speaker per name: a name that leads on
    # two labels stays only where its case is strongest.
    best = {}
    for label, counts in votes.items():
        name, count = max(counts.items(), key=lambda kv: kv[1])
        if count >= MIN_VOTES:
            best[label] = (name, count)
    by_name = defaultdict(list)
    for label, (name, count) in best.items():
        by_name[name].append((count, label))
    guesses = {}
    for name, claimants in by_name.items():
        claimants.sort(reverse=True)
        if len(claimants) > 1 and claimants[0][0] == claimants[1][0]:
            continue  # a dead heat names nobody
        count, label = claimants[0]
        guesses[label] = {
            "name": name,
            "votes": count,
            "confidence": "high" if count >= 3 else "low",
            "evidence": sorted(set(evidence[label][name]))[:6],
        }
    return guesses


def guess_me(report, names, source_name):
    """Which speaker is probably the user, on a two-sided call.

    The recordings this app sees are named after the *other* person
    ("2026-09-25 Brian.mkv"), so when exactly two speakers have baselines
    and exactly one of them carries a name that appears in the recording's
    own title, the user is probably the other one. Anything less clear-cut
    returns None: a wrong "me" would quietly poison the coaching history,
    which is why callers treat this as a preview until confirmed.

    `names` maps labels to names, typed or guessed alike.
    """
    speakers = (report or {}).get("speakers") or {}
    main = [label for label, entry in speakers.items()
            if entry.get("baseline_turns")]
    if len(main) != 2:
        return None
    tokens = {token.lower()
              for token in re.findall(r"[A-Za-z]+", source_name or "")
              if len(token) >= 2 and token.lower() not in _NOT_NAMES}
    # Rule 1: exactly one main speaker carries the name the recording is
    # titled after — the counterpart — so the user is the other one.
    counterparts = [label for label in main
                    if (names.get(label) or "").strip().rstrip("?")
                    .lower() in tokens]
    if len(counterparts) == 1:
        counterpart = counterparts[0]
        me = main[0] if main[1] == counterpart else main[1]
        return {"label": me,
                "counterpart": counterpart,
                "counterpart_name": (names.get(counterpart) or "")
                .rstrip("?"),
                "confidence": "low"}

    # Rule 2, the inverse: the title names somebody (a capitalised token),
    # and the one name the call itself produced belongs to somebody *else*
    # — usually the counterpart addressing the user ("Thanks, Kaden" on a
    # call filed as "Brian"). The differently-named speaker is the user.
    named = {label: (names.get(label) or "").strip().rstrip("?")
             for label in main if (names.get(label) or "").strip()}
    title_names = {token for token
                   in re.findall(r"\b[A-Z][a-z]{2,}\b", source_name or "")
                   if token.lower() not in _NOT_NAMES}
    if len(named) == 1 and title_names:
        label, name = next(iter(named.items()))
        if name.lower() not in {t.lower() for t in title_names}:
            other = main[0] if main[1] == label else main[1]
            return {"label": label,
                    "counterpart": other,
                    "counterpart_name": sorted(title_names)[0],
                    "confidence": "low"}
    return None


def merge_with_context(guesses, speaker_names):
    """Guesses only where the user has not spoken: a typed name always wins,
    and a guess never fills a label the user named."""
    named = {label for label, name in (speaker_names or {}).items()
             if (name or "").strip()}
    return {label: guess for label, guess in (guesses or {}).items()
            if label not in named}
