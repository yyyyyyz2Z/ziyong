"""Load MIDI or MusicXML into a common note-event table."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Dict, List, Union

import pretty_midi


def _from_midi(path: Path, piano_only: bool = False) -> List[Dict[str, float]]:
    midi = pretty_midi.PrettyMIDI(str(path))
    notes = []
    for instrument in midi.instruments:
        # MIDI program 0 is Acoustic Grand Piano. Ignore percussion when
        # comparing against a piano performance.
        if instrument.is_drum:
            continue
        if piano_only and instrument.program not in {0, 1, 2, 3}:
            continue
        for note in instrument.notes:
            notes.append(
                {
                    "pitch": int(note.pitch),
                    "start_seconds": float(note.start),
                    "end_seconds": float(note.end),
                    "duration_seconds": float(note.end - note.start),
                }
            )
    return sorted(notes, key=lambda row: (row["start_seconds"], row["pitch"]))


def load_score(path: Union[str, Path], piano_only: bool = False) -> List[Dict[str, float]]:
    """Load .mid/.midi directly or convert MusicXML through music21."""
    score_path = Path(path)
    if not score_path.exists():
        raise FileNotFoundError(f"Score not found: {score_path}")
    suffix = score_path.suffix.lower()
    if suffix in {".mid", ".midi"}:
        return _from_midi(score_path, piano_only=piano_only)
    if suffix in {".xml", ".musicxml", ".mxl"}:
        try:
            from music21 import converter
        except ImportError as exc:
            raise RuntimeError(
                "MusicXML support requires music21. Install it with: "
                "python -m pip install music21"
            ) from exc
        score = converter.parse(str(score_path))
        with tempfile.TemporaryDirectory() as temp_dir:
            midi_path = Path(temp_dir) / "score.mid"
            score.write("midi", fp=str(midi_path))
            return _from_midi(midi_path, piano_only=piano_only)
    raise ValueError("Supported score formats: .mid, .midi, .xml, .musicxml, .mxl")
