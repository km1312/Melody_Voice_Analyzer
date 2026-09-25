"""JSON Schemas for everything a model returns.

Validation is the first verifier rule: parse, then hold the shape to these
before any content check runs. The schemas are deliberately about structure,
not content — quotes, ids, convergence and wording are checked in
`verify.py`, in code, where they can be checked exactly. `additionalProperties`
stays open so a model adding a harmless key does not fail a run.
"""

TURN_ID = {"type": "string", "pattern": r"^T\d{3,}$"}
MOMENT_ID = {"type": "string", "pattern": r"^M\d{3,}$"}
TURN_IDS = {"type": "array", "items": TURN_ID}

LIKELIHOODS = ["very unlikely", "unlikely", "roughly even chance",
               "likely", "very likely"]
# The cap for stance/unsaid/relational readings (PR-7). "almost certain" is
# deliberately not in the vocabulary at all.
SHOWABLE_LIKELIHOODS = ["roughly even chance", "likely", "very likely"]
EVIDENCE_CONFIDENCE = ["low", "moderate", "high"]
CHANNELS = ["lexical", "timing", "prosody", "disfluency", "interaction"]
LAYERS = ["stance_commitment", "unsaid", "relational"]

_TOPIC = {
    "type": "object",
    "required": ["id", "label", "spans"],
    "properties": {
        "id": {"type": "string"},
        "label": {"type": "string"},
        "spans": {"type": "array",
                  "items": {"type": "array", "items": TURN_ID,
                            "minItems": 2, "maxItems": 2}},
        "raised_by": {"type": "string"},
    },
}

_FACT_LINE = {
    "type": "object",
    "required": ["text", "turn_ids"],
    "properties": {"text": {"type": "string"}, "turn_ids": TURN_IDS},
}

_ACTION_ITEM = {
    "type": "object",
    "required": ["task", "turn_ids"],
    "properties": {
        "owner": {"type": "string"},
        "task": {"type": "string"},
        "due": {"type": "string"},
        "turn_ids": TURN_IDS,
    },
}

_NOTES = {
    "type": "object",
    "required": ["summary", "decisions", "action_items", "open_questions",
                 "key_numbers"],
    "properties": {
        "summary": {"type": "string"},
        "decisions": {"type": "array", "items": _FACT_LINE},
        "action_items": {"type": "array", "items": _ACTION_ITEM},
        "open_questions": {"type": "array", "items": _FACT_LINE},
        "key_numbers": {"type": "array", "items": _FACT_LINE},
    },
}

_EVIDENCE_ITEM = {
    "type": "object",
    "required": ["turn_id", "channel"],
    "properties": {
        "turn_id": TURN_ID,
        "quote": {"type": "string"},
        "channel": {"enum": CHANNELS},
        "moment_ids": {"type": "array", "items": MOMENT_ID},
        "description": {"type": "string"},
    },
}

_INSIGHT = {
    "type": "object",
    "required": ["layer", "speaker", "claim", "likelihood",
                 "evidence_confidence", "evidence", "alternatives",
                 "follow_up"],
    "properties": {
        "id": {"type": "string"},
        "layer": {"enum": LAYERS},
        "speaker": {"type": "string"},
        "topic_id": {"type": "string"},
        "claim": {"type": "string"},
        "likelihood": {"enum": LIKELIHOODS},
        "evidence_confidence": {"enum": EVIDENCE_CONFIDENCE},
        "evidence": {"type": "array", "items": _EVIDENCE_ITEM, "minItems": 1},
        "alternatives": {"type": "array", "items": {"type": "string"}},
        "follow_up": {"type": "string"},
    },
}

_SPEAKER_ENTRY = {
    "type": "object",
    "required": ["label"],
    "properties": {
        "label": {"type": "string"},
        "nothing_notable": {"type": "boolean"},
        "cares_about": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["why", "turn_ids"],
                "properties": {
                    "topic_id": {"type": "string"},
                    "why": {"type": "string"},
                    "turn_ids": TURN_IDS,
                },
            },
        },
    },
}

INSIGHTS_DRAFT = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "insights_draft",
    "type": "object",
    "required": ["topics", "notes", "speakers", "insights"],
    "properties": {
        "working": {
            "type": "object",
            "properties": {
                "observations": {"type": "array"},
                "rejected": {"type": "array",
                             "items": {"type": "object",
                                       "properties": {
                                           "claim": {"type": "string"},
                                           "reason": {"type": "string"}}}},
            },
        },
        "topics": {"type": "array", "items": _TOPIC},
        "notes": _NOTES,
        "speakers": {"type": "array", "items": _SPEAKER_ENTRY},
        "insights": {"type": "array", "items": _INSIGHT},
        "so_what": {"type": "array",
                    "items": {"type": "object",
                              "required": ["text"],
                              "properties": {
                                  "text": {"type": "string"},
                                  "refs": {"type": "array",
                                           "items": {"type": "string"}}}}},
    },
}

