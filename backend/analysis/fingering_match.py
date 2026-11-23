"""Score finger contact in rectified keyboard coordinates and resolve chords."""

from dataclasses import dataclass

import cv2
import numpy as np
from scipy.optimize import linear_sum_assignment

from .calibration import WHITE_PITCH_CLASSES
from .predict_fingering import TIP_INDEX_TO_FINGER


BLACK_HALF_WIDTH = .29
BLACK_DEPTH = .60
MIN_CANDIDATE_SCORE = .27
MIN_MATCH_SCORE = .44
MIN_SCORE_MARGIN = .10
FINGERS = [(hand, finger) for hand in ("left", "right") for finger in TIP_INDEX_TO_FINGER.values()]


@dataclass(frozen=True)
class KeyRegion:
    center: float
    bands: tuple
    outline: np.ndarray
    surface: np.ndarray = None
    obstructions: tuple = ()


CONTACT_SCALE = np.float32([.24, .15])


def transform_points(points, matrix):
    return cv2.perspectiveTransform(np.asarray(points, dtype=np.float32).reshape(-1, 1, 2),
                                    matrix).reshape(-1, 2)


def keyboard_regions(mapping, keys):
    """Use white-key widths across the keyboard and unit depth along a key."""
    corners = np.asarray(mapping["corners"], dtype=np.float32)
    white_keys = {pitch for pitch in keys if pitch % 12 in WHITE_PITCH_CLASSES}
    width = len(white_keys)
    keyboard = np.float32([[0, 0], [width, 0], [width, 1], [0, 1]])
    to_keyboard = cv2.getPerspectiveTransform(corners, keyboard)
    to_image = cv2.getPerspectiveTransform(keyboard, corners)
    centers = transform_points([(key["x"], key["y"]) for key in keys.values()], to_keyboard)
    keys_by_x = sorted((float(center[0]), pitch) for pitch, center in zip(keys, centers))
    regions = {}
    for i, (x, pitch) in enumerate(keys_by_x):
        key = keys[pitch]
        if "surface" in key:
            # Scale the two axes separately so the existing contact tolerances
            # are preserved when using the detected key's visible top face.
            surface = transform_points(key["surface"], to_keyboard) / CONTACT_SCALE
            # pianoCV's white faces are full rectangles. The black silhouettes
            # cover the part of the white surface hidden behind raised keys.
            obstructions = tuple(transform_points(keys[neighbor]["outline"], to_keyboard) / CONTACT_SCALE
                                 for neighbor in (pitch - 1, pitch + 1)
                                 if pitch in white_keys and neighbor in keys and neighbor not in white_keys)
            regions[pitch] = KeyRegion(x, (), np.rint(key["outline"]).astype(np.int32), surface, obstructions)
            continue
        if pitch in white_keys:
            left, right = x - .5, x + .5
            rear_left = left + BLACK_HALF_WIDTH if i > 0 and keys_by_x[i - 1][1] not in white_keys else left
            rear_right = right - BLACK_HALF_WIDTH if i + 1 < len(keys_by_x) and keys_by_x[i + 1][1] not in white_keys else right
            bands = ((rear_left, rear_right, 0, BLACK_DEPTH), (left, right, BLACK_DEPTH, 1))
            outline = [(rear_left, 0), (rear_right, 0), (rear_right, BLACK_DEPTH),
                       (right, BLACK_DEPTH), (right, 1), (left, 1), (left, BLACK_DEPTH),
                       (rear_left, BLACK_DEPTH)]
        else:
            left, right = x - BLACK_HALF_WIDTH, x + BLACK_HALF_WIDTH
            bands = ((left, right, 0, BLACK_DEPTH),)
            outline = [(left, 0), (right, 0), (right, BLACK_DEPTH), (left, BLACK_DEPTH)]
        regions[pitch] = KeyRegion(x, bands, np.rint(transform_points(outline, to_image)).astype(np.int32))
    return to_keyboard, regions


