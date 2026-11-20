"""Extract audio from a piano video and transcribe it to MIDI/CSV.

This is the first audio-enabled prototype. It requires the ``ffmpeg`` command
to be available on PATH and the Python package ``basic-pitch``.

Usage:
    .venv\Scripts\python.exe -m backend.analysis.video_to_notes \
        --input data\raw\performance.mp4 \
        --output-dir outputs\transcription

With a separate audio file:
    .venv\Scripts\python.exe -m backend.analysis.video_to_notes \
        --input data\raw\performance.mp4 \
        --audio data\raw\performance.m4a \
        --output-dir outputs\transcription
"""

from __future__ import annotations

import argparse
import csv
import shutil
import subprocess
from pathlib import Path
from typing import Optional


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Transcribe piano audio from MP4")
    parser.add_argument("--input", required=True, help="Input MP4 video")
    parser.add_argument(
        "--audio",
        help="Optional external audio file, such as M4A. If omitted, audio is read from MP4.",
    )
    parser.add_argument("--output-dir", default="outputs/transcription")
    return parser.parse_args()


def extract_audio(
    video_path: Path,
    audio_path: Path,
    external_audio: Optional[Path] = None,
) -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg was not found. Install FFmpeg and add its bin directory to PATH."
        )
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(external_audio or video_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "44100",
        # WAV is the container; PCM signed 16-bit little-endian is the codec.
        "-c:a",
        "pcm_s16le",
        str(audio_path),
    ]
    subprocess.run(command, check=True)


def transcribe_audio(audio_path: Path, output_dir: Path) -> Path:
    try:
        from basic_pitch.inference import predict
    except ImportError as exc:
        raise RuntimeError(
            "basic-pitch is not installed. Run: "
            "python -m pip install basic-pitch"
        ) from exc

    _model_output, midi_data, note_events = predict(str(audio_path))
    midi_path = output_dir / "transcribed.mid"
    midi_data.write(str(midi_path))

    csv_path = output_dir / "notes.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow(
            ["start_seconds", "end_seconds", "pitch", "amplitude", "pitch_bends"]
        )
        for event in note_events:
            # basic-pitch versions return either tuples or dict-like events.
            if isinstance(event, dict):
                start = event["start_time"]
                end = event["end_time"]
                pitch = event["pitch"]
                amplitude = event.get("amplitude", event.get("velocity", ""))
                pitch_bends = event.get("pitch_bends", event.get("confidence", ""))
            else:
                start, end, pitch, amplitude, pitch_bends = event[:5]
            writer.writerow([start, end, pitch, amplitude, pitch_bends])

    print(f"Saved generated MIDI to: {midi_path}")
    print(f"Saved note table to: {csv_path}")
    return midi_path


def main() -> None:
    args = parse_args()
    video_path = Path(args.input)
    external_audio = Path(args.audio) if args.audio else None
    output_dir = Path(args.output_dir)
    if not video_path.exists():
        raise FileNotFoundError(f"Video not found: {video_path}")
    if external_audio is not None and not external_audio.exists():
        raise FileNotFoundError(f"Audio file not found: {external_audio}")
    output_dir.mkdir(parents=True, exist_ok=True)

    audio_path = output_dir / "extracted_audio.wav"
    extract_audio(video_path, audio_path, external_audio)
    transcribe_audio(audio_path, output_dir)
    print("Audio transcription complete.")


if __name__ == "__main__":
    main()
