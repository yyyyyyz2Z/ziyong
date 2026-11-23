"""Apply editable, versioned review decisions to immutable alignment candidates."""

from collections import Counter
from datetime import datetime, timezone


VERDICTS = {"unreviewed", "confirmed", "misaligned", "variant", "unclear"}


def _played(note, offset):
    finger = int(note["finger"]) if note["status"] == "matched" and note["finger"] else None
    return dict(performance_id=str(note["note_index"]), played_note=note["note_name"],
                time=round(float(note["start_seconds"]) + offset, 4), hand=note["hand"] if finger else None,
                finger=finger)


def effective_report(report, predictions, offset):
    if report["status"] != "aligned" or not report.get("edits"):
        return report
    edits = report["edits"]
    played = {str(note["note_index"]): note for note in predictions if note["start_frame"] not in (None, "")}
    resolved = []
    released = set()
    attached = set()
    for original in report["rows"]:
        if not original["score_note_id"]:
            continue
        row = dict(original)
        edit = edits.get(row["id"], {})
        if "performance_id" in edit:
            if original["performance_id"] and original["performance_id"] != edit["performance_id"]:
                released.add(original["performance_id"])
            actual = played.get(edit["performance_id"])
            row.update(_played(actual, offset) if actual else
                       dict(performance_id=None, played_note=None, time=row["expected_time"], hand=None, finger=None))
            row.update(timing_delta_ms=None, status="review", pairing_overridden=True)
        if row["performance_id"]:
            attached.add(row["performance_id"])
        _apply_decision(row, edit)
        resolved.append(row)

    unpaired = {row["performance_id"]: row for row in report["rows"] if not row["score_note_id"]}
    for identifier, old in unpaired.items():
        if identifier not in attached:
            row = dict(old)
            _apply_decision(row, edits.get(row["id"], {}))
            resolved.append(row)
    for identifier in released.difference(attached, unpaired):
        row = dict(_played(played[identifier], offset), id=f"p:{identifier}", score_note_id=None, measure=None,
                   measure_label=None, beat=None, expected_note=None, status="review")
        _apply_decision(row, edits.get(row["id"], {}))
        resolved.append(row)
    resolved.sort(key=lambda row: (row["time"], row["id"]))
    return dict(report, rows=resolved, counts=dict(Counter(row["status"] for row in resolved)),
                review_count=sum("manual_review" in row for row in resolved))


def _apply_decision(row, edit):
    verdict = edit.get("verdict")
    if verdict:
        row["manual_review"] = verdict
    if verdict == "confirmed":
        if not row["score_note_id"]:
            row["status"] = "extra_confirmed"
        elif row["played_note"] is None:
            row["status"] = "missing_confirmed"
        else:
            row["status"] = "matched_pitch" if row["expected_note"] == row["played_note"] else "pitch_confirmed"
    elif verdict:
        row.update(status="review", timing_delta_ms=None)
    if "fingers" in edit:
        row.update(reference_fingers=edit["fingers"], reference_finger_source="manual")
    if row.get("score_note_id"):
        reference = row.get("reference_fingers", [])
        row["fingering_difference"] = bool(row.get("finger") and reference and row["status"] == "matched_pitch"
                                           and row["finger"] not in reference)


def change_review(report, predictions, offset, data):
    if report["status"] != "aligned":
        raise ValueError("请先取得可复核的曲目对齐结果")
    current = effective_report(report, predictions, offset)
    identifier = data.get("row_id")
    row = next((row for row in current["rows"] if row["id"] == identifier), None)
    if row is None:
        raise ValueError("该音符当前不在复核列表里，请重新打开结果")
    edits = dict(report.get("edits", {}))
    edit = dict(edits.get(identifier, {}))
    touched = False
    if "verdict" in data:
        verdict = data["verdict"]
        if not isinstance(verdict, str) or verdict not in VERDICTS:
            raise ValueError("复核标记无效")
        if verdict == "unreviewed":
            edit.pop("verdict", None)
        else:
            edit["verdict"] = verdict
        touched = True
    if "fingers" in data:
        fingers = data["fingers"]
        if not row["score_note_id"]:
            raise ValueError("只有对应谱面音符才能录入参考指法")
        if fingers is None:
            edit.pop("fingers", None)
        elif (not isinstance(fingers, list) or not 1 <= len(fingers) <= 5 or
              any(type(finger) is not int or not 1 <= finger <= 5 for finger in fingers)):
            raise ValueError("参考指法须为 1 至 5 指，可选择多个备选")
        else:
            edit["fingers"] = sorted(set(fingers))
        touched = True
    if data.get("restore_pairing") is True or "performance_id" in data:
        if not row["score_note_id"]:
            raise ValueError("请选择要重新匹配的谱面音符")
        saved_row = next(base for base in report["rows"] if base["id"] == identifier)
        restore = data.get("restore_pairing") is True
        actual = saved_row["performance_id"] if restore else data["performance_id"]
        if actual is not None:
            if not isinstance(actual, str) or not any(str(note["note_index"]) == actual and
                                                       note["start_frame"] not in (None, "") for note in predictions):
                raise ValueError("请选择该次演奏中有效的实际音符")
            if any(other["id"] != identifier and other["score_note_id"] and other["performance_id"] == actual
                   for other in current["rows"]):
                raise ValueError("这个实际音符已对应另一谱音，请先解除原有对应")
        if restore:
            edit.pop("performance_id", None)
            edit.pop("verdict", None)
        else:
            edit.update(performance_id=actual, verdict="confirmed")
        touched = True
    if not touched:
        raise ValueError("请选择要保存的复核内容")
    edit.pop("updated_at", None)
    if edit:
        edits[identifier] = dict(edit, updated_at=datetime.now(timezone.utc).isoformat())
    else:
        edits.pop(identifier, None)
    return dict(report, edits=edits, revision=report.get("revision", 0) + 1)
