"""Export selected, written-order MusicXML measures as a reference MIDI."""

from __future__ import annotations

import argparse
from collections import defaultdict, deque
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from mido import MetaMessage, MidiFile, MidiTrack


def _measure_grid(score):
    from music21 import stream

    if not isinstance(score, stream.Score):
        raise ValueError("请输入包含单一乐章的 MusicXML 乐谱")
    grids = [
        tuple(
            measure.getOffsetInHierarchy(score)
            for measure in part.getElementsByClass(stream.Measure)
        )
        for part in score.parts
    ]
    if not grids or not grids[0]:
        raise ValueError("乐谱没有可截取的小节")
    if any(grid != grids[0] for grid in grids[1:]):
        raise ValueError("各声部的小节边界不一致，请先校对乐谱")
    return grids[0]


def score_measures(score):
    """Return the written order and printed labels for the selection UI."""
    from music21 import stream

    boundaries = _measure_grid(score)
    measures = score.parts[0].getElementsByClass(stream.Measure)
    return [{"position": index, "label": measure.measureNumberWithSuffix(), "beat": float(beat)}
            for index, (measure, beat) in enumerate(zip(measures, boundaries), 1)]


def _measure_range(score, first: int, last: int):
    boundaries = _measure_grid(score)
    if not 1 <= first <= last <= len(boundaries):
        raise ValueError(f"选段须满足 1 ≤ 起始小节 ≤ 结束小节 ≤ {len(boundaries)}")
    return boundaries[first - 1], boundaries[last] if last < len(boundaries) else score.highestTime


def _use_written_order(score):
    from music21 import bar, repeat, spanner

    # The MIDI writer normally expands repeats, shifting the printed measure offsets.
    marks = list(score.recurse().getElementsByClass(
        (bar.Repeat, repeat.RepeatExpression, spanner.RepeatBracket)
    ))
    for mark in marks:
        score.remove(mark, recurse=True)


def _clip_track(track: MidiTrack, start: int, stop: int) -> MidiTrack:
    # Keep the latest settings active at the cut, including each channel's patch.
    context = {}
    active_notes = defaultdict(deque)
    events = []

    def add_note(onset, note_on, release, note_off):
        clipped_start = max(onset, start)
        if clipped_start < release:
            events.extend(((clipped_start, note_on), (release, note_off)))

    tick = 0
    for event in track:
        tick += event.time
        if tick >= stop:
            break
        if event.type == "end_of_track":
            continue
        if event.type == "note_on" and event.velocity:
            active_notes[event.channel, event.note].append((tick, event))
        elif event.type in ("note_on", "note_off"):
            pending = active_notes.get((event.channel, event.note))
            if pending:
                onset, note_on = pending.popleft()
                add_note(onset, note_on, tick, event)
        elif tick >= start:
            events.append((tick, event))
        elif event.type in ("set_tempo", "time_signature", "key_signature", "track_name",
                            "instrument_name", "program_change", "control_change"):
            key = (event.type, getattr(event, "channel", None), getattr(event, "control", None))
            context[key] = event

    for pending in active_notes.values():
        for onset, note_on in pending:
            add_note(onset, note_on, stop, note_on.copy(velocity=0))

    # At a shared tick, release an old note before starting the next one.
    events.sort(key=lambda item: (item[0], item[1].type == "note_on" and item[1].velocity > 0))
    excerpt = MidiTrack(event.copy(time=0) for event in context.values())
    previous_tick = start
    for tick, event in events:
        excerpt.append(event.copy(time=tick - previous_tick))
        previous_tick = tick
    excerpt.append(MetaMessage("end_of_track", time=stop - previous_tick))
    return excerpt


def read_musicxml(source: Path):
    from music21 import converter

    source = Path(source)
    if source.suffix.lower() not in {".musicxml", ".xml", ".mxl"}:
        raise ValueError("请输入 .musicxml、.xml 或 .mxl 乐谱")
    return converter.parseFile(source, format="musicxml", forceSource=True, storePickle=False)


def excerpt_midi(score, first: int, last: int) -> MidiFile:
    from music21.midi.translate import streamToMidiFile

    first_beat, end_beat = _measure_range(score, first, last)
    # Convert the complete written score first so ties can join across the cut.
    _use_written_order(score)
    full_score = streamToMidiFile(score, addStartDelay=False)
    original = MidiFile(file=BytesIO(full_score.writestr()))
    start = round(first_beat * original.ticks_per_beat)
    stop = round(end_beat * original.ticks_per_beat)
    if start >= stop:
        raise ValueError("所选小节没有可导出的时长")
    excerpt = MidiFile(type=original.type, ticks_per_beat=original.ticks_per_beat)
    excerpt.tracks = [_clip_track(track, start, stop) for track in original.tracks]
    if not any(event.type == "note_on" and event.velocity
               for track in excerpt.tracks for event in track):
        raise ValueError("所选小节没有可导出的音符")
    return excerpt


def export_excerpt(source: Path, destination: Path, first: int, last: int) -> Path:
    """Write the inclusive range of 1-based measure positions in score order."""
    destination = Path(destination)
    if destination.suffix.lower() not in {".mid", ".midi"}:
        raise ValueError("输出文件须使用 .mid 或 .midi 扩展名")

    excerpt = excerpt_midi(read_musicxml(source), first, last)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=destination.parent) as directory:
        temporary = Path(directory) / destination.name
        excerpt.save(temporary)
        temporary.replace(destination)
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description="按书面顺序从 MusicXML 截取连续小节并输出参考 MIDI")
    parser.add_argument("score", type=Path)
    parser.add_argument("--first", type=int, required=True, help="起始小节位置，从 1 开始")
    parser.add_argument("--last", type=int, required=True, help="结束小节位置，包含在选段内")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        destination = export_excerpt(args.score, args.output, args.first, args.last)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(destination)


if __name__ == "__main__":
    main()
