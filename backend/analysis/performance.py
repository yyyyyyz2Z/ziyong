"""Combine score, audio timing, key geometry and hand tracking for one video."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pretty_midi

from .symbolic_alignment import Note, predict_alignment
from .video_to_notes import extract_audio, transcribe_audio
from .performance_graph import build_graph


def align_reference(reference, performed, duration):
    """Bound the alignment matrix while retaining full-recording coverage."""
    matches, anchors = {}, []
    for first in range(0, len(reference), 300):
        last = min(first + 300, len(reference))
        low = max(0, int(first / len(reference) * len(performed)) - 150)
        high = min(len(performed), int(last / len(reference) * len(performed)) + 150)
        if high <= low:
            continue
        prediction = predict_alignment(reference[first:last], performed[low:high])
        matches.update(prediction["pairs"])
        anchors.extend(prediction["anchors"])
    monotone = []
    for anchor in sorted(set(anchors)):
        if not monotone or anchor[0] > monotone[-1][0] and anchor[1] > monotone[-1][1]:
            monotone.append(anchor)
    if len(monotone) >= 2:
        source, target = np.array(monotone).T
        # Extrapolate using the neighboring local tempo at the two ends.
        def project(value):
            if value < source[0]:
                return target[0] + (value - source[0]) * (target[1] - target[0]) / (source[1] - source[0])
            if value > source[-1]:
                return target[-1] + (value - source[-1]) * (target[-1] - target[-2]) / (source[-1] - source[-2])
            return float(np.interp(value, source, target))
    else:
        first = performed[0].onset if performed else 0
        last = performed[-1].onset if performed else duration - .1
        span = max(.1, reference[-1].onset - reference[0].onset)
        def project(value):
            return first + (value - reference[0].onset) * max(.1, last - first) / span
    by_id = {note.id: note for note in performed}
    events = []
    for note in reference:
        expected = float(project(note.onset))
        actual = by_id.get(matches.get(note.id)) if len(monotone) >= 2 else None
        onset = actual.onset if actual else expected
        end = actual.onset + actual.duration if actual else project(note.onset + note.duration)
        events.append(dict(reference_id=note.id, pitch=note.pitch, expected_time=round(expected, 4),
                           start=round(max(0, min(duration - .02, onset)) * 20000) / 20000,
                           end=max(.01, min(duration, max(onset + .03, end))),
                           timing_source="audio" if actual else "score_projection",
                           timing_delta_ms=round((actual.onset - expected) * 1000, 1) if actual else None))
    events.sort(key=lambda row: (row["start"], row["pitch"]))
    return events, monotone


def analyze(video, folder):
    passage = json.loads((folder / "reference_passage.json").read_text(encoding="utf-8"))
    mapping = json.loads((folder / "mapping.json").read_text(encoding="utf-8"))
    import cv2
    capture = cv2.VideoCapture(str(video))
    duration = capture.get(cv2.CAP_PROP_FRAME_COUNT) / capture.get(cv2.CAP_PROP_FPS)
    capture.release()
    extract_audio(video, folder / "extracted_audio.wav")
    transcribed = transcribe_audio(folder / "extracted_audio.wav", folder)
    midi = pretty_midi.PrettyMIDI(str(transcribed))
    played = sorted((note for instrument in midi.instruments if not instrument.is_drum for note in instrument.notes
                     if 21 <= note.pitch <= 108), key=lambda note: (note.start, note.pitch))
    performance = [Note(str(index), note.pitch, note.start, note.end - note.start) for index, note in enumerate(played)]
    reference = [Note(row["id"], row["pitch"], row["onset"], row["duration"]) for row in passage["notes"]]
    events, anchors = align_reference(reference, performance, duration)
    guide = pretty_midi.PrettyMIDI(resolution=10000)
    track = pretty_midi.Instrument(0, name="Aligned score")
    for row in events:
        track.notes.append(pretty_midi.Note(80, row["pitch"], row["start"], max(row["start"] + .01, row["end"])))
    guide.instruments.append(track)
    guide.write(str(folder / "aligned_reference.mid"))
    subprocess.run([sys.executable, "-m", "backend.analysis.pipeline", "--video", str(video),
                    "--midi", str(folder / "aligned_reference.mid"), "--mapping", str(folder / "mapping.json"),
                    "--output-dir", str(folder)], check=True)
    import csv
    with (folder / "fingering_predictions.csv").open(encoding="utf-8-sig") as stream:
        predictions = list(csv.DictReader(stream))
    graph, report = build_graph(passage, predictions, events, mapping, duration)
    (folder / "performance_graph.json").write_text(json.dumps(graph, ensure_ascii=False), encoding="utf-8")
    (folder / "score_alignment.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    summary_path = folder / "analysis_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary.update(mode="performance", alignment_anchors=len(anchors), performance=graph["summary"],
                   reference_assumption="same_piece_complete", score_alignment_status="aligned")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args()
    analyze(arguments.video, arguments.output_dir)