def fingertip_scores(row, region, key, to_keyboard):
    points, identities, weights = [], [], []
    center = row["start_frame"]
    window = row["sample_frames"]
    span = max(1, center - window[0], window[-1] - center)
    frame_weights = {frame: 1 - .5 * abs(frame - center) / span for frame in window}
    for frame, hands in row["hands_by_frame"].items():
        for hand, landmarks in hands.items():
            for index, finger in TIP_INDEX_TO_FINGER.items():
                point = landmarks[index]
                points.append((point["x"], point["y"]))
                identities.append((hand, finger))
                weights.append(frame_weights[int(frame)])
    if not points:
        return {}

    x, y = transform_points(points, to_keyboard).T
    if region.surface is not None:
        scaled = np.column_stack((x, y)) / CONTACT_SCALE
        error = np.array([max(0.0, -cv2.pointPolygonTest(region.surface, tuple(map(float, point)), True)) ** 2
                          for point in scaled])
        for obstruction in region.obstructions:
            hidden = [cv2.pointPolygonTest(obstruction, tuple(map(float, point)), False) > 0 for point in scaled]
            error[hidden] = np.inf
    else:
        errors = []
        for left, right, back, front in region.bands:
            across = np.maximum(0, np.maximum(left - x, x - right)) / .24
            along = np.maximum(0, np.maximum(back - y, y - front)) / .15
            errors.append(across ** 2 + along ** 2)
        error = np.min(errors, axis=0)
    # The longitudinal position within a key can vary freely. Prefer the center
    # across its width only as a tie-breaker for fingertips near adjacent keys.
    quality = np.exp(-error) * (1 - .18 * np.minimum(abs(x - region.center) / .5, 1))
    pixel_distances = np.linalg.norm(np.asarray(points) - (key["x"], key["y"]), axis=1)
    total_weight = sum(frame_weights.values())
    stats = {}
    for finger in dict.fromkeys(identities):
        indices = [i for i, identity in enumerate(identities) if identity == finger]
        score = sum(float(quality[i]) * weights[i] for i in indices) / total_weight
        support = sum(quality[i] >= .50 for i in indices)
        distance = float(np.median(pixel_distances[indices]))
        stats[finger] = (score, support, distance)
    return stats


def group_attacks(landmarks):
    group = []
    first_attack = 0
    for index, row in enumerate(landmarks):
        if row["start_frame"] is None:
            continue
        attack = row["start_seconds"]
        if group and attack - first_attack > .030:
            yield group
            group = []
        if not group:
            first_attack = attack
        group.append(index)
    if group:
        yield group


def assign_fingers(landmarks, keys, regions, to_keyboard):
    predictions = [("unmatched", "outside_video", None, 0, None)] * len(landmarks)
    for group in group_attacks(landmarks):
        # Dummy columns let weak notes go unmatched instead of forcing a finger.
        scores = np.zeros((len(group), len(FINGERS) + len(group)))
        stats = []
        for row_index, note_index in enumerate(group):
            row = landmarks[note_index]
            pitch = row["pitch"]
            options = fingertip_scores(row, regions[pitch], keys[pitch], to_keyboard)
            stats.append(options)
            for column, finger in enumerate(FINGERS):
                if finger in options:
                    score, support, _ = options[finger]
                    if score >= MIN_MATCH_SCORE and support >= 2:
                        scores[row_index, column] = score
        rows, columns = linear_sum_assignment(scores, maximize=True)
        total = scores[rows, columns].sum()
        for row_index, column in zip(rows, columns):
            note_index = group[row_index]
            options = stats[row_index]
            if not options:
                predictions[note_index] = ("unmatched", "no_hand", None, 0, None)
                continue
            best = max(options, key=lambda finger: options[finger][0])
            score, support, distance = options[best]
            if score < MIN_CANDIDATE_SCORE:
                predictions[note_index] = ("unmatched", "outside_key", best, 0, distance)
            elif scores[row_index, column] == 0:
                if scores[row_index].any():
                    reason = "chord_conflict"
                else:
                    reason = "insufficient_frames" if support < 2 else "weak_contact"
                predictions[note_index] = ("uncertain", reason, best, score, distance)
            else:
                finger = FINGERS[column]
                score, _, distance = options[finger]
                scores[row_index, column] = 0
                other_rows, other_columns = linear_sum_assignment(scores, maximize=True)
                margin = total - scores[other_rows, other_columns].sum()
                scores[row_index, column] = score
                status, reason = ("matched", "") if margin >= MIN_SCORE_MARGIN else ("uncertain", "ambiguous_fingers")
                predictions[note_index] = (status, reason, finger, score, distance)
    return predictions
