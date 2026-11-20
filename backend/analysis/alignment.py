"""Align transcribed note events with frames in the original video.

Usage:
    .venv\Scripts\python.exe -m backend.analysis.alignment \
        --video data\raw\performance.mp4 \
        --notes outputs\transcription\notes.csv \
        --output outputs\aligned_notes.csv
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Dict, List

import cv2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Align notes with video frames")
    parser.add_argument("--video", required=True, help="Original MP4 video")
    parser.add_argument("--notes", required=True, help="Note CSV from transcription")
    parser.add_argument("--output", required=True, help="Output aligned CSV")
    parser.add_argument("--offset", type=float, default=0.0, help="Seconds to add to MIDI times to align with video")
    return parser.parse_args()


def read_video_info(video_path: Path) -> Dict[str, float]:
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")
    try:
        fps = capture.get(cv2.CAP_PROP_FPS)
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    finally:
        capture.release()

    if not fps or fps <= 0:
        raise RuntimeError("Could not determine video FPS")
    return {
        "fps": fps,
        "frame_count": frame_count,
        "width": width,
        "height": height,
        "duration_seconds": frame_count / fps,
    }


def align_notes(notes_path: Path, video_info: Dict[str, float], offset: float = 0.0) -> List[Dict[str, str]]:
    aligned: List[Dict[str, str]] = []
    with notes_path.open("r", newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        for row in reader:
            start = float(row["start_seconds"])
            end = float(row["end_seconds"])
            start_frame = max(0, round((start + offset) * video_info["fps"]))
            end_frame = max(start_frame, round((end + offset) * video_info["fps"]))
            aligned.append(
                {
                    "note_index": str(len(aligned)),
                    "pitch": row["pitch"],
                    "start_seconds": row["start_seconds"],
                    "end_seconds": row["end_seconds"],
                    "amplitude": row.get("amplitude", ""),
                    "pitch_bends": row.get("pitch_bends", ""),
                    "hand": row.get("hand", ""), "finger": row.get("finger", ""),
                    "confidence": row.get("confidence", "0"),
                    "status": row.get("status", "unreviewed"),
                    "reviewed": row.get("reviewed", "false"),
                    "start_frame": str(start_frame),
                    "end_frame": str(end_frame),
                    "frame_time_seconds": f"{start_frame / video_info['fps']:.6f}",
                    "frame_error_seconds": f"{start_frame / video_info['fps'] - start:.6f}",
                }
            )
    return aligned


def write_csv(rows: List[Dict[str, str]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "note_index",
        "pitch",
        "start_seconds",
        "end_seconds",
        "amplitude",
        "pitch_bends",
        "hand", "finger", "confidence", "status", "reviewed",
        "start_frame",
        "end_frame",
        "frame_time_seconds",
        "frame_error_seconds",
    ]
    with output_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    video_path = Path(args.video)
    notes_path = Path(args.notes)
    output_path = Path(args.output)
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")
    if not notes_path.exists():
        raise FileNotFoundError(f"Notes CSV not found: {notes_path}")

    video_info = read_video_info(video_path)
    rows = align_notes(notes_path, video_info, args.offset)
    write_csv(rows, output_path)

    print(f"Video FPS: {video_info['fps']:.3f}")
    print(f"Video size: {int(video_info['width'])}x{int(video_info['height'])}")
    print(f"Video frames: {int(video_info['frame_count'])}")
    print(f"Aligned notes: {len(rows)}")
    print(f"Saved aligned notes to: {output_path}")


if __name__ == "__main__":
    main()
