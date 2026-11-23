"""Symbolic alignment and supervised selection of alignment parameters."""

from dataclasses import asdict, dataclass
from itertools import product

from backend.analysis.symbolic_alignment import (
    DEFAULT, Note, Parameters, _group_pairs, _notes_json, _predict, _render, align_one,
)


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


def _metrics(correct, predicted, labels):
    return {"correct": correct, "predicted": predicted, "labels": labels,
            "precision": correct / predicted if predicted else 0,
            "recall": correct / labels if labels else 0,
            "f1": 2 * correct / (predicted + labels) if predicted + labels else 0}


def _measure(prediction, truth):
    pairs = prediction["pairs"]
    return _metrics(len(pairs & truth), len(pairs), len(truth))


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
