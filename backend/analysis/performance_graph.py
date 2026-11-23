"""Connect observations to score positions and actionable practice rules."""

from collections import Counter
from statistics import median
from .score_review import score_guidance


RULES = [
    dict(id="steady", label="节奏与连续性", advice="选定四到八小节，用节拍器慢练，保持相同时值的起音间隔。"),
    dict(id="fingering", label="指法衔接", advice="在换指前预先安排下一指，分手连接前后两个音组，再合手复练。"),
    dict(id="hands", label="双手配合", advice="先明确两手在同一拍的落点，按拍合手，逐步连成长句。"),
]


def summarize(events):
    measured = [row for row in events if row["timing_source"] == "audio"]
    deltas = [abs(row["timing_delta_ms"]) for row in measured if row["timing_delta_ms"] is not None]
    fingers = Counter(str(row["finger"]) for row in events if row.get("finger"))
    hands = Counter(row["hand"] for row in events if row.get("hand"))
    highlights = sorted(measured, key=lambda row: abs(row["timing_delta_ms"] or 0), reverse=True)[:8]
    return dict(notes=len(events), audio_timed_notes=len(measured), hand_counts=dict(hands),
                finger_counts=dict(fingers), median_onset_deviation_ms=round(median(deltas), 1) if deltas else None,
                reference_fingering_differences=sum(row.get("fingering_difference", False) for row in events),
                highlights=[{key: row[key] for key in ("id", "name", "time", "measure_label", "timing_delta_ms")}
                            for row in highlights])


def build_graph(passage, predictions, timings, mapping, duration):
    if len(predictions) != len(timings):
        raise ValueError("音符时间与指法结果数量不一致，请重新分析")
    score = {row["id"]: row for row in passage["notes"]}
    nodes = [dict(id="performance", type="performance", duration=duration, title=passage["title"])]
    nodes += [dict(id=f'key:{key["midi_pitch"]}', type="key", pitch=key["midi_pitch"],
                   outline=key.get("outline"), center=[key["x"], key["y"]]) for key in mapping["key_centers"]]
    nodes += [dict(rule, type="practice_rule") for rule in RULES]
    edges, events, rows = [], [], []
    for prediction, timing in zip(predictions, timings):
        reference = score[timing["reference_id"]]
        finger = int(prediction["finger"]) if prediction["finger"] else None
        identifier = str(prediction["note_index"])
        fingers = reference.get("reference_fingers", [])
        difference = bool(finger and fingers and finger not in fingers)
        event = dict(id=identifier, reference_id=reference["id"], name=reference["name"], pitch=reference["pitch"],
                     time=timing["start"], end=timing["end"], measure_label=reference.get("measure_label"),
                     hand=prediction["hand"], finger=finger, reference_fingers=fingers,
                     timing_source=timing["timing_source"], timing_delta_ms=timing["timing_delta_ms"],
                     fingering_difference=difference, contact_support=float(prediction["confidence"]))
        events.append(event)
        nodes.append(dict(event, id=f"event:{identifier}", type="note_event"))
        nodes.append(dict(reference, id=f'score:{reference["id"]}', type="score_note"))
        nodes.append(dict(id=f"hand_observation:{identifier}", type="hand_observation",
                          source="MediaPipe Hands", artifact="aligned_landmarks.jsonl", note_index=identifier,
                          frame=prediction.get("start_frame"), geometric_support=float(prediction["confidence"])))
        edges.extend([dict(source="performance", relation="HAS_EVENT", target=f"event:{identifier}"),
                      dict(source=f"event:{identifier}", relation="PLAYS", target=f'score:{reference["id"]}'),
                      dict(source=f"event:{identifier}", relation="ON_KEY", target=f'key:{reference["pitch"]}')])
        edges.append(dict(source=f"event:{identifier}", relation="OBSERVED_IN", target=f"hand_observation:{identifier}"))
        if finger:
            finger_id = f'finger:{prediction["hand"]}:{finger}'
            edges.append(dict(source=f"event:{identifier}", relation="USES_FINGER", target=finger_id))
        rule = "fingering" if difference else "steady"
        edges.append(dict(source=f"event:{identifier}", relation="PRACTICE_WITH", target=rule))
        rows.append(dict(id=reference["id"], score_note_id=reference["id"], performance_id=identifier,
                         measure=reference.get("measure"), measure_label=reference.get("measure_label"),
                         beat=reference.get("beat"), score_beat=reference.get("score_beat"),
                         expected_note=reference["name"], played_note=reference["name"], time=event["time"],
                         expected_time=timing["expected_time"], timing_delta_ms=timing["timing_delta_ms"],
                         timing_source=timing["timing_source"], status="score_linked",
                         hand=event["hand"], finger=finger, reference_fingers=fingers, fingering_difference=difference))
    for hand in ("left", "right"):
        nodes += [dict(id=f"finger:{hand}:{finger}", type="finger", hand=hand, number=finger) for finger in range(1, 6)]
    graph = dict(version=1, assumption="same_piece_complete", title=passage["title"], nodes=nodes, edges=edges,
                 events=events, rules=RULES, summary=summarize(events))
    report = dict(title=passage["title"], status="aligned", source="performance", rows=rows,
                  counts={"score_linked": len(rows)}, measures=passage.get("measures", []),
                  ornament_measures=passage.get("ornament_measures", []), revision=0)
    rules, references = score_guidance(report)
    graph["references"] = references
    graph["reviewed_rules"] = rules
    nodes.extend(dict(rule, type="reviewed_rule") for rule in rules)
    nodes.extend(dict(reference, type="source") for reference in references)
    for rule in rules:
        edges.extend(dict(source=rule["id"], relation="GROUNDED_IN", target=identifier)
                     for identifier in rule["reference_ids"])
        edges.append(dict(source="performance", relation="GUIDED_BY", target=rule["id"]))
    return graph, report


def graph_segment(graph, start, end, selected):
    events = [event for event in graph["events"] if start - .001 <= event["time"] < end
              and (not selected or event["id"] in selected)]
    # Aggregate every event and sample across the complete selection for the model.
    indices = sorted({round(index * (len(events) - 1) / 31) for index in range(32)}) if events else []
    sample = [events[index] for index in indices]
    return dict(title=graph["title"], assumption=graph["assumption"], summary=summarize(events),
                events=sample, rules=graph["rules"], reviewed_rules=graph.get("reviewed_rules", []))
