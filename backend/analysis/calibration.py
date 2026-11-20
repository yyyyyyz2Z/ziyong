"""Read calibration frames and project MIDI pitches onto the selected keyboard."""

import math

import cv2
import numpy as np

from .auto_keyboard import detect_keyboard


WHITE_PITCH_CLASSES = (0, 2, 4, 5, 7, 9, 11)


def read_frame(video, meta, seconds):
    seconds = float(seconds)
    if not math.isfinite(seconds) or not 0 <= seconds < meta["duration"]:
        raise ValueError("校准时间须在视频时长范围内")
    capture = cv2.VideoCapture(str(video))
    try:
        capture.set(cv2.CAP_PROP_POS_FRAMES, int(seconds * meta["fps"]))
        ok, frame = capture.read()
        if not ok:
            raise ValueError("无法读取该时刻画面，请换一个时间点")
        return frame
    finally:
        capture.release()


def suggest_corners(frame):
    corners, _ = detect_keyboard(frame)
    points = corners.tolist() if corners is not None else []
    return points if len({tuple(point) for point in points}) == 4 else []


def keyboard_mapping(corners, width, height, first, last, mirrored):
    if not (21 <= first < last <= 108) or any(pitch % 12 not in WHITE_PITCH_CLASSES for pitch in (first, last)):
        raise ValueError("键盘范围两端必须是白键，MIDI 编号 21–108")
    points = np.asarray(corners, dtype=np.float32)
    if points.shape != (4, 2) or not np.isfinite(points).all() or (points < 0).any():
        raise ValueError("四角坐标超出画面")
    if (points[:, 0] >= width).any() or (points[:, 1] >= height).any():
        raise ValueError("四角坐标超出画面")
    if not cv2.isContourConvex(points.astype(np.int32)) or cv2.contourArea(points) < 5000:
        raise ValueError("请按左上、右上、右下、左下选取完整键床")

    transform = cv2.getPerspectiveTransform(np.array([[0, 0], [1, 0], [1, 1], [0, 1]], np.float32), points)
    whites = [pitch for pitch in range(first, last + 1) if pitch % 12 in WHITE_PITCH_CLASSES]
    positions = {pitch: index + .5 for index, pitch in enumerate(whites)}
    keys = []
    for pitch in range(first, last + 1):
        white = pitch in positions
        position = positions[pitch] if white else (positions[pitch - 1] + positions[pitch + 1]) / 2
        u = position / len(whites)
        if mirrored:
            u = 1 - u
        x, y = cv2.perspectiveTransform(np.array([[[u, .72 if white else .45]]], np.float32), transform)[0, 0]
        keys.append(dict(midi_pitch=pitch, x=float(x), y=float(y)))
    return dict(
        corners=corners, key_centers=keys, key_width_pixels=float(np.linalg.norm(points[1] - points[0]) / len(whites)),
        width=width, height=height, mirrored=mirrored, low_pitch=first, high_pitch=last,
    )
