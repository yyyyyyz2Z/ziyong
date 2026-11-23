"""Map a selected MusicXML passage to MIDI attacks and video evidence."""

from bisect import bisect_right
from collections import Counter
from math import isfinite
from pathlib import Path
from statistics import median
from zipfile import BadZipFile, ZipFile

import pretty_midi

from .score_excerpt import read_musicxml, score_measures
from .symbolic_alignment import DEFAULT, Note, predict_alignment
from .technique_graph import graph_index


MAX_PASSAGE_NOTES = 1000
MAX_SCORE_NOTES = 20000


def score_document(path):
    from music21 import articulations, chord, stream

    if Path(path).suffix == ".mxl":
        try:
            with ZipFile(path) as archive:
                if len(archive.infolist()) > 200 or sum(item.file_size for item in archive.infolist()) > 24 * 1024 * 1024:
                    raise ValueError("压缩乐谱解压后内容过大")
        except BadZipFile as error:
            raise ValueError("无法读取 MXL 乐谱") from error
    score = read_musicxml(path)
    measures = score_measures(score)
    end_beat = float(score.highestTime)
    tempo = [(float(first), float(last), float(mark.getQuarterBPM() or 120))
             for first, last, mark in score.metronomeMarkBoundaries()]
    time_starts = [first for first, _, _ in tempo]
    starts = []
    seconds = 0.0
    for first, last, bpm in tempo:
        starts.append(seconds)
        seconds += (last - first) * 60 / bpm

    def time(beat):
        index = max(0, bisect_right(time_starts, beat) - 1)
        first, _, bpm = tempo[index]
        return starts[index] + (beat - first) * 60 / bpm

    for measure in measures:
        measure["seconds"] = time(measure["beat"])

    notes = []
    ornament_measures = set()
    for part_index, part in enumerate(score.parts, 1):
        for position, measure in enumerate(part.getElementsByClass(stream.Measure), 1):
            measure_info = measures[position - 1]
            for event in measure.recurse().notes:
                if event.duration.isGrace or event.expressions:
                    ornament_measures.add(position)
                if event.duration.isGrace:
                    continue
                beat_in_measure = float(event.getOffsetInHierarchy(measure))
                beat = measure_info["beat"] + beat_in_measure
                displayed_beat = float(event.beat)
                if not isfinite(displayed_beat):
                    displayed_beat = beat_in_measure + 1
                voice = event.getContextByClass(stream.Voice)
                tones = event.notes if isinstance(event, chord.Chord) else (event,)
                for tone in tones:
                    if not getattr(tone, "pitch", None) or tone.tie and tone.tie.type in ("continue", "stop"):
                        continue
                    duration = float(event.quarterLength)
                    pitch = int(tone.pitch.midi)
                    if not 21 <= pitch <= 108 or duration <= 0:
                        continue
                    fingers = sorted({int(a.fingerNumber) for a in tone.articulations
                                      if isinstance(a, articulations.Fingering)
                                      and not getattr(a, "substitution", False)
                                      and str(a.fingerNumber) in ("1", "2", "3", "4", "5")})
                    notes.append(dict(pitch=pitch, name=pretty_midi.note_number_to_name(pitch),
                                      measure=position, measure_label=measure_info["label"], beat=displayed_beat,
                                      score_beat=beat, onset=time(beat), duration=time(beat + duration) - time(beat),
                                      part=part_index, voice=str(voice.id) if voice is not None else None,
                                      reference_fingers=fingers))
                    if len(notes) > MAX_SCORE_NOTES:
                        raise ValueError("乐谱音符过多，请拆分乐章后再上传")
    if not notes:
        raise ValueError("乐谱没有可分析的钢琴起音")
    notes.sort(key=lambda row: (row["score_beat"], row["pitch"], row["part"], row["voice"] or ""))
    for index, row in enumerate(notes, 1):
        row["id"] = f"r{index:05}"
    metadata = score.metadata
    title = (metadata.movementName or metadata.title) if metadata else None
    if title == Path(path).name:
        title = None
    return dict(title=str(title or "")[:240], measures=measures, notes=notes,
                ornament_measures=sorted(ornament_measures), end_seconds=time(end_beat))


