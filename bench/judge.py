"""The judge: blind pairwise comparison, order swapped, human-checkable.

The judge model must differ from both candidates and its id is recorded in
every report. `--human` walks the same anonymised pairs in the terminal so
judge-to-human agreement can be measured once per judge model (20 pairs is
the floor the PRD sets).
"""

import json

from revolv.interpret.verify import strip_response

JUDGE_PROMPT_VERSION = "j1.0.0"

JUDGE_PROMPT = """You are reviewing two sets of meeting notes and readings, A and B, made from the same recorded conversation. You also have the analysis view they were made from. Judge the output only against that view.

Score each of A and B from 1 to 5 on:
- faithfulness: every note and reading is supported by the cited turns; nothing is invented or stretched.
- usefulness: a reader who was on the call would act differently or ask something better because of it.
- non_obviousness: it tells the reader something they would likely not have written down themselves.
- over_reach (5 is worst): it claims feelings, motives or traits the evidence cannot carry, or implies deception.
- tone: tentative, respectful, written as if the person described might read it.

Then say which you would rather receive, A or B, or tie, in one sentence of reasoning. Do not reward length. A short output with two well-evidenced readings beats a long one with six weak ones. An output that honestly says 'nothing notable' can win.

Return JSON only:
{"A":{"faithfulness":0,"usefulness":0,"non_obviousness":0,"over_reach":0,"tone":0},
 "B":{"faithfulness":0,"usefulness":0,"non_obviousness":0,"over_reach":0,"tone":0},
 "prefer":"A","why":""}

<analysis_view>
@VIEW@
</analysis_view>
<output_a>
@OUTPUT_A@
</output_a>
<output_b>
@OUTPUT_B@
</output_b>"""

DIMENSIONS = ("faithfulness", "usefulness", "non_obviousness", "over_reach",
              "tone")


def build_prompt(view_text, output_a, output_b, swapped=False):
    if swapped:
        output_a, output_b = output_b, output_a
    # The prompt's JSON shape is full of braces, so no str.format here.
    return (JUDGE_PROMPT.replace("@VIEW@", view_text)
            .replace("@OUTPUT_A@", output_a)
            .replace("@OUTPUT_B@", output_b))


def _parse(text):
    reply = json.loads(strip_response(text))
    for side in ("A", "B"):
        scores = reply.get(side) or {}
        for dimension in DIMENSIONS:
            if not isinstance(scores.get(dimension), (int, float)):
                raise ValueError("missing score {0}.{1}".format(side,
                                                                dimension))
    if reply.get("prefer") not in ("A", "B", "tie"):
        raise ValueError("prefer must be A, B or tie")
    return reply


def _unswap(reply):
    swapped = {"A": reply["B"], "B": reply["A"],
               "prefer": {"A": "B", "B": "A"}.get(reply["prefer"], "tie"),
               "why": reply.get("why", "")}
    return swapped


def judge_pair(provider, view_text, output_a, output_b):
    """Judge twice with the order swapped; return both verdicts and the
    combined preference (a preference only when both orderings agree)."""
    verdicts = []
    for swapped in (False, True):
        completion = provider.complete(
            system="You are a careful, sceptical reviewer.",
            user=build_prompt(view_text, output_a, output_b, swapped),
            json_schema=None, temperature=0.2, seed=1, max_tokens=1200)
        reply = _parse(completion.text)
        verdicts.append(_unswap(reply) if swapped else reply)
    prefers = [v["prefer"] for v in verdicts]
    combined = prefers[0] if prefers[0] == prefers[1] else "tie"
    return {"verdicts": verdicts, "prefer": combined,
            "judge_prompt_version": JUDGE_PROMPT_VERSION}


def agreement(judge_prefers, human_prefers):
    """Share of pairs where the judge and the human said the same thing."""
    if not judge_prefers:
        return None
    hits = sum(1 for j, h in zip(judge_prefers, human_prefers) if j == h)
    return round(hits / len(judge_prefers), 3)


def human_review(pairs, ask=input, say=print):
    """The human judge: the same blind pairs, in the terminal.

    `pairs` is [(view_text, output_a, output_b)]; returns the preferences.
    """
    preferences = []
    for number, (view_text, output_a, output_b) in enumerate(pairs, 1):
        say("\n===== pair {0} of {1} =====".format(number, len(pairs)))
        say("--- output A ---\n{0}".format(output_a))
        say("--- output B ---\n{0}".format(output_b))
        while True:
            answer = ask("Which would you rather receive? [a/b/tie] ") \
                .strip().lower()
            if answer in ("a", "b", "tie"):
                preferences.append({"a": "A", "b": "B"}.get(answer, "tie"))
                break
    return preferences
