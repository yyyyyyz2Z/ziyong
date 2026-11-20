"""Draw MediaPipe hand landmarks on a piano performance video.

Usage:
    .venv\Scripts\python.exe -m backend.analysis.video_hand_pose \
        --input data\raw\performance.mp4 \
        --output outputs\hand_pose.mp4
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import mediapipe as mp


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Draw hand skeletons on a video")
    parser.add_argument("--input", required=True, help="Input video path")
    parser.add_argument("--output", required=True, help="Output annotated video path")
    parser.add_argument(
        "--show",
        action="store_true",
        help="Show the annotated video while processing",
    )
    return parser.parse_args()


def process_video(input_path: Path, output_path: Path, show: bool = False) -> int:
    if not input_path.exists():
        raise FileNotFoundError(f"Input video not found: {input_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(input_path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open input video: {input_path}")

    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    frame_count = 0

    # mp4v is broadly supported by OpenCV on Windows.
    writer = cv2.VideoWriter(
        str(output_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )
    if not writer.isOpened():
        capture.release()
        raise RuntimeError(f"Could not create output video: {output_path}")

    mp_hands = mp.solutions.hands
    mp_drawing = mp.solutions.drawing_utils
    mp_styles = mp.solutions.drawing_styles

    try:
        with mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=2,
            model_complexity=1,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        ) as hands:
            while True:
                ok, frame = capture.read()
                if not ok:
                    break

                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                result = hands.process(rgb_frame)

                if result.multi_hand_landmarks:
                    for hand_landmarks in result.multi_hand_landmarks:
                        mp_drawing.draw_landmarks(
                            frame,
                            hand_landmarks,
                            mp_hands.HAND_CONNECTIONS,
                            mp_styles.get_default_hand_landmarks_style(),
                            mp_styles.get_default_hand_connections_style(),
                        )

                frame_count += 1
                cv2.putText(
                    frame,
                    f"Frame: {frame_count}",
                    (20, 35),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 255, 0),
                    2,
                    cv2.LINE_AA,
                )
                writer.write(frame)

                if show:
                    cv2.imshow("Piano Hand Pose", frame)
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
    finally:
        capture.release()
        writer.release()
        cv2.destroyAllWindows()

    return frame_count


def main() -> None:
    args = parse_args()
    count = process_video(Path(args.input), Path(args.output), args.show)
    print(f"Processed {count} frames")
    print(f"Saved annotated video to: {args.output}")


if __name__ == "__main__":
    main()
