"""Automatically estimate a piano keyboard quadrilateral from a video frame.

This is a first zero-click prototype. It uses bright-region segmentation and
contours, then maps 88 keys between the detected left and right edges. Always
inspect the preview and confidence before using the coordinates for research.

Usage:
    .venv\Scripts\python.exe -m backend.analysis.auto_keyboard \
        --video data\raw\performance.mp4 \
        --output outputs\auto_keyboard.json \
        --preview outputs\auto_keyboard_preview.jpg
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np


Point = Tuple[float, float]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Auto-detect piano keyboard")
    parser.add_argument("--video", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--preview", required=True)
    parser.add_argument("--frame", type=int, default=800)
    return parser.parse_args()


def order_points(points: np.ndarray) -> np.ndarray:
    sums = points.sum(axis=1)
    diffs = np.diff(points, axis=1).reshape(-1)
    return np.array(
        [
            points[np.argmin(sums)],
            points[np.argmin(diffs)],
            points[np.argmax(sums)],
            points[np.argmax(diffs)],
        ],
        dtype=np.float32,
    )


def detect_keyboard(frame: np.ndarray) -> Tuple[Optional[np.ndarray], float]:
    height, width = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    # Piano white keys are bright and mostly low-saturation in this recording.
    mask = cv2.inRange(hsv, np.array([0, 0, 100]), np.array([180, 150, 255]))
    mask[: int(height * 0.12), :] = 0
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (31, 31))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best: Optional[np.ndarray] = None
    best_score = 0.0
    frame_area = float(width * height)
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < frame_area * 0.03:
            continue
        perimeter = cv2.arcLength(contour, True)
        polygon = cv2.approxPolyDP(contour, 0.04 * perimeter, True)
        if len(polygon) != 4:
            rect = cv2.minAreaRect(contour)
            polygon = cv2.boxPoints(rect).reshape(-1, 1, 2).astype(np.int32)
        points = order_points(polygon.reshape(4, 2).astype(np.float32))
        center_y = float(points[:, 1].mean())
        score = (area / frame_area) * (0.5 + 0.5 * center_y / height)
        if score > best_score:
            best, best_score = points, score

    confidence = min(1.0, best_score * 4.0)
    return best, confidence


def key_centers(corners: np.ndarray, count: int = 88) -> List[Dict[str, object]]:
    top_left, top_right, bottom_right, bottom_left = corners
    keys: List[Dict[str, object]] = []
    for index in range(count):
        u = (index + 0.5) / count
        top = top_left * (1 - u) + top_right * u
        bottom = bottom_left * (1 - u) + bottom_right * u
        center = (top + bottom) / 2
        keys.append(
            {
                "midi_pitch": 21 + index,
                "x": round(float(center[0]), 3),
                "y": round(float(center[1]), 3),
            }
        )
    return keys


def main() -> None:
    args = parse_args()
    video_path = Path(args.video)
    output_path = Path(args.output)
    preview_path = Path(args.preview)
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")
    capture.set(cv2.CAP_PROP_POS_FRAMES, args.frame)
    ok, frame = capture.read()
    capture.release()
    if not ok:
        raise RuntimeError(f"Could not read frame {args.frame}")

    corners, confidence = detect_keyboard(frame)
    if corners is None:
        raise RuntimeError("Automatic keyboard detection found no suitable region")

    preview = frame.copy()
    polygon = corners.astype(np.int32).reshape(-1, 1, 2)
    cv2.polylines(preview, [polygon], True, (0, 0, 255), 5)
    for index, point in enumerate(corners):
        cv2.circle(preview, tuple(point.astype(int)), 12, (0, 255, 255), -1)
        cv2.putText(preview, str(index + 1), tuple(point.astype(int)), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 3)
    data = {
        "video": str(video_path),
        "frame_index": args.frame,
        "confidence": round(confidence, 4),
        "corners": corners.round(3).tolist(),
        "key_centers": key_centers(corners),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    preview_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    cv2.imwrite(str(preview_path), preview)
    print(f"Detection confidence: {confidence:.3f}")
    print(f"Saved mapping to: {output_path}")
    print(f"Saved preview to: {preview_path}")


if __name__ == "__main__":
    main()
