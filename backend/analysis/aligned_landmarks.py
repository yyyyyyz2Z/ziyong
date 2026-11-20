"""Extract hand landmarks at the video frame for each aligned note.

Usage:
    .venv\Scripts\python.exe -m backend.analysis.aligned_landmarks \
        --video data\raw\performance.mp4 \
        --aligned-notes outputs\aligned_notes.csv \
        --output outputs\aligned_landmarks.jsonl
"""

from __future__ import annotations

import argparse
import csv
import json
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List

import cv2

from .hand_tracking import hand_positions, tracked_frames


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract landmarks for aligned notes")
    parser.add_argument("--video", required=True)
    parser.add_argument("--aligned-notes", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def read_aligned_notes(path: Path) -> List[Dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as file:
        return list(csv.DictReader(file))


def process(video_path: Path, notes: List[Dict[str, str]], mirrored: bool = False,
            replay_track=None) -> List[Dict[str, Any]]:
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    fps = capture.get(cv2.CAP_PROP_FPS)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    if fps <= 0:
        capture.release()
        raise RuntimeError("Could not determine video FPS")
    # Use time-based attack windows across frame rates. Read adjacent frames so the
    # tracker can follow the hand and score consecutive contact observations.
    before, after = round(fps * .045), round(fps * .085)
    starts = [min(total - 1, int(row["start_frame"])) if total else int(row["start_frame"])
              for row in notes]
    windows = [range(max(0, start - before), min(total or start + after + 1, start + after + 1))
               for start in starts]
    detections = dict.fromkeys(frame for window in windows for frame in window)

    try:
        last_frame = max(detections, default=-1)
        with closing(tracked_frames(capture)) as frames:
            for frame_index, (_, result) in enumerate(frames):
                if replay_track is None and frame_index > last_frame:
                    break
                if replay_track is not None or frame_index in detections:
                    positions = list(hand_positions(result, width, height, mirrored))
                    if frame_index in detections:
                        detections[frame_index] = {hand: points for hand, points in positions
                                                   if hand in ("left", "right")}
                    if replay_track is not None:
                        replay_track.write(json.dumps(positions, separators=(",", ":")) + "\n")
    finally:
        capture.release()

    output: List[Dict[str, Any]] = []
    for row, frame, window in zip(notes, starts, windows):
        sample_frames = list(window)
        by_frame = {str(f): detections[f] or {} for f in sample_frames}
        merged: Dict[str, Any] = {}
        for f in sorted(sample_frames, key=lambda f: abs(f - frame)):
            detected_hands = by_frame[str(f)]
            for hand_name, landmarks in detected_hands.items():
                merged.setdefault(hand_name, landmarks)
        output.append(
            {
                "note_index": int(row["note_index"]),
                "pitch": int(row["pitch"]),
                "start_seconds": float(row["start_seconds"]),
                "start_frame": frame,
                "hands": merged,
                "hands_by_frame": by_frame,
                "sample_frames": sample_frames,
            }
        )
    return output


def main() -> None:
    args = parse_args()
    video_path = Path(args.video)
    notes_path = Path(args.aligned_notes)
    output_path = Path(args.output)
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")
    if not notes_path.exists():
        raise FileNotFoundError(f"Aligned notes not found: {notes_path}")

    rows = process(video_path, read_aligned_notes(notes_path))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")

    detected = sum(1 for row in rows if row["hands"])
    print(f"Aligned notes: {len(rows)}")
    print(f"Notes with detected hands: {detected}")
    print(f"Saved landmarks to: {output_path}")


if __name__ == "__main__":
    main()
