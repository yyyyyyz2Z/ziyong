"""Link measured scale attempts to practice rules and reviewed sources."""

import json
import math
from bisect import bisect_right
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from statistics import median

import numpy as np

from .fingering_match import transform_points
from .predict_fingering import TIP_INDEX_TO_FINGER


EXERCISE = "T02"
PREPARATION_WINDOW = .35
FINGER_TIPS = {finger: point for point, finger in TIP_INDEX_TO_FINGER.items()}


@lru_cache(maxsize=1)
def graph_index():
    graph = json.loads(Path(__file__).with_name("piano_technique_graph.json").read_text(encoding="utf-8"))
    nodes = {node["id"]: node for node in graph["nodes"]}
    edges = defaultdict(list)
    for edge in graph["edges"]:
        edges[(edge["source"], edge["relation"])].append(edge["target"])
        if edge["relation"] == "SUPPORTS_EVIDENCE":
            edges[(edge["target"], "supported_by")].append(edge["source"])
    return graph["version"], nodes, edges


def supports_exercise(identifier):
    _, nodes, _ = graph_index()
    return isinstance(identifier, str) and nodes.get(identifier, {}).get("analysis") == "single_hand_scale"


@lru_cache(maxsize=None)
def exercise_definition(identifier):
    _, nodes, edges = graph_index()
    task = nodes[identifier]
    score = sorted((nodes[note] for note in edges[identifier, "HAS_NOTE"]), key=lambda n: n["ordinal"])
    transition, = (nodes[node] for node in edges[identifier, "HAS_TRANSITION"])
    step = [note["id"] for note in score].index(transition["from_note"])
    names = [nodes[edges[note["id"], "REFERS_TO_KEY"][0]]["label"] for note in score]
    fingers = [nodes[edges[note["id"], "HAS_REFERENCE_FINGER"][0]]["number"] for note in score]
    hand = {"R": "right", "L": "left"}[task["hand"]]
    return dict(id=identifier, label=task["label"], score=score, names=names, fingers=fingers,
                hand=hand, transition=transition, step=step)


def scale_attempts(predictions, offset, exercise=EXERCISE):
    definition = exercise_definition(exercise)
    score, transition, step = (definition[key] for key in ("score", "transition", "step"))
    pitches = [note["pitch_midi"] for note in score]
    hand = definition["hand"]
    size = len(score)
    times = [float(row["start_seconds"]) for row in predictions]
    index = 0
    while index <= len(predictions) - size:
        rows = predictions[index:index + size]
        if [int(row["pitch"]) for row in rows] != pitches or any(row["start_frame"] is None for row in rows):
            index += 1
            continue
        onsets = times[index:index + size]
        intervals = [b - a for a, b in zip(onsets, onsets[1:])]
        baseline = median(intervals[:step] + intervals[step + 1:])
        # Simultaneous attacks (including chords adjacent to the run) are
        # ambiguous. A long break in the middle can join two unrelated runs.
        previous_clear = index == 0 or onsets[0] - times[index - 1] > .03
        following_clear = index + size == len(times) or times[index + size] - onsets[-1] > .03
        if min(intervals) <= .03 or max(intervals) > max(1.5, baseline * 3) or not (previous_clear and following_clear):
            index += 1
            continue
        attack_rows = rows[step:step + 2]
        observed = [row["finger"] if row["status"] == "matched" and row["hand"] == hand else None
                    for row in attack_rows]
        expected_fingers = transition["expected_fingers"]
        yield {
            "transition_id": transition["id"],
            "score_note_ids": [transition["from_note"], transition["to_note"]],
            "note_names": definition["names"][step:step + 2],
            "note_ids": [str(row["note_index"]) for row in attack_rows],
            "start": round(onsets[step] + offset, 4), "end": round(onsets[step + 1] + offset, 4),
            "interval_ms": round(1000 * intervals[step], 1), "baseline_ms": round(1000 * baseline, 1),
            "ratio": round(intervals[step] / baseline, 3),
            "hand": hand,
            "fingers": observed,
            "expected_fingers": expected_fingers,
            "supported_fingering": observed == expected_fingers,
            "target_pitch": pitches[step + 1],
        }
        index += size


