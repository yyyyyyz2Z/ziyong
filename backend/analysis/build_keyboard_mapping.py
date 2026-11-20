"""Build 88-key coordinates from four manually selected keyboard corners.

Usage:
    .venv\Scripts\python.exe -m backend.analysis.build_keyboard_mapping \
        --video data\raw\performance.mp4 \
        --calibration outputs\keyboard_calibration.json \
        --output outputs\keyboard_mapping.json \
        --preview outputs\keyboard_mapping_preview.jpg
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List

import cv2
import numpy as np


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build piano key mapping")
    parser.add_argument("--video", required=True)
    parser.add_argument("--calibration", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--preview", required=True)
    return parser.parse_args()


def load_frame(video_path: Path, frame_index: int) -> np.ndarray:
    capture = cv2.VideoCapture(str(video_path))
    capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
    ok, frame = capture.read()
    capture.release()
    if not ok:
        raise RuntimeError(f"Could not read frame {frame_index}")
    return frame


def main() -> None:
    args = parse_args()
    calibration = json.loads(Path(args.calibration).read_text(encoding="utf-8"))
    corners = np.array(
        [
            calibration["corners"]["top_left"],
            calibration["corners"]["top_right"],
            calibration["corners"]["bottom_right"],
            calibration["corners"]["bottom_left"],
        ],
        dtype=np.float32,
    )
    # Reject collapsed, self-crossing or implausibly small calibration regions.
    if not cv2.isContourConvex(corners.astype(np.int32).reshape(-1, 1, 2)):
        raise ValueError("Calibration corners must form a convex polygon in TL, TR, BR, BL order")
    if cv2.contourArea(corners.astype(np.float32)) < 5000:
        raise ValueError("Calibration region is too small; select the full visible keybed")
    frame = load_frame(Path(args.video), int(calibration["frame_index"]))

    # Project normalized keyboard coordinates to the original camera frame.
    source = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float32)
    homography = cv2.getPerspectiveTransform(source, corners)
    key_centers: List[Dict[str, object]] = []
    preview = frame.copy()
    # The visible keyboard has 52 white-key widths, not 88 equal semitone widths.
    white_classes = {0, 2, 4, 5, 7, 9, 11}
    white_pitches = [pitch for pitch in range(21, 109) if pitch % 12 in white_classes]
    white_positions = {pitch: index + 0.5 for index, pitch in enumerate(white_pitches)}
    for pitch in range(21, 109):
        if pitch in white_positions:
            u = white_positions[pitch] / 52.0
        else:
            lower = pitch - 1
            upper = pitch + 1
            while lower >= 21 and lower not in white_positions: lower -= 1
            while upper <= 108 and upper not in white_positions: upper += 1
            u = ((white_positions[lower] + white_positions[upper]) / 2) / 52.0
        # Put the contact line over the front half of the keybed.
        point = np.array([[[u, 0.68]]], dtype=np.float32)
        projected = cv2.perspectiveTransform(point, homography)[0, 0]
        x, y = float(projected[0]), float(projected[1])
        key_centers.append({"midi_pitch": pitch, "x": round(x, 3), "y": round(y, 3), "u": round(u, 6)})
        cv2.circle(preview, (round(x), round(y)), 2, (0, 0, 255), -1)

    cv2.polylines(preview, [corners.astype(np.int32).reshape(-1, 1, 2)], True, (0, 255, 0), 4)
    for point in corners:
        cv2.circle(preview, tuple(point.astype(int)), 10, (0, 255, 255), -1)

    output = {
        "video": str(args.video),
        "frame_index": int(calibration["frame_index"]),
        "corners": corners.tolist(),
        "key_count": 88,
        "white_key_count": 52,
        "mapping_method": "white-key semitone geometry",
        "key_centers": key_centers,
    }
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    preview_path = Path(args.preview)
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(preview_path), preview)
    print(f"Generated {len(key_centers)} key coordinates")
    print(f"Saved mapping to: {output_path}")
    print(f"Saved preview to: {preview_path}")


if __name__ == "__main__":
    main()
