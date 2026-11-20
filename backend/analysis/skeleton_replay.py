"""Extract a frame-by-frame hand skeleton and render a replay without MIDI."""

import argparse
import json
from pathlib import Path

import cv2

from .alignment import read_video_info
from .hand_tracking import draw_skeleton, hand_positions, tracked_frames


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--mirrored", action="store_true")
    args = parser.parse_args()
    video, output = args.video, args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    info = read_video_info(video)
    fps, width, height = info["fps"], info["width"], info["height"]
    capture = cv2.VideoCapture(str(video))
    writer = cv2.VideoWriter(str(output / "fingering_replay.mp4"), cv2.VideoWriter_fourcc(*"mp4v"),
                             fps, (width, height))
    frames = frames_with_hands = 0
    try:
        if not capture.isOpened() or not writer.isOpened():
            raise RuntimeError("无法读取原片或创建骨架回放视频")
        with (output / "aligned_landmarks.jsonl").open("w", encoding="utf-8") as stream:
            for index, (frame, result) in enumerate(tracked_frames(capture)):
                hands = [{"hand": hand, "landmarks": points}
                         for hand, points in hand_positions(result, width, height, args.mirrored)]
                for landmarks in result.multi_hand_landmarks or []:
                    draw_skeleton(frame, landmarks)
                writer.write(frame)
                stream.write(json.dumps({"frame": index, "time_seconds": round(index / fps, 6),
                                         "hands": hands}) + "\n")
                frames += 1
                frames_with_hands += bool(hands)
    finally:
        capture.release()
        writer.release()

    if not frames:
        raise RuntimeError("无法读取视频帧")
    summary = {
        "mode": "skeleton_only", "video": str(video.resolve()), "fps": fps,
        "video_duration_seconds": frames / fps, "frames": frames, "sampled_frames": frames,
        "frames_with_hands": frames_with_hands, "notes": None, "status_counts": None,
        "coverage": None, "score": None,
        "score_note": "未提供 MIDI，未进行音符对齐、错音判断或逐音符指法识别。",
    }
    for name in ("session.json", "analysis_summary.json"):
        (output / name).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Skeleton replay complete: {frames} frames")


if __name__ == "__main__":
    main()
