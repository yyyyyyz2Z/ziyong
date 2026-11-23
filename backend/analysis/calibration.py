"""Read calibration frames and project MIDI pitches onto the selected keyboard."""

import math

import cv2
import numpy as np

from .auto_keyboard import detect_keyboard


WHITE_PITCH_CLASSES = (0, 2, 4, 5, 7, 9, 11)
PIANOCV_SOURCES = ("pianocv_auto", "pianocv_crop")


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


def pianocv_mapping(source, corners, keys, width, height, mirrored):
    if source not in PIANOCV_SOURCES or not isinstance(keys, list) or len(keys) != 88:
        raise ValueError("pianoCV 需要完整的 88 键坐标")
    mapping = keyboard_mapping(corners, width, height, 21, 108, mirrored)
    quad = np.asarray(corners, dtype=np.float32)
    transform = cv2.getPerspectiveTransform(quad, np.float32([[0, 0], [52, 0], [52, 1], [0, 1]]))
    centers = []
    projected_x = []

    def polygon(value):
        points = np.asarray(value, dtype=np.float32)
        if (points.ndim != 2 or points.shape[1] != 2 or not 3 <= len(points) <= 32
                or not np.isfinite(points).all() or (points < 0).any()
                or (points[:, 0] >= width).any() or (points[:, 1] >= height).any()
                or cv2.contourArea(points) < 1):
            raise ValueError("pianoCV 琴键轮廓超出画面或形状无效")
        return points

    for pitch, key in enumerate(keys, 21):
        if not isinstance(key, dict) or key.get("midi_pitch") != pitch:
            raise ValueError("pianoCV 琴键编号须从 A0 到 C8 连续排列")
        outline = polygon(key.get("outline"))
        surface = polygon(key.get("surface"))
        moment = cv2.moments(surface)
        center = (moment["m10"] / moment["m00"], moment["m01"] / moment["m00"])
        x, y = cv2.perspectiveTransform(np.float32([[center]]), transform)[0, 0]
        if not (0 <= x <= 52 and -.5 <= y <= 1.1):
            raise ValueError("pianoCV 琴键与键盘范围不符")
        projected_x.append(float(x))
        centers.append(dict(midi_pitch=pitch, x=center[0], y=center[1],
                            outline=outline.tolist(), surface=surface.tolist()))
    direction = -1 if mirrored else 1
    if any((right - left) * direction <= 0 for left, right in zip(projected_x, projected_x[1:])):
        raise ValueError("pianoCV 琴键顺序异常，请核对取景和水平镜像设置")
    return dict(mapping, source=source, key_centers=centers)