PASS_A = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "pass_a",
    "type": "object",
    "required": ["topics", "facts", "observations", "per_speaker"],
    "properties": {
        "topics": {"type": "array", "items": _TOPIC},
        "facts": {
            "type": "object",
            "required": ["decisions", "action_items", "open_questions",
                         "key_numbers"],
            "properties": {
                "decisions": {"type": "array", "items": _FACT_LINE},
                "action_items": {"type": "array", "items": _ACTION_ITEM},
                "open_questions": {"type": "array", "items": _FACT_LINE},
                "key_numbers": {"type": "array", "items": _FACT_LINE},
            },
        },
        "observations": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "turn_id", "speaker", "channel",
                             "description"],
                "properties": {
                    "id": {"type": "string"},
                    "turn_id": TURN_ID,
                    "speaker": {"type": "string"},
                    "quote": {"type": "string"},
                    "channel": {"enum": CHANNELS},
                    "description": {"type": "string"},
                    "moment_ids": {"type": "array", "items": MOMENT_ID},
                    "topic_id": {"type": "string"},
                },
            },
        },
        "per_speaker": {"type": "array", "items": {"type": "object"}},
    },
}

PASS_B = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "pass_b",
    "type": "object",
    "required": ["clusters", "nothing_notable"],
    "properties": {
        "clusters": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "speaker", "layer", "readings", "favoured",
                             "likelihood", "evidence_confidence"],
                "properties": {
                    "id": {"type": "string"},
                    "speaker": {"type": "string"},
                    "topic_id": {"type": "string"},
                    "layer": {"enum": LAYERS},
                    "readings": {
                        "type": "array",
                        "minItems": 2,
                        "items": {
                            "type": "object",
                            "required": ["id", "text", "ordinary", "supports"],
                            "properties": {
                                "id": {"type": "string"},
                                "text": {"type": "string"},
                                "ordinary": {"type": "boolean"},
                                "supports": {"type": "array",
                                             "items": {"type": "string"}},
                                "against": {"type": "array",
                                            "items": {"type": "string"}},
                            },
                        },
                    },
                    "favoured": {"type": "string"},
                    "likelihood": {"enum": LIKELIHOODS},
                    "evidence_confidence": {"enum": EVIDENCE_CONFIDENCE},
                    "why": {"type": "string"},
                },
            },
        },
        "nothing_notable": {"type": "array", "items": {"type": "string"}},
    },
}

PASS_C = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "pass_c",
    "type": "object",
    "required": ["reviews"],
    "properties": {
        "reviews": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["cluster_id", "verdict"],
                "properties": {
                    "cluster_id": {"type": "string"},
                    "verdict": {"enum": ["keep", "downgrade", "drop"]},
                    "likelihood": {"enum": LIKELIHOODS},
                    "evidence_confidence": {"enum": EVIDENCE_CONFIDENCE},
                    "claim": {"type": "string"},
                    "reason": {"type": "string"},
                },
            },
        },
    },
}

COACHING = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "coaching",
    "type": "object",
    "required": ["observations", "nothing_to_report"],
    "properties": {
        "observations": {
            "type": "array",
            "maxItems": 3,
            "items": {
                "type": "object",
                "required": ["feature", "text"],
                "properties": {
                    "feature": {"type": "string"},
                    "text": {"type": "string"},
                    "turn_id": TURN_ID,
                    "try": {"type": "string"},
                },
            },
        },
        "nothing_to_report": {"type": "boolean"},
    },
}

SCHEMAS = {
    "pass_a": PASS_A,
    "pass_b": PASS_B,
    "pass_c": PASS_C,
    "insights_draft": INSIGHTS_DRAFT,
    "coaching": COACHING,
}


def problems(instance, schema):
    """Validation errors in plain words, best first; empty means valid."""
    import jsonschema

    validator = jsonschema.Draft202012Validator(schema)
    found = []
    for error in sorted(validator.iter_errors(instance),
                        key=lambda e: (len(e.absolute_path), str(e.absolute_path))):
        where = " → ".join(str(part) for part in error.absolute_path) or "top level"
        found.append("{0}: {1}".format(where, error.message))
    return found
