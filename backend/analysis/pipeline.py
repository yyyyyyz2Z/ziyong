"""Run calibration-aware fingering analysis and render a traceable replay."""

import argparse
import csv
import json
from pathlib import Path
from tempfile import TemporaryFile

import cv2
import numpy as np
import pretty_midi

from .alignment import align_notes, read_video_info, write_csv
from .aligned_landmarks import process as extract_landmarks
from .fingering_match import assign_fingers, keyboard_regions
from .hand_tracking import draw_tracked_skeletons
from .predict_fingering import TIP_INDEX_TO_FINGER
from .score_review import analyze_passage
from .technique_graph import analyze_exercise, supports_exercise


FINGER_TO_TIP = {finger: tip for tip, finger in TIP_INDEX_TO_FINGER.items()}


def render_replay(video, destination, info, track, predictions, matches, regions):
    by_frame = {}
    for row, (_, _, candidate, _, _) in zip(predictions, matches):
        if row["start_frame"] is not None:
            by_frame.setdefault(row["start_frame"], []).append((row, candidate))
    fps, width, height = info["fps"], info["width"], info["height"]
    capture = cv2.VideoCapture(str(video))
    writer = cv2.VideoWriter(str(destination), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    active_notes = []
    last_onset = -1
    hold_frames = round(fps * .16)
    try:
        if not capture.isOpened() or not writer.isOpened():
            raise RuntimeError("无法读取原片或创建指法回放视频")
        track.seek(0)
        for index, line in enumerate(track):
            ok, frame = capture.read()
            if not ok:
                raise RuntimeError("指法回放无法读取已追踪的视频帧")
            positions = json.loads(line)
            draw_tracked_skeletons(frame, positions)
            if index in by_frame:
                active_notes = by_frame[index]
                last_onset = index
            if active_notes and index - last_onset <= hold_frames:
                draw_note_evidence(frame, active_notes, dict(positions), regions)
            writer.write(frame)
        if capture.read()[0]:
            raise RuntimeError("指法回放的帧数与手部追踪结果不一致")
    finally:
        capture.release()
        writer.release()


def draw_note_evidence(frame, notes, hands, regions):
    width = frame.shape[1]
    for number, (row, candidate) in enumerate(notes):
        outline = regions[int(row["pitch"])].outline
        cv2.polylines(frame, [outline], True, (10, 10, 10), 5, cv2.LINE_AA)
        cv2.polylines(frame, [outline], True, (60, 245, 255), 2, cv2.LINE_AA)
        if candidate is not None and candidate[0] in hands:
            hand, finger = candidate
            tip = hands[hand][FINGER_TO_TIP[finger]]
            point = (round(tip["x"]), round(tip["y"]))
            cv2.circle(frame, point, 10, (10, 10, 10), 4, cv2.LINE_AA)
            cv2.circle(frame, point, 10, (255, 255, 255), 2, cv2.LINE_AA)
        label = f'{row["note_name"]} {row["hand"] or "?"} hand / finger {row["finger"] or "?"} | {row["status"]}'
        y = 35 + number * 29
        cv2.rectangle(frame, (8, y - 25), (min(width - 8, 580), y + 5), (20, 20, 28), -1)
        cv2.putText(frame, label, (16, y), cv2.FONT_HERSHEY_SIMPLEX, .65, (0, 245, 255), 2, cv2.LINE_AA)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--midi", required=True, type=Path)
    parser.add_argument("--mapping", required=True, type=Path, help="Keyboard mapping calibrated for this fixed camera")
    parser.add_argument("--output-dir", default=Path("outputs/session"), type=Path)
    parser.add_argument("--offset", type=float, default=0.0)
    args = parser.parse_args()
    if not np.isfinite(args.offset) or abs(args.offset) > 120:
        parser.error("--offset must be finite and within ±120 seconds")
    video, midi_path, mapping_path, output = args.video, args.midi, args.mapping, args.output_dir
    for path in (video, midi_path, mapping_path):
        if not path.is_file():
            parser.error(f"File not found: {path}")
    output.mkdir(parents=True, exist_ok=True)

    midi = pretty_midi.PrettyMIDI(str(midi_path))
    notes = [
        {"instrument_index": track, "track": instrument.name, "pitch": note.pitch,
         "note_name": pretty_midi.note_number_to_name(note.pitch), "start_seconds": note.start,
         "end_seconds": note.end, "duration_seconds": note.end - note.start, "velocity": note.velocity,
         "hand": "", "finger": "", "confidence": 0.0, "status": "unreviewed"}
        for track, instrument in enumerate(midi.instruments) for note in instrument.notes
    ]
    notes.sort(key=lambda row: (row["start_seconds"], row["pitch"]))
    if not notes:
        parser.error("MIDI contains no note events")
    if any(not 21 <= note["pitch"] <= 108 for note in notes):
        parser.error("MIDI contains notes outside piano range 21–108")
    with (output / "midi_notes.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(notes[0]))
        writer.writeheader()
        writer.writerows(notes)
    info = read_video_info(video)
    in_video = [0 <= note["start_seconds"] + args.offset < info["duration_seconds"] for note in notes]
    overlap = sum(in_video) / len(notes)
    if overlap < .8:
        parser.error(f"Only {overlap:.1%} of MIDI note onsets fit video; check song/MIDI and --offset")
    if abs(midi.get_end_time() + args.offset - info["duration_seconds"]) > max(10, info["duration_seconds"] * .35):
        print("WARNING: MIDI/video durations differ substantially; verify they are the same performance.")
    aligned = align_notes(output / "midi_notes.csv", info, args.offset)
    write_csv(aligned, output / "aligned_notes.csv")

    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    mirrored = bool(mapping.get("mirrored", False))
    keys = {int(key["midi_pitch"]): key for key in mapping.get("key_centers", [])}
    mapping_video = mapping.get("video")
    mapping_warning = bool(mapping_video and Path(mapping_video).name.lower() != video.name.lower())
    if mapping_warning:
        print(f"WARNING: mapping source is {Path(mapping_video).name}; confirm camera/framing is identical.")
    missing = sorted({note["pitch"] for note in notes if note["pitch"] not in keys})
    if missing:
        parser.error(f"Keyboard mapping misses MIDI pitches: {missing[:12]}")
    to_keyboard, regions = keyboard_regions(mapping, keys)
    fps = info["fps"]
    visible_notes = [row for row, visible in zip(aligned, in_video) if visible]
    technique = None

    # Keep the full replay track on disk while retaining only finger-scoring
    # windows in memory. A single tracking pass provides both sets of points.
    with TemporaryFile(mode="w+t", encoding="utf-8") as track:
        detected = iter(extract_landmarks(video, visible_notes, mirrored, replay_track=track))
        landmarks = [
            next(detected) if visible else dict(note_index=int(row["note_index"]), pitch=int(row["pitch"]),
                start_seconds=float(row["start_seconds"]), start_frame=None,
                hands={}, hands_by_frame={}, sample_frames=[])
            for row, visible in zip(aligned, in_video)
        ]
        with (output / "aligned_landmarks.jsonl").open("w", encoding="utf-8") as stream:
            for row in landmarks:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        matches = assign_fingers(landmarks, keys, regions, to_keyboard)
        predictions = []
        for row, aligned_row, (status, reason, candidate, confidence, distance) in zip(landmarks, aligned, matches):
            hand, finger = candidate if status == "matched" else ("", "")
            predictions.append({
                **{key: aligned_row[key] for key in ("note_index", "pitch", "start_seconds", "end_seconds")},
                "start_frame": row["start_frame"], "note_name": pretty_midi.note_number_to_name(row["pitch"]),
                "hand": hand, "finger": finger,
                "distance_pixels": round(distance, 2) if distance is not None else "",
                "confidence": round(confidence, 4), "confidence_type": "geometric_support_not_probability",
                "status": status, "reason": reason,
            })
        with (output / "fingering_predictions.csv").open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(predictions[0]))
            writer.writeheader()
            writer.writerows(predictions)
        exercise = mapping.get("exercise")
        if supports_exercise(exercise):
            technique = analyze_exercise(predictions, track, to_keyboard, regions, fps, args.offset, exercise)
        render_replay(video, output / "fingering_replay.mp4", info, track, predictions, matches, regions)

    score_passage = output / "score_passage.json"
    score_status = None
    if score_passage.is_file():
        passage = json.loads(score_passage.read_text(encoding="utf-8"))
        comparison = analyze_passage(passage, predictions, args.offset)
        (output / "score_alignment.json").write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")
        score_status = comparison["status"]
    counts = {status: sum(row["status"] == status for row in predictions)
              for status in ("matched", "uncertain", "unmatched")}
    summary = {
        "mode": "fingering", "video": str(video.resolve()), "midi": str(midi_path.resolve()),
        "mapping": str(mapping_path.resolve()), "mapping_source_warning": mapping_warning,
        "offset_seconds": args.offset, "fps": fps, "video_duration_seconds": info["duration_seconds"],
        "midi_duration_seconds": midi.get_end_time(), "onset_overlap_ratio": round(overlap, 4),
        "notes": len(notes), "status_counts": counts,
        "coverage": round(counts["matched"] / len(notes), 4),
        "mean_geometric_support": round(float(np.mean([row["confidence"] for row in predictions])), 4),
        "mirrored": mirrored, "algorithm_version": "pianocv-key-region-v1" if mapping.get("source") else "key-region-v1",
        "keyboard_source": mapping.get("source", "legacy_calibration"),
        "technique": technique,
        "score_alignment_status": score_status,
        "algorithm": "MediaPipe Hands; rectified key regions; multi-frame contact scoring and chord assignment",
        "score": None, "score_note": "No validated performance score is computed. Geometric support is not accuracy.",
    }
    for name in ("session.json", "analysis_summary.json"):
        (output / name).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Complete: {len(notes)} notes; status counts {counts}; output {output.resolve()}")


if __name__ == "__main__":
    main()