def select_passage(document, first, last):
    measures = document["measures"]
    if not 1 <= first <= last <= len(measures):
        raise ValueError(f"选段须满足 1 ≤ 起始小节 ≤ 结束小节 ≤ {len(measures)}")
    origin = measures[first - 1]["seconds"]
    notes = [dict(row, onset=row["onset"] - origin) for row in document["notes"] if first <= row["measure"] <= last]
    if not 1 <= len(notes) <= MAX_PASSAGE_NOTES:
        raise ValueError(f"请选择包含 1 至 {MAX_PASSAGE_NOTES} 个起音的小节范围")
    return dict(title=document["title"] or "未命名乐谱", first=first, last=last, measures=measures[first - 1:last],
                ornament_measures=[position for position in document["ornament_measures"] if first <= position <= last],
                notes=notes)


def analyze_passage(passage, predictions, offset):
    references = passage["notes"]
    played = [row for row in predictions if row["start_frame"] is not None]
    result = dict(title=passage["title"], first=passage["first"], last=passage["last"], measures=[],
                  status="insufficient", counts={}, rows=[], reference_notes=len(references), played_notes=len(played),
                  reference_coverage=0, played_coverage=0, anchors=[], ornament_measures=passage["ornament_measures"])
    if not played:
        return result
    if len(played) > MAX_PASSAGE_NOTES:
        return dict(result, status="too_long")

    reference = [Note(row["id"], row["pitch"], row["onset"], row["duration"]) for row in references]
    performance = [Note(str(row["note_index"]), int(row["pitch"]), float(row["start_seconds"]) + offset,
                        float(row["end_seconds"]) - float(row["start_seconds"])) for row in played]
    prediction = predict_alignment(reference, performance)
    anchors, pairs = prediction["anchors"], dict(prediction["pairs"])
    reference_coverage, played_coverage = len(pairs) / len(reference), len(pairs) / len(performance)
    result.update(reference_coverage=round(reference_coverage, 3), played_coverage=round(played_coverage, 3),
                  anchors=[dict(score_seconds=round(a, 4), video_seconds=round(b, 4)) for a, b in anchors])
    if (len(anchors) < 3 or min(reference_coverage, played_coverage) < .55
            or anchors[-1][0] - anchors[0][0] < .35 * (reference[-1].onset - reference[0].onset)
            or anchors[-1][1] - anchors[0][1] < .35 * (performance[-1].onset - performance[0].onset)):
        return result

    by_id = {str(row["note_index"]): row for row in played}
    performed = {note.id: note for note in performance}
    mapped = prediction["projected"]
    used = set(pairs.values())
    extra_notes = [note for note in performance if note.id not in used]
    missing = [row for row in references if row["id"] not in pairs]
    placed_extras = {}
    simultaneous = Counter((row["score_beat"], row["pitch"]) for row in references)

    def in_span(row, time):
        return (anchors[0][0] <= row["onset"] <= anchors[-1][0]
                and anchors[0][1] <= time <= anchors[-1][1])

    def bounded(row, time):
        return (in_span(row, time)
                and simultaneous[row["score_beat"], row["pitch"]] == 1
                and row["measure"] not in passage["ornament_measures"])

    # Only propose a replacement for a unique nearby unmatched reference
    # and played attack. Crowded chords and ornaments stay under review.
    nearby = {row["id"]: [note for note in extra_notes if note.pitch != row["pitch"]
                          and abs(mapped[row["id"]] - note.onset) <= .065 and bounded(row, note.onset)]
              for row in missing}
    claims = Counter(note.id for group in nearby.values() for note in group)
    for identifier, group in nearby.items():
        if len(group) == 1 and claims[group[0].id] == 1:
            placed_extras[identifier] = group[0].id
    assigned_extras = set(placed_extras.values())

    rows = []
    for row in references:
        expected_time = mapped[row["id"]]
        played_id = pairs.get(row["id"]) or placed_extras.get(row["id"])
        actual = by_id.get(played_id)
        actual_time = performed[played_id].onset if actual else None
        status = ("matched_pitch" if row["id"] in pairs else "pitch_candidate" if actual
                  else "missing_candidate" if bounded(row, expected_time) else "review")
        finger = int(actual["finger"]) if actual and actual["status"] == "matched" and actual["finger"] else None
        reference_fingers = row["reference_fingers"]
        timing_delta = (round(1000 * (actual_time - expected_time), 1)
                        if status == "matched_pitch" and in_span(row, actual_time) else None)
        rows.append(dict(id=row["id"], score_note_id=row["id"], measure=row["measure"], measure_label=row["measure_label"],
                         beat=round(row["beat"], 4), score_beat=row["score_beat"], part=row["part"], voice=row["voice"],
                         expected_note=row["name"], played_note=actual["note_name"] if actual else None,
                         performance_id=played_id, expected_time=round(expected_time, 4),
                         time=round(actual_time, 4) if actual else round(expected_time, 4),
                         timing_delta_ms=timing_delta,
                         hand=actual["hand"] if finger else None, finger=finger, reference_fingers=reference_fingers,
                         fingering_difference=bool(finger and reference_fingers and finger not in reference_fingers
                                                   and status == "matched_pitch"), status=status))

    for extra in extra_notes:
        if extra.id in assigned_extras:
            continue
        closest = min(references, key=lambda row: abs(mapped[row["id"]] - extra.onset))
        trusted = bounded(closest, extra.onset) and abs(mapped[closest["id"]] - extra.onset) <= DEFAULT.tolerance_ms / 1000
        rows.append(dict(id=f"p:{extra.id}", score_note_id=None, measure=closest["measure"] if trusted else None,
                         measure_label=closest["measure_label"] if trusted else None, beat=None,
                         expected_note=None, played_note=by_id[extra.id]["note_name"], performance_id=extra.id,
                         time=round(extra.onset, 4), status="extra_candidate" if trusted else "review"))
    rows.sort(key=lambda row: (row["time"], row["id"]))
    result.update(status="aligned", counts=dict(Counter(row["status"] for row in rows)), rows=rows)
    for measure in passage["measures"]:
        items = [row for row in rows if row["measure"] == measure["position"]]
        observed_beats = {}
        for row in items:
            if row["status"] == "matched_pitch":
                observed_beats.setdefault(row["score_beat"], []).append(row["time"])
        points = [(beat, median(times)) for beat, times in sorted(observed_beats.items())]
        rates = [(b - a) / (later - earlier) * 60
                 for (a, earlier), (b, later) in zip(points, points[1:]) if later - earlier > .03]
        result["measures"].append(dict(position=measure["position"], label=measure["label"],
                                       matched=sum(row["status"] == "matched_pitch" for row in items),
                                       bpm=round(median(rates), 1) if len(rates) >= 2 else None))
    return result


