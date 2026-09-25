"""Deterministic metrics over cell records (PRD section 10).

Everything here reads `cell.json` records — ids and numbers — plus, for
recall, a call's `gold.json`. Two readings match across seeds when speaker
and layer agree and their evidence turns overlap by half or more.
"""

import statistics as st

LIKELIHOOD_ORDER = ["roughly even chance", "likely", "very likely"]


def _ok(records):
    return [r for r in records if r.get("status") == "ok"]


def group_key(record):
    return (record.get("model"), record.get("mode"), record.get("variant"))


def groups(records):
    grouped = {}
    for record in _ok(records):
        grouped.setdefault(group_key(record), []).append(record)
    return grouped


def deterministic(records):
    """One metrics row per (model, mode, variant)."""
    rows = {}
    for key, cells in groups(records).items():
        verifiers = [c.get("verifier") or {} for c in cells]
        proposed = sum(v.get("proposed", 0) for v in verifiers)
        evidence_proposed = sum(v.get("evidence_proposed", 0)
                                for v in verifiers)
        quote_rejected = sum(v.get("evidence_quote_rejected", 0)
                             for v in verifiers)
        dropped = {}
        for v in verifiers:
            for reason, count in (v.get("dropped_by_reason") or {}).items():
                dropped[reason] = dropped.get(reason, 0) + count
        described = sum(c.get("speakers_described", 0) for c in cells)
        rows[key] = {
            "cells": len(cells),
            "kept_per_call": round(st.mean(
                [c.get("kept", 0) for c in cells]), 2),
            "proposed": proposed,
            "quote_mismatch_rate": round(quote_rejected / evidence_proposed,
                                         3) if evidence_proposed else None,
            "convergence_violation_rate": round(
                dropped.get("convergence", 0) / proposed, 3)
            if proposed else None,
            "wording_violations": dropped.get("wording", 0)
            + dropped.get("wording_note_line", 0),
            "abstention_rate": round(sum(
                c.get("nothing_notable", 0) for c in cells) / described, 3)
            if described else None,
            "mean_seconds": round(st.mean(
                [c.get("seconds", 0) for c in cells]), 1),
            "tokens_out": sum(c.get("tokens_out") or 0 for c in cells),
        }
        retest = test_retest(cells)
        rows[key].update(retest)
    return rows


# -- test-retest -------------------------------------------------------------

def _match(a, b):
    if a["speaker"] != b["speaker"] or a["layer"] != b["layer"]:
        return False
    turns_a, turns_b = set(a["turns"]), set(b["turns"])
    if not turns_a or not turns_b:
        return False
    # Matched when the evidence turns overlap by half of the smaller set.
    overlap = len(turns_a & turns_b)
    return overlap * 2 >= min(len(turns_a), len(turns_b))


def match_readings(first, second):
    pairs = []
    used = set()
    for a in first:
        for index, b in enumerate(second):
            if index in used:
                continue
            if _match(a, b):
                pairs.append((a, b))
                used.add(index)
                break
    return pairs


def _within_one_band(a, b):
    try:
        return abs(LIKELIHOOD_ORDER.index(a) - LIKELIHOOD_ORDER.index(b)) <= 1
    except ValueError:
        return False


def test_retest(cells):
    """Jaccard over matched readings across seeds of the same call, and the
    share of matched pairs within one likelihood band."""
    by_call = {}
    for cell in cells:
        by_call.setdefault(cell.get("call"), []).append(cell)
    jaccards = []
    band_hits, band_total = 0, 0
    for call_cells in by_call.values():
        seeds = sorted(call_cells, key=lambda c: c.get("seed", 0))
        for first, second in zip(seeds, seeds[1:]):
            a = first.get("readings") or []
            b = second.get("readings") or []
            if not a and not b:
                jaccards.append(1.0)
                continue
            pairs = match_readings(a, b)
            union = len(a) + len(b) - len(pairs)
            jaccards.append(len(pairs) / union if union else 1.0)
            for pa, pb in pairs:
                band_total += 1
                if _within_one_band(pa.get("likelihood"),
                                    pb.get("likelihood")):
                    band_hits += 1
    result = {}
    if jaccards:
        result["test_retest_jaccard"] = round(st.mean(jaccards), 3)
    if band_total:
        result["band_agreement"] = round(band_hits / band_total, 3)
    return result


# -- gold --------------------------------------------------------------------

def action_item_recall(document, gold):
    """Share of the owner's hand-listed action items the notes recovered.

    Matching is by the gold item's `turn_ids`: a gold action item counts as
    recovered when any notes action item cites one of its turns."""
    wanted = gold.get("action_items") or []
    if not wanted:
        return None
    got = [set(item.get("turn_ids") or [])
           for item in (document.get("notes") or {}).get("action_items")
           or []]
    hits = sum(1 for item in wanted
               if any(set(item.get("turn_ids") or []) & cited
                      for cited in got))
    return round(hits / len(wanted), 3)


def reading_precision_recall(readings, gold):
    """Kept readings against owner labels (real / not_real / unknown),
    matched on evidence turns."""
    labels = gold.get("readings") or []
    real = [set(item.get("turn_ids") or []) for item in labels
            if item.get("label") == "real"]
    not_real = [set(item.get("turn_ids") or []) for item in labels
                if item.get("label") == "not_real"]
    if not labels:
        return None
    kept_turns = [set(r.get("turns") or []) for r in readings]
    true_positive = sum(1 for turns in kept_turns
                        if any(turns & g for g in real))
    false_positive = sum(1 for turns in kept_turns
                         if any(turns & g for g in not_real))
    recall = (sum(1 for g in real if any(g & turns for turns in kept_turns))
              / len(real)) if real else None
    precision = (true_positive / (true_positive + false_positive)
                 if (true_positive + false_positive) else None)
    return {"precision": precision, "recall": recall}
