"""Track adjacent video frames and render MediaPipe's finger colors."""

import cv2
import mediapipe as mp
from mediapipe.framework.formats import landmark_pb2


HANDS = mp.solutions.hands
DRAW = mp.solutions.drawing_utils
POINT_STYLE = mp.solutions.drawing_styles.get_default_hand_landmarks_style()
LINE_STYLE = mp.solutions.drawing_styles.get_default_hand_connections_style()


def tracked_frames(capture):
    with HANDS.Hands(static_image_mode=False, max_num_hands=2, model_complexity=1,
                     min_detection_confidence=0.5, min_tracking_confidence=0.5) as tracker:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            yield frame, tracker.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))


def hand_positions(result, width, height, mirrored):
    handedness = result.multi_handedness or []
    for index, landmarks in enumerate(result.multi_hand_landmarks or []):
        hand = "unknown"
        if index < len(handedness):
            hand = handedness[index].classification[0].label.lower()
            if not mirrored:
                hand = {"left": "right", "right": "left"}.get(hand, hand)
        yield hand, [
            {"x": round(point.x * width, 3), "y": round(point.y * height, 3), "z": round(point.z, 6)}
            for point in landmarks.landmark
        ]


def draw_skeleton(frame, landmarks):
    DRAW.draw_landmarks(frame, landmarks, HANDS.HAND_CONNECTIONS, POINT_STYLE, LINE_STYLE)


def draw_tracked_skeletons(frame, positions):
    height, width = frame.shape[:2]
    for _, points in positions:
        landmarks = landmark_pb2.NormalizedLandmarkList()
        for point in points:
            landmarks.landmark.add(x=point["x"] / width, y=point["y"] / height, z=point["z"])
        draw_skeleton(frame, landmarks)
