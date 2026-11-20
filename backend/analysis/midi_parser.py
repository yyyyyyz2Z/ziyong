"""Read a MIDI file and print note timing and velocity information.

Usage:
    .venv\Scripts\python.exe -m backend.analysis.midi_parser \
        --input data\raw\performance.mid

Optional CSV export:
    .venv\Scripts\python.exe -m backend.analysis.midi_parser \
        --input data\raw\performance.mid \
        --csv outputs\midi_notes.csv
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import pretty_midi


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Print notes from a MIDI file")
    parser.add_argument("--input", required=True, help="Input MIDI path")
    parser.add_argument("--csv", help="Optional output CSV path")
    return parser.parse_args()


def note_rows(midi: pretty_midi.PrettyMIDI) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for instrument_index, instrument in enumerate(midi.instruments):
        track_name = instrument.name or f"Instrument {instrument_index + 1}"
        for note_index, note in enumerate(instrument.notes, start=1):
            rows.append(
                {
                    "instrument_index": instrument_index,
                    "track": track_name,
                    "note_index": len(rows),
                    "pitch": note.pitch,
                    "note_name": pretty_midi.note_number_to_name(note.pitch),
                    "start_seconds": round(note.start, 6),
                    "end_seconds": round(note.end, 6),
                    "duration_seconds": round(note.end - note.start, 6),
                    "velocity": note.velocity,
                    "hand": "",
                    "finger": "",
                    "confidence": 0.0,
                    "status": "unreviewed",
                    "reviewed": "false",
                }
            )
    return rows


def write_csv(rows: list[dict[str, object]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "instrument_index",
        "track",
        "note_index",
        "pitch",
        "note_name",
        "start_seconds",
        "end_seconds",
        "duration_seconds",
        "velocity",
        "hand", "finger", "confidence", "status", "reviewed",
    ]
    with output_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    args = parse_args()
    input_path = Path(args.input)
    if not input_path.exists():
        raise FileNotFoundError(f"MIDI file not found: {input_path}")

    midi = pretty_midi.PrettyMIDI(str(input_path))
    rows = note_rows(midi)

    print(f"MIDI: {input_path}")
    print(f"Duration: {midi.get_end_time():.3f} seconds")
    print(f"Tracks: {len(midi.instruments)}")
    print(f"Notes: {len(rows)}")
    print()
    print("track | note | pitch | start(s) | end(s) | duration(s) | velocity")
    print("-" * 78)
    for row in rows:
        print(
            f"{row['track']} | {row['note_name']} | {row['pitch']} | "
            f"{row['start_seconds']:.3f} | {row['end_seconds']:.3f} | "
            f"{row['duration_seconds']:.3f} | {row['velocity']}"
        )

    if args.csv:
        write_csv(rows, Path(args.csv))
        print(f"\nSaved note table to: {args.csv}")


if __name__ == "__main__":
    main()
