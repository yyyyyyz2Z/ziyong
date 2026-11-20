"""Transcribe the video's audio and optionally compare it with a reference MIDI."""

import argparse
import json
import subprocess
from pathlib import Path

from .alignment import read_video_info
from .compare_performance import comparison, write_comparison
from .score_loader import load_score
from .video_to_notes import extract_audio, transcribe_audio


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--reference", type=Path)
    args = parser.parse_args()
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    wav = output / "extracted_audio.wav"
    try:
        extract_audio(args.video, wav)
    except subprocess.CalledProcessError:
        parser.exit(1, "无法提取视频音轨。请上传含有清晰钢琴声音的视频。\n")
    observed = load_score(transcribe_audio(wav, output))
    if not observed:
        parser.exit(1, "未转录出音符。请检查音轨是否包含清晰的钢琴声。\n")

    info = read_video_info(args.video)
    summary = {
        "mode": "audio", "video_duration_seconds": info["duration_seconds"],
        "notes": len(observed), "algorithm": "Basic Pitch",
        "reference": str(args.reference) if args.reference else None,
    }
    if args.reference:
        reference = load_score(args.reference)
        if len(reference) * len(observed) > 2_000_000:
            summary["comparison_status"] = "too_large"
        else:
            rows, metrics = comparison(reference, observed)
            coverage = metrics["correct"] / max(1, min(len(reference), len(observed)))
            summary["comparison_coverage"] = coverage
            if metrics["correct"] >= 8 and coverage >= .5:
                summary["comparison_status"] = "candidate"
                summary["comparison"] = metrics
                write_comparison(output / "comparison.csv", rows)
            else:
                summary["comparison_status"] = "insufficient"
    (output / "analysis_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
