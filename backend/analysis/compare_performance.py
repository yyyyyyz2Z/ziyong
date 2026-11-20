"""Compare an observed performance against an optional reference score."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .score_loader import load_score


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare performance and score")
    parser.add_argument("--reference", required=True, help="Reference MIDI or MusicXML")
    parser.add_argument("--performance", required=True, help="Transcribed MIDI")
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument(
        "--piano-only",
        action="store_true",
        help="Use only piano-program tracks from the reference score",
    )
    return parser.parse_args()


def align(reference: List[Dict[str, float]], observed: List[Dict[str, float]]) -> List[Tuple[Optional[dict], Optional[dict], str]]:
    """Find the best matching local segment of a complete reference score.

    This is a Smith-Waterman-style local alignment. It allows a video excerpt
    to start and end in the middle of a full piece without penalising the
    unplayed parts of the reference score.
    """
    n, m = len(reference), len(observed)
    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    back = [["stop"] * (m + 1) for _ in range(n + 1)]
    best_score = 0.0
    best_position = (0, 0)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            pitch_score = 3.0 if reference[i - 1]["pitch"] == observed[j - 1]["pitch"] else -1.5
            timing_penalty = min(1.0, abs(reference[i - 1]["start_seconds"] - observed[j - 1]["start_seconds"]))
            choices = {
                "match": dp[i - 1][j - 1] + pitch_score - timing_penalty * 0.25,
                "delete": dp[i - 1][j] - 1.5,
                "insert": dp[i][j - 1] - 1.5,
                "stop": 0.0,
            }
            best = max(choices, key=choices.get)
            dp[i][j] = max(0.0, choices[best])
            back[i][j] = best
            if dp[i][j] > best_score:
                best_score = dp[i][j]
                best_position = (i, j)

    result: List[Tuple[Optional[dict], Optional[dict], str]] = []
    i, j = best_position
    while i > 0 and j > 0 and dp[i][j] > 0:
        action = back[i][j]
        if action == "match":
            ref, obs = reference[i - 1], observed[j - 1]
            status = "correct" if ref["pitch"] == obs["pitch"] else "wrong_pitch"
            result.append((ref, obs, status))
            i -= 1
            j -= 1
        elif action == "delete":
            result.append((reference[i - 1], None, "missed"))
            i -= 1
        elif action == "insert":
            result.append((None, observed[j - 1], "extra"))
            j -= 1
        else:
            break
    return list(reversed(result))


def comparison(reference, observed):
    aligned = align(reference, observed)
    matched_pairs = [(ref, obs) for ref, obs, _status in aligned if ref is not None and obs is not None]
    alignment_offset = (
        matched_pairs[0][1]["start_seconds"] - matched_pairs[0][0]["start_seconds"]
        if matched_pairs
        else 0.0
    )
    rows = []
    for ref, obs, status in aligned:
        rows.append(
            {
                "status": status,
                "reference_pitch": "" if ref is None else int(ref["pitch"]),
                "observed_pitch": "" if obs is None else int(obs["pitch"]),
                "reference_start": "" if ref is None else round(ref["start_seconds"], 4),
                "observed_start": "" if obs is None else round(obs["start_seconds"], 4),
                "timing_error": "" if ref is None or obs is None else round(obs["start_seconds"] - (ref["start_seconds"] + alignment_offset), 4),
            }
        )
    counts = {status: sum(row["status"] == status for row in rows) for status in ["correct", "wrong_pitch", "missed", "extra"]}
    comparable = counts["correct"] + counts["wrong_pitch"]
    metrics = {
        "reference_notes": len(reference),
        "observed_notes": len(observed),
        "matched_reference_start_seconds": aligned[0][0]["start_seconds"] if aligned and aligned[0][0] else None,
        "matched_reference_end_seconds": aligned[-1][0]["end_seconds"] if aligned and aligned[-1][0] else None,
        "matched_observed_start_seconds": aligned[0][1]["start_seconds"] if aligned and aligned[0][1] else None,
        "matched_observed_end_seconds": aligned[-1][1]["end_seconds"] if aligned and aligned[-1][1] else None,
        "alignment_offset_seconds": round(alignment_offset, 4),
        **counts,
        "pitch_accuracy": round(counts["correct"] / comparable, 4) if comparable else 0.0,
        "match_rate": round(counts["correct"] / len(reference), 4) if reference else 0.0,
        "mean_absolute_timing_error": round(
            sum(abs(float(row["timing_error"])) for row in rows if row["timing_error"] != "")
            / max(1, comparable),
            4,
        ),
    }
    return rows, metrics


def write_comparison(csv_path, rows):
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()) if rows else ["status"])
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    rows, metrics = comparison(load_score(args.reference, piano_only=args.piano_only), load_score(args.performance))
    write_comparison(Path(args.output_csv), rows)
    Path(args.output_json).write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