def finger_sample(frame, points, transform, target, finger):
    tip = FINGER_TIPS[finger]
    xy = np.array([[points[index]["x"], points[index]["y"]] for index in range(tip - 2, tip + 1)])
    if not np.isfinite(xy).all():
        return None
    x = float(transform_points(xy[2:], transform)[0, 0])
    a, b = xy[0] - xy[1], xy[2] - xy[1]
    scale = np.linalg.norm(a) * np.linalg.norm(b)
    angle = math.degrees(math.acos(float(np.clip(np.dot(a, b) / scale, -1, 1)))) if scale > 1 else None
    if not math.isfinite(x):
        return None
    return frame, round(abs(target - x), 3), xy[2].tolist(), round(angle, 1) if angle is not None else None


def finger_measurement(samples, first, last, attack, fps):
    frames = last - first + 1
    coverage = len(samples) / frames
    output = {"coverage": round(coverage, 3), "usable_frames": len(samples), "expected_frames": frames}
    if len(samples) < 5 or coverage < .8 or last - samples[-1][0] > 1:
        return dict(output, status="insufficient_landmarks")
    frame, distance, point, angle = samples[-1]
    output.update(status="observed", sample_seconds=round(frame / fps, 4), fingertip_px=point,
                  distance_white_keys=distance, joint_angle_2d_deg=angle)
    # The start is only an exploratory estimate. Require sustained approach in
    # consecutive frames and decline an onset that may precede the window.
    for previous, left, middle, right in zip(samples, samples[1:], samples[2:], samples[3:]):
        if (right[0] - previous[0] == 3 and previous[1] - left[1] < .025
                and left[1] > middle[1] > right[1] and left[1] - right[1] >= .10):
            output.update(preparation_estimate_ms=round(1000 * (attack - left[0] / fps), 1),
                          preparation_start_seconds=round(left[0] / fps, 4))
            break
    return output


def analyze_exercise(predictions, track, transform, regions, fps, offset, exercise=EXERCISE):
    version, _, _ = graph_index()
    definition = exercise_definition(exercise)
    attempts = list(scale_attempts(predictions, offset, exercise))
    windows = []
    for attempt in attempts:
        attempt["motion"] = {"status": "fingering_unconfirmed"}
        if attempt["supported_fingering"]:
            first = max(0, math.ceil((attempt["end"] - PREPARATION_WINDOW) * fps))
            last = math.floor(attempt["end"] * fps + 1e-6)
            if last >= first:
                windows.append((first, last, attempt, []))
    if windows:
        starts = [window[0] for window in windows]
        track.seek(0)
        for frame, line in enumerate(track):
            if frame > windows[-1][1]:
                break
            index = bisect_right(starts, frame) - 1
            if index < 0:
                continue
            # Adjacent runs can overlap in their look-back windows at high speed.
            if frame > windows[index][1]:
                continue
            hands = [points for hand, points in json.loads(line) if hand == definition["hand"] and len(points) == 21]
            if len(hands) != 1:
                continue
            while index >= 0 and frame <= windows[index][1]:
                _, _, attempt, samples = windows[index]
                sample = finger_sample(frame, hands[0], transform, regions[attempt["target_pitch"]].center,
                                       attempt["expected_fingers"][1])
                if sample is not None:
                    samples.append(sample)
                index -= 1
        for first, last, attempt, samples in windows:
            attempt["motion"] = finger_measurement(samples, first, last, attempt["end"], fps)
    return {"task": exercise, "task_label": definition["label"], "graph_version": version, "fps": fps,
            "attempts": attempts, "repeatability": repeatability(attempts), "thresholds_validated": False}


def repeatability(attempts):
    if len(attempts) < 2:
        return None
    ratios = [attempt["ratio"] for attempt in attempts]
    baselines = [attempt["baseline_ms"] for attempt in attempts]
    center = median(ratios)
    return dict(count=len(attempts), median_ratio=round(center, 3),
                ratio_mad=round(median(abs(ratio - center) for ratio in ratios), 3),
                baseline_range_ms=[min(baselines), max(baselines)])


