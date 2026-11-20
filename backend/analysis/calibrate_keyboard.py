"""Interactively mark the four corners of the visible piano keyboard.

Click in this order: top-left, top-right, bottom-right, bottom-left.
Press R to reset, S to save, or Q/Esc to quit.

Usage:
    .venv\Scripts\python.exe -m backend.analysis.calibrate_keyboard \
        --video data\raw\performance.mp4 \
        --output outputs\keyboard_calibration.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List, Tuple

import cv2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Calibrate piano keyboard corners")
    parser.add_argument("--video", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--frame", type=int, default=800)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    video_path = Path(args.video)
    output_path = Path(args.output)
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")
    capture.set(cv2.CAP_PROP_POS_FRAMES, args.frame)
    ok, frame = capture.read()
    capture.release()
    if not ok:
        raise RuntimeError(f"Could not read frame {args.frame}")
    if frame.shape[1] < 640 or frame.shape[0] < 360:
        raise RuntimeError("Video resolution is too small for reliable keyboard calibration")

    points: List[Tuple[int, int]] = []
    window = "Keyboard calibration - click 4 corners"

    def redraw() -> None:
        canvas = frame.copy()
        for index, (x, y) in enumerate(points):
            cv2.circle(canvas, (x, y), 9, (0, 0, 255), -1)
            cv2.putText(
                canvas,
                str(index + 1),
                (x + 12, y - 12),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 0, 255),
                2,
                cv2.LINE_AA,
            )
        if len(points) >= 2:
            cv2.polylines(canvas, [__import__("numpy").array(points)], False, (0, 255, 0), 3)
        if len(points) == 4:
            cv2.polylines(
                canvas,
                [__import__("numpy").array(points)],
                True,
                (0, 255, 0),
                3,
            )
        cv2.putText(
            canvas,
            "Click TL, TR, BR, BL | R reset | S save | Q quit",
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        cv2.imshow(window, canvas)

    def on_mouse(event: int, x: int, y: int, _flags: int, _param: object) -> None:
        if event == cv2.EVENT_LBUTTONDOWN and len(points) < 4:
            points.append((x, y))
            redraw()

    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(window, on_mouse)
    redraw()
    try:
        while True:
            key = cv2.waitKey(50) & 0xFF
            if key in (ord("r"), ord("R")):
                points.clear()
                redraw()
            elif key in (ord("s"), ord("S")) and len(points) == 4:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                data = {
                    "video": str(video_path),
                    "frame_index": args.frame,
                    "corners": {
                        "top_left": list(points[0]),
                        "top_right": list(points[1]),
                        "bottom_right": list(points[2]),
                        "bottom_left": list(points[3]),
                    },
                }
                output_path.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                print(f"Saved keyboard calibration to: {output_path}")
                break
            elif key in (ord("q"), 27):
                print("Calibration cancelled")
                break
    finally:
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
