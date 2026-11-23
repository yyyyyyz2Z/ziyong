"""Run analysis workers and update their persisted statuses."""

import subprocess
import sys

from .assets import ASSET_FILES


STAGES = {
    "performance": "提取演奏起音、跟踪手指并关联乐谱",
    "skeleton_only": "提取手部关键点",
    "fingering": "对齐音符并推断指法",
    "audio": "转录视频音轨",
}


def analysis_command(job, artifacts, folder, video):
    command = [sys.executable, "-m"]
    mode = job["mode"]
    if mode == "performance":
        command += ["backend.analysis.performance", "--video", str(video), "--output-dir", str(folder)]
    elif mode == "skeleton_only":
        command += ["backend.analysis.skeleton_replay", "--video", str(video), "--output-dir", str(folder)]
        if job.get("mirrored"):
            command.append("--mirrored")
    elif mode == "audio":
        command += ["backend.analysis.audio_analysis", "--video", str(video), "--output-dir", str(folder)]
        if job.get("reference_id"):
            reference = artifacts.folder(job["reference_id"]) / ASSET_FILES["midi"]
            command += ["--reference", str(reference)]
    else:
        midi = artifacts.folder(job["midi_id"]) / ASSET_FILES["midi"]
        command += [
            "backend.analysis.pipeline", "--video", str(video), "--midi", str(midi),
            "--mapping", str(folder / "mapping.json"), "--offset", str(job["offset"]),
            "--output-dir", str(folder),
        ]
    return command


def run_analysis(job, artifacts, root):
    folder = artifacts.folder(job["id"])
    metadata = folder / "job.json"
    try:
        mode = job["mode"]
        job.update(status="running", stage=STAGES[mode])
        artifacts.write_json(metadata, job)
        video = artifacts.folder(job["video_id"]) / ASSET_FILES["video"]
        log_path = folder / "process.log"
        with log_path.open("w", encoding="utf-8") as log:
            result = subprocess.run(analysis_command(job, artifacts, folder, video), stdout=log, stderr=log, cwd=root)
        if result.returncode:
            raise ValueError(log_path.read_text(encoding="utf-8", errors="replace")[-1800:])
        if mode != "audio":
            job.update(stage="转换浏览器回放视频")
            artifacts.write_json(metadata, job)
            convert_replay(folder, video)
        job.update(status="succeeded", stage="完成")
        if mode == "performance":
            artifacts.write_json(folder / "overview.json", {"status": "pending"})
    except Exception as exc:
        job.update(status="failed", stage="失败", error=str(exc))
    finally:
        artifacts.write_json(metadata, job)


def convert_replay(folder, video):
    result = subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error", "-i", str(folder / "fingering_replay.mp4"), "-i", str(video),
        "-map", "0:v:0", "-map", "1:a?", "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-movflags", "+faststart", str(folder / "replay.mp4"),
    ], capture_output=True)
    if result.returncode:
        raise ValueError("浏览器回放转换失败：" + result.stderr.decode("utf-8", errors="replace")[-500:])
