import math
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import BoundedSemaphore

from ..analysis.calibration import keyboard_mapping
from .errors import ConflictError
from .job_runner import STAGES, run_analysis


class JobService:
    def __init__(self, artifacts, assets, root):
        self.artifacts = artifacts
        self.assets = assets
        self.root = root
        self.worker = ThreadPoolExecutor(max_workers=1)
        self.queue = BoundedSemaphore(6)

    def history(self, owner):
        return self.artifacts.jobs(owner)

    def job(self, owner, identifier, *, finished=False):
        folder = self.artifacts.owned_folder(owner, identifier)
        job = self.artifacts.read_json(folder / "job.json")
        if finished and job["status"] != "succeeded":
            raise ConflictError("任务尚未完成")
        return folder, job

    def result(self, folder):
        return dict(
            summary=self.artifacts.read_json(folder / "analysis_summary.json"),
            notes=list(self.artifacts.note_rows(folder)),
        )

    def submit(self, owner, data):
        _, video = self.assets.asset(owner, data["video_id"])
        mode = data.get("mode", "fingering")
        if mode not in STAGES:
            raise ValueError("分析模式无效")
        offset = float(data.get("offset", 0))
        if video["kind"] != "video" or not math.isfinite(offset) or abs(offset) > 120:
            raise ValueError("输入类型或偏移无效")

        mirrored = data.get("mirrored") is True
        midi_id = reference_id = mapping = None
        warning = False
        if mode == "fingering":
            midi_id, warning, mapping = self.prepare_fingering(owner, data, video, offset, mirrored)
        if mode == "audio":
            reference_id = data.get("reference_id")
            if reference_id and self.assets.asset(owner, reference_id)[1]["kind"] != "midi":
                raise ValueError("参考乐谱须为 MIDI")

        if not self.queue.acquire(blocking=False):
            raise ConflictError("本地队列已满，请稍后提交")
        try:
            identifier, folder = self.artifacts.create_folder()
            if mapping:
                self.artifacts.write_json(folder / "mapping.json", mapping)
            job = dict(
                id=identifier, video_id=video["id"], midi_id=midi_id, mode=mode, offset=offset if midi_id else None,
                status="queued", stage="等待分析", duration_warning=warning, mirrored=mirrored,
                reference_id=reference_id, title=video.get("name") or "演奏视频",
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            self.artifacts.write_json(folder / "job.json", job)
            self.artifacts.register(owner, identifier, "job")
            self.worker.submit(self.execute, job.copy())
        except Exception:
            self.queue.release()
            raise
        return job

    def prepare_fingering(self, owner, data, video, offset, mirrored):
        if not data.get("midi_id"):
            raise ValueError("逐音符指法分析需要 MIDI；请改选手部骨架回放")
        _, midi = self.assets.asset(owner, data["midi_id"])
        if midi["kind"] != "midi":
            raise ValueError("输入类型无效")
        first, last = int(data.get("first", 21)), int(data.get("last", 108))
        if midi["minimum"] < first or midi["maximum"] > last:
            raise ValueError("MIDI 音域超出所选键盘范围")
        warning = abs(midi["duration"] + offset - video["duration"]) > max(10, video["duration"] * .35)
        if warning and not data.get("confirm_duration"):
            raise ConflictError("MIDI 与视频时长明显不同；确认同一次演奏后才能继续", confirmation_required=True)
        time = float(data.get("calibration_time", 0))
        if not math.isfinite(time) or not 0 <= time < video["duration"]:
            raise ValueError("校准时间超出视频范围")
        mapping = keyboard_mapping(data["corners"], video["width"], video["height"], first, last, mirrored)
        mapping.update(calibration_time_seconds=time, calibration_frame_index=int(time * video["fps"]))
        return midi["id"], warning, mapping

    def execute(self, job):
        try:
            run_analysis(job, self.artifacts, self.root)
        finally:
            self.queue.release()
