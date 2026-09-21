"""Reports: one table per metric by model, a per-call breakdown, ablations.

Reports carry ids and numbers only (PRD section 10 guard rails); the raw
outputs stay under runs/.
"""

import csv
from pathlib import Path

from .metrics import deterministic, groups


def _fmt(value):
    if value is None:
        return "-"
    if isinstance(value, float):
        return "{0:g}".format(value)
    return str(value)


METRIC_COLUMNS = ["cells", "kept_per_call", "proposed",
                  "quote_mismatch_rate", "convergence_violation_rate",
                  "wording_violations", "abstention_rate",
                  "test_retest_jaccard", "band_agreement", "mean_seconds",
                  "tokens_out"]


def build_report(records, out_dir, judge_notes=None):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = deterministic(records)

    lines = ["# Benchmark report", ""]
    statuses = {}
    for record in records:
        statuses[record.get("status")] = \
            statuses.get(record.get("status"), 0) + 1
    lines.append("Cells: " + ", ".join(
        "{0} {1}".format(count, status)
        for status, count in sorted(statuses.items())))
    lines.append("")

    lines.append("| model | mode | variant | " +
                 " | ".join(METRIC_COLUMNS) + " |")
    lines.append("|" + " --- |" * (3 + len(METRIC_COLUMNS)))
    for (model, mode, variant), row in sorted(rows.items()):
        lines.append("| {0} | {1} | {2} | ".format(model, mode, variant) +
                     " | ".join(_fmt(row.get(c)) for c in METRIC_COLUMNS) +
                     " |")
    lines.append("")

    lines.append("## Per call")
    lines.append("")
    lines.append("| call | model | mode | variant | seed | status | kept |")
    lines.append("|" + " --- |" * 7)
    for record in sorted(records, key=lambda r: (r.get("call") or "",
                                                 r.get("cell") or "")):
        lines.append("| {0} | {1} | {2} | {3} | {4} | {5} | {6} |".format(
            record.get("call", "-"), record.get("model", "-"),
            record.get("mode", "-"), record.get("variant", "-"),
            record.get("seed", "-"), record.get("status", "-"),
            record.get("kept", "-")))
    lines.append("")
    if judge_notes:
        lines.append("## Judge")
        lines.append("")
        lines.extend(judge_notes)
        lines.append("")
    lines.append("With fewer than ten calls, read differences as "
                 "directional, not as findings.")

    with open(out_dir / "report.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    with open(out_dir / "results.csv", "w", encoding="utf-8",
              newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["model", "mode", "variant"] + METRIC_COLUMNS)
        for (model, mode, variant), row in sorted(rows.items()):
            writer.writerow([model, mode, variant] +
                            [row.get(c) for c in METRIC_COLUMNS])
    return out_dir / "report.md"