def practice_material(exercise, available):
    _, nodes, edges = graph_index()
    transition = exercise_definition(exercise)["transition"]["id"]
    references = {}

    def add_reference(identifier):
        source = nodes[identifier]
        if not source.get("reviewed"):
            return False
        references[identifier] = dict(id=identifier, title=source.get("title", source["label"]), url=source["url"],
                                      tip=source["finding_zh"], limit=source["limit_zh"])
        return True

    chart_ids = [identifier for identifier in edges[exercise, "USES_REFERENCE"] if add_reference(identifier)]
    rules = []
    for identifier in edges[exercise, "USES_RULE"]:
        rule = nodes[identifier]
        if rule.get("availability") not in available or transition not in edges[identifier, "LOCATED_AT"]:
            continue
        sources = [paper for evidence in edges[identifier, "GROUNDED_IN"]
                   for paper in edges[evidence, "supported_by"]
                   if add_reference(paper)]
        tips = edges[identifier, "SUGGESTS"]
        if identifier == "R03":
            tips = edges[transition, "SUGGESTS"]
        if identifier == "R02":
            sources += chart_ids
        rules.append(dict(id=identifier, label=rule["label"], mode=rule["mode"], logic=rule["logic"],
                          metrics=[dict(id=metric, **{key: nodes[metric][key] for key in
                                                      ("label", "definition", "input", "unit")})
                                   for metric in edges[identifier, "MEASURES"]],
                          advice=[nodes[tip]["advice"] for tip in tips],
                          reference_ids=list(dict.fromkeys(sources))))
    return rules, list(references.values())


def exercise_catalog():
    version, nodes, _ = graph_index()
    exercises = []
    for identifier in nodes:
        if not supports_exercise(identifier):
            continue
        definition = exercise_definition(identifier)
        rules, references = practice_material(identifier, {"timing", "motion", "finger_candidates", "repetition"})
        exercises.append(dict(id=identifier, label=definition["label"], note_names=definition["names"],
                              fingers=definition["fingers"], transition=definition["transition"]["label"],
                              step=definition["step"], rules=rules, references=references))
    return {"version": version, "exercises": exercises}


def segment_evidence(report, start, end, selected):
    # Require both attacks to belong to the clip. When selecting individual
    # notes, require the whole transition to be explicitly selected.
    attempts = [attempt for attempt in report["attempts"]
                if start - .001 <= attempt["start"] and attempt["end"] < end
                and (not selected or set(attempt["note_ids"]).issubset(selected))]
    if not attempts:
        return None
    definition = exercise_definition(report["task"])
    step = definition["step"]
    visible_attempts = []
    for attempt in attempts[:12]:
        item = dict(attempt)
        legacy_motion = item.pop("thumb", None)
        motion = attempt.get("motion", legacy_motion).copy()
        if legacy_motion and "motion" not in attempt and motion["status"] == "observed":
            motion["fingertip_px"] = motion.pop("thumb_tip_px")
            motion["joint_angle_2d_deg"] = motion.pop("thumb_ip_angle_2d_deg")
        if motion.get("sample_seconds", start) < start - .001:
            motion = {"status": "outside_selection"}
        elif motion.get("preparation_start_seconds", start) < start:
            motion.pop("preparation_start_seconds")
            motion.pop("preparation_estimate_ms")
            motion["preparation_before_selection"] = True
        item.setdefault("note_names", definition["names"][step:step + 2])
        item.setdefault("hand", definition["hand"])
        visible_attempts.append(dict(item, motion=motion))
    variation = repeatability(attempts)
    available = {"timing"}
    if any(attempt["motion"]["status"] == "observed" for attempt in visible_attempts):
        available.add("motion")
    if any(any(finger is not None for finger in attempt["fingers"]) for attempt in visible_attempts):
        available.add("finger_candidates")
    if variation:
        available.add("repetition")
    rules, references = practice_material(report["task"], available)
    version, _, _ = graph_index()
    return dict(task=definition["label"], graph_version=version, measurement_graph_version=report["graph_version"],
                attempts=visible_attempts, total_attempts=len(attempts), rules=rules, fps=report.get("fps"),
                repeatability=variation, thresholds_validated=False), references
