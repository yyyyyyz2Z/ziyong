"""Shared onset-group alignment for training and score analysis."""

from collections import defaultdict
from dataclasses import dataclass
from typing import NamedTuple


class Note(NamedTuple):
    id: str
    pitch: int
    onset: float
    duration: float


@dataclass(frozen=True)
class Parameters:
    chord_window_ms: int = 35
    anchor_similarity: float = 0.7
    tolerance_ms: int = 160


DEFAULT = Parameters()


def _monotone_pairs(left, right, weight):
    """Find an order-preserving, one-to-one pairing with optional gaps."""
    width = len(right) + 1
    previous = [0.0] * width
    back = [bytearray(width) for _ in range(len(left) + 1)]
    for i, a in enumerate(left, 1):
        current = [0.0] * width
        actions = back[i]
        for j, b in enumerate(right, 1):
            score, action = previous[j], 1
            if current[j - 1] > score:
                score, action = current[j - 1], 2
            merit = weight(a, b)
            if merit > 0 and previous[j - 1] + merit >= score:
                score, action = previous[j - 1] + merit, 3
            current[j] = score
            actions[j] = action
        previous = current
    i, j = len(left), len(right)
    result = []
    while i and j:
        action = back[i][j]
        if action == 3:
            result.append((left[i - 1], right[j - 1]))
        i -= action != 2
        j -= action != 1
    return list(reversed(result))


def _group(notes, window):
    groups = []
    for note in notes:
        if not groups or note.onset - groups[-1][0] > window:
            groups.append((note.onset, set()))
        groups[-1][1].add(note.pitch)
    return groups


def _similarity(left, right):
    return len(left[1] & right[1]) / len(left[1] | right[1])


def _group_pairs(reference, performance, window_ms):
    return _monotone_pairs(_group(reference, 0.024), _group(performance, window_ms / 1000),
                           lambda left, right: 3 * _similarity(left, right) - 1.25)


def _anchors(group_pairs, threshold):
    candidates = [(left[0], right[0]) for left, right in group_pairs if _similarity(left, right) >= threshold]
    if not candidates:
        return []
    kept = [candidates[0]]
    for index, point in enumerate(candidates[1:], 1):
        score_gap, played_gap = (point[n] - kept[-1][n] for n in (0, 1))
        far_enough = score_gap >= 0.55 or (index == len(candidates) - 1 and score_gap > 0)
        if far_enough and 0.35 <= played_gap / score_gap <= 3:
            kept.append(point)
    return kept


def _project(reference, anchors, offset):
    if len(anchors) < 2:
        return {note.id: note.onset + offset for note in reference}
    projected = {}
    index = 0
    for note in reference:
        while index < len(anchors) - 2 and note.onset > anchors[index + 1][0]:
            index += 1
        left, right = anchors[index:index + 2]
        if note.onset < left[0]:
            onset = note.onset + left[1] - left[0]
        elif note.onset > right[0]:
            onset = note.onset + right[1] - right[0]
        else:
            onset = left[1] + (note.onset - left[0]) * (right[1] - left[1]) / (right[0] - left[0])
        projected[note.id] = onset
    return projected


def _predict(reference, performance, group_pairs, parameters, fixed=False):
    anchors = _anchors(group_pairs, DEFAULT.anchor_similarity if fixed else parameters.anchor_similarity)
    offset = anchors[0][1] - anchors[0][0] if anchors else performance[0].onset - reference[0].onset
    projected = _project(reference, [] if fixed else anchors, offset)
    by_pitch = defaultdict(list)
    for note in performance:
        by_pitch[note.pitch].append(note)
    reference_by_pitch = defaultdict(list)
    for note in reference:
        reference_by_pitch[note.pitch].append(note)
    tolerance = parameters.tolerance_ms / 1000

    def reward(left, right):
        distance = abs(projected[left.id] - right.onset)
        return 2 - distance / tolerance if distance <= tolerance else 0

    pairs = {
        (left.id, right.id)
        for pitch, notes in reference_by_pitch.items()
        for left, right in _monotone_pairs(notes, by_pitch[pitch], reward)
    }
    return {"pairs": pairs, "anchors": anchors[:1] if fixed else anchors, "projected": projected}


def predict_alignment(reference, performance, parameters=DEFAULT):
    groups = _group_pairs(reference, performance, parameters.chord_window_ms)
    return _predict(reference, performance, groups, parameters)


def _render(prediction):
    return {**prediction, "pairs": [list(pair) for pair in sorted(prediction["pairs"])]}


def _notes_json(notes):
    return [note._asdict() for note in notes]


def align_one(reference, performance, parameters):
    default_pairs = _group_pairs(reference, performance, DEFAULT.chord_window_ms)
    adaptive_pairs = (default_pairs if parameters.chord_window_ms == DEFAULT.chord_window_ms
                      else _group_pairs(reference, performance, parameters.chord_window_ms))
    return {"reference": _notes_json(reference), "performance": _notes_json(performance),
            "fixed": _render(_predict(reference, performance, default_pairs, DEFAULT, fixed=True)),
            "adaptive": _render(_predict(reference, performance, adaptive_pairs, parameters))}
