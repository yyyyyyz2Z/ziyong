"""Match each aligned note to the nearest detected fingertip.

Usage:
    .venv\Scripts\python.exe -m backend.analysis.predict_fingering \
        --landmarks outputs\aligned_landmarks.jsonl \
        --mapping outputs\keyboard_mapping.json \
        --output outputs\fingering_predictions.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Tuple


TIP_INDEX_TO_FINGER = {4: 1, 8: 2, 12: 3, 16: 4, 20: 5}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Predict fingers for aligned notes")
    parser.add_argument("--landmarks", required=True)
    parser.add_argument("--mapping", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def distance(a: Dict[str, float], b: Dict[str, float]) -> float:
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"])


def main() -> None:
    args = parse_args()
    mapping = json.loads(Path(args.mapping).read_text(encoding="utf-8"))
    key_by_pitch = {int(row["midi_pitch"]): row for row in mapping["key_centers"]}

    rows: List[Dict[str, Any]] = []
    with Path(args.landmarks).open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                rows.append(json.loads(line))

    output_rows: List[Dict[str, Any]] = []
    for row in rows:
        key = key_by_pitch.get(int(row["pitch"]))
        candidates: List[Tuple[float, str, int]] = []
        if key is not None:
            target = {"x": float(key["x"]), "y": float(key["y"])}
            for hand_name, landmarks in row.get("hands", {}).items():
                for landmark_index, finger in TIP_INDEX_TO_FINGER.items():
                    if landmark_index < len(landmarks):
                        candidates.append(
                            (distance(target, landmarks[landmark_index]), hand_name, finger)
                        )

        candidates.sort(key=lambda item: item[0])
        # MIDI pitch is not used to infer a finger from a raw image coordinate;
        # require a nearby fingertip to avoid plausible-looking false matches.
        if candidates and candidates[0][0] <= 90:
            nearest_distance, hand, finger = candidates[0]
            # This is a geometric confidence, not a calibrated probability.
            confidence = max(0.0, min(1.0, 1.0 - nearest_distance / 150.0))
            status = "matched"
        else:
            nearest_distance, hand, finger, confidence, status = ("", "", "", 0.0, "unmatched")

        output_rows.append(
            {
                "note_index": row["note_index"],
                "pitch": row["pitch"],
                "start_seconds": row["start_seconds"],
                "start_frame": row["start_frame"],
                "hand": hand,
                "finger": finger,
                "distance_pixels": round(nearest_distance, 3) if nearest_distance != "" else "",
                "confidence": round(confidence, 4),
                "status": status,
                "reviewed": "false",
            }
        )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8-sig") as file:
        fields = list(output_rows[0].keys()) if output_rows else []
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(output_rows)

    matched = sum(row["status"] == "matched" for row in output_rows)
    print(f"Notes: {len(output_rows)}")
    print(f"Matched: {matched}")
    print(f"Unmatched: {len(output_rows) - matched}")
    print(f"Saved fingering predictions to: {output_path}")


if __name__ == "__main__":
    main()