def score_segment(report, start, end, selected):
    if report["status"] != "aligned":
        return {"title": report["title"], "status": report["status"]}
    chosen = set(selected)
    rows = [row for row in report["rows"] if start - .001 <= row["time"] < end
            and (not chosen or row["performance_id"] in chosen)]
    if not rows:
        return None
    prioritized = [row for row in rows if row.get("manual_review") or row.get("reference_finger_source") == "manual"]
    ids = {row["id"] for row in prioritized}
    scoped = (prioritized + [row for row in rows if row["id"] not in ids])[:48]
    scoped.sort(key=lambda row: (row["time"], row["id"]))
    return dict(title=report["title"], status="aligned", revision=report.get("revision", 0), total=len(rows), rows=scoped,
                counts=dict(Counter(row["status"] for row in rows)))


def score_guidance(segment):
    if segment["status"] != "aligned":
        return [], []
    _, nodes, edges = graph_index()
    rule_ids = ["R01", "R10"]
    if any(row["status"] == "matched_pitch" and row.get("reference_fingers") and row.get("finger")
           for row in segment["rows"]):
        rule_ids.append("R11")
    rules, references = [], {}
    for identifier in rule_ids:
        rule = nodes[identifier]
        sources = []
        for evidence in edges[identifier, "GROUNDED_IN"]:
            for paper in edges[evidence, "supported_by"]:
                source = nodes[paper]
                if source.get("reviewed"):
                    references[paper] = dict(id=paper, title=source["title"], url=source["url"],
                                             tip=source["finding_zh"], limit=source["limit_zh"])
                    sources.append(paper)
        rules.append(dict(id=identifier, label=rule["label"], logic=rule["logic"],
                          advice=[nodes[tip]["advice"] for tip in edges[identifier, "SUGGESTS"]],
                          reference_ids=list(dict.fromkeys(sources))))
    return rules, list(references.values())
