"""Symbolic alignment and supervised selection of alignment parameters."""

from collections import defaultdict
from dataclasses import asdict, dataclass
from itertools import product
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
WINDOWS = (35, 75)
SIMILARITIES = (0.5, 0.7, 0.9)
TOLERANCES = (100, 160, 260)


def model_document(parameters):
    return {"version": 1, "method": "piecewise-onset-alignment", "parameters": asdict(parameters)}


def read_model(document):
    if document is None:
        return DEFAULT
    if (not isinstance(document, dict) or document.get("version") != 1
            or document.get("method") != "piecewise-onset-alignment"):
        raise ValueError("请选择本工具保存的模型 JSON")
    try:
        parameters = Parameters(**document["parameters"])
    except (KeyError, TypeError) as exc:
        raise ValueError("模型参数不完整") from exc
    if (parameters.chord_window_ms not in WINDOWS or parameters.anchor_similarity not in SIMILARITIES
            or parameters.tolerance_ms not in TOLERANCES):
        raise ValueError("模型参数超出支持范围")
    return parameters


def read_notes(rows, label):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 1000:
        raise ValueError(f"{label}须包含 1 至 1000 个音符")
    notes, ids = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f"{label}中的音符须为 JSON 对象")
        note_id, pitch = row.get("id"), row.get("pitch")
        onset, duration = row.get("onset"), row.get("duration", 0.2)
        if (not isinstance(note_id, str) or not note_id.strip() or len(note_id) > 64 or note_id in ids
                or type(pitch) is not int or not 21 <= pitch <= 108
                or type(onset) not in (int, float) or not 0 <= onset <= 3600
                or type(duration) not in (int, float) or not 0 < duration <= 3600):
            raise ValueError(f"{label}含无效音符，检查 ID、音高或时间")
        ids.add(note_id)
        notes.append(Note(note_id, pitch, float(onset), float(duration)))
    return sorted(notes, key=lambda note: (note.onset, note.pitch, note.id))


@dataclass
class Example:
    id: str
    piece_id: str
    reference: list
    performance: list
    truth: set


def read_dataset(data):
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("训练集需使用 version 为 1 的 JSON 格式")
    samples = data.get("examples")
    if not isinstance(samples, list) or not 2 <= len(samples) <= 80:
        raise ValueError("训练集需要 2 至 80 个片段，并且来自至少两首不同的曲目")
    examples, sample_ids = [], set()
    cells = 0
    for item in samples:
        if not isinstance(item, dict):
            raise ValueError("训练集中的每个片段须为 JSON 对象")
        sample_id, piece_id = item.get("id"), item.get("piece_id")
        if (not isinstance(sample_id, str) or not sample_id.strip() or len(sample_id) > 100
                or sample_id in sample_ids or not isinstance(piece_id, str)
                or not piece_id.strip() or len(piece_id) > 100):
            raise ValueError("每个片段都需要唯一 id 和有效的 piece_id")
        sample_ids.add(sample_id)
        reference = read_notes(item.get("reference"), f"{sample_id} 的参考音符")
        performance = read_notes(item.get("performance"), f"{sample_id} 的演奏音符")
        cells += len(reference) * len(performance)
        if cells > 3_000_000:
            raise ValueError("本次对齐规模过大，请缩短片段或分批导入")
        ref_ids = {note.id: note.pitch for note in reference}
        perf_ids = {note.id: note.pitch for note in performance}
        rows = item.get("matches")
        if not isinstance(rows, list) or not rows or len(rows) > min(len(reference), len(performance)):
            raise ValueError(f"{sample_id} 需要完整的逐音匹配标签 matches")
        truth, seen_ref, seen_perf = set(), set(), set()
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError(f"{sample_id} 含无效的匹配标签")
            ref_id, perf_id = row.get("reference_id"), row.get("performance_id")
            if (not isinstance(ref_id, str) or not isinstance(perf_id, str)
                    or ref_id not in ref_ids or perf_id not in perf_ids
                    or ref_ids[ref_id] != perf_ids[perf_id] or ref_id in seen_ref or perf_id in seen_perf):
                raise ValueError(f"{sample_id} 的标签须引用同音高、互不重复的音符 ID")
            truth.add((ref_id, perf_id))
            seen_ref.add(ref_id)
            seen_perf.add(perf_id)
        examples.append(Example(sample_id, piece_id, reference, performance, truth))
    return examples


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


def _metrics(correct, predicted, labels):
    return {"correct": correct, "predicted": predicted, "labels": labels,
            "precision": correct / predicted if predicted else 0,
            "recall": correct / labels if labels else 0,
            "f1": 2 * correct / (predicted + labels) if predicted + labels else 0}


def _measure(prediction, truth):
    pairs = prediction["pairs"]
    return _metrics(len(pairs & truth), len(pairs), len(truth))


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


def train(document):
    examples = read_dataset(document)
    pieces = sorted({example.piece_id for example in examples})
    if len(pieces) < 2:
        raise ValueError("请至少导入两首曲目，训练和验证按 piece_id 分组")
    validation_pieces = set(pieces[::4][:max(1, len(pieces) // 4)])
    training = [example for example in examples if example.piece_id not in validation_pieces]
    validation = [example for example in examples if example.piece_id in validation_pieces]
    cache = {(sample.id, window): _group_pairs(sample.reference, sample.performance, window)
             for sample in examples for window in WINDOWS}

    def run(sample, parameters, fixed=False):
        return _predict(sample.reference, sample.performance, cache[sample.id, parameters.chord_window_ms],
                        parameters, fixed=fixed)

    def aggregate(measurements):
        return _metrics(*(sum(score[field] for score in measurements)
                          for field in ("correct", "predicted", "labels")))

    settings = [DEFAULT, *(Parameters(*values) for values in product(WINDOWS, SIMILARITIES, TOLERANCES)
                          if Parameters(*values) != DEFAULT)]
    trials = [{"parameters": asdict(params),
               **aggregate([_measure(run(sample, params), sample.truth) for sample in training])}
              for params in settings]
    chosen = settings[max(range(len(settings)), key=lambda index: trials[index]["f1"])]

    results = []
    for sample in validation:
        predictions = {"fixed": run(sample, DEFAULT, fixed=True), "default": run(sample, DEFAULT),
                       "adaptive": run(sample, chosen)}
        results.append({"id": sample.id, "piece_id": sample.piece_id,
                        "reference": _notes_json(sample.reference), "performance": _notes_json(sample.performance),
                        "truth": [list(pair) for pair in sorted(sample.truth)],
                        **{key: _render(value) for key, value in predictions.items()},
                        "metrics": {key: _measure(value, sample.truth) for key, value in predictions.items()}})
    return {"model": model_document(chosen), "training_pieces": sorted(set(pieces) - validation_pieces),
            "validation_pieces": sorted(validation_pieces), "training_count": len(training),
            "validation_count": len(validation), "trials": trials,
            "validation": {name: aggregate([row["metrics"][name] for row in results])
                           for name in ("fixed", "default", "adaptive")}, "examples": results}
