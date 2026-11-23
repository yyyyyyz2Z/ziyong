import hashlib
import json
import math
import pretty_midi
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import BoundedSemaphore, Lock

from ..analysis.calibration import keyboard_mapping, pianocv_mapping
from ..analysis.score_review import analyze_passage, select_passage
from ..analysis.score_revisions import change_review, effective_report
from ..analysis.technique_graph import supports_exercise
from .errors import ConflictError
from .job_runner import STAGES, run_analysis


def _passage_fingerprint(passage):
    identity = {key: passage[key] for key in ("first", "last", "notes", "ornament_measures")}
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


class JobService:
    def __init__(self, artifacts, assets, root, coach=None):
        self.artifacts = artifacts
        self.assets = assets
        self.root = root
        self.worker = ThreadPoolExecutor(max_workers=1)
        self.queue = BoundedSemaphore(6)
        self.score_lock = Lock()
        self.coach = coach

    def history(self, owner):
        return self.artifacts.jobs(owner)

    def job(self, owner, identifier, *, finished=False):
        folder = self.artifacts.owned_folder(owner, identifier)
        job = self.artifacts.read_json(folder / "job.json")
        if finished and job["status"] != "succeeded":
            raise ConflictError("任务尚未完成")
        return folder, job

    def result(self, folder):
        result = dict(
            summary=self.artifacts.read_json(folder / "analysis_summary.json"),
            notes=list(self.artifacts.note_rows(folder)),
        )
        report = self.score_result(folder)
        if report is not None:
            result["score_alignment"] = report
        overview = folder / "overview.json"
        if overview.is_file():
            result["overview"] = self.artifacts.read_json(overview)
        return result

    def performance_reference(self, owner, data):
        if data.get("score_id"):
            folder, score = self.assets.asset(owner, data["score_id"])
            if score["kind"] != "score":
                raise ValueError("请选择曲目乐谱")
            document = self.artifacts.read_json(folder / "score.json")
            first = data.get("measure_first", 1)
            last = data.get("measure_last", len(document["measures"]))
            if type(first) is not int or type(last) is not int or not 1 <= first <= last <= len(document["measures"]):
                raise ValueError("请选择有效的小节范围")
            origin = document["measures"][first - 1]["seconds"]
            return dict(document, first=first, last=last,
                        notes=[dict(row, onset=row["onset"] - origin) for row in document["notes"]
                               if first <= row["measure"] <= last],
                        measures=document["measures"][first - 1:last])
        folder, asset = self.assets.asset(owner, data["reference_id"])
        if asset["kind"] != "midi":
            raise ValueError("请选择曲目的参考 MIDI")
        midi = pretty_midi.PrettyMIDI(str(folder / "input.mid"))
        notes = sorted([dict(pitch=note.pitch, name=pretty_midi.note_number_to_name(note.pitch), onset=note.start,
                             duration=note.end - note.start, part=part, reference_fingers=[])
                        for part, instrument in enumerate(midi.instruments, 1) if not instrument.is_drum
                        for note in instrument.notes], key=lambda row: (row["onset"], row["pitch"]))
        for index, row in enumerate(notes):
            row["id"] = f"r{index:05}"
        return dict(title=asset["name"], notes=notes, measures=[], ornament_measures=[])

    def score_result(self, folder):
        path = folder / "score_alignment.json"
        if path.is_file():
            report = self.artifacts.read_json(path)
            if report.get("edits"):
                summary = self.artifacts.read_json(folder / "analysis_summary.json")
                return effective_report(report, self.artifacts.note_rows(folder), float(summary.get("offset_seconds") or 0))
            return report
        return None

    def score_passage(self, owner, data):
        score_folder, score = self.assets.asset(owner, data["score_id"])
        if score["kind"] != "score":
            raise ValueError("曲目选段需要 MusicXML 乐谱")
        first, last = data.get("measure_first"), data.get("measure_last")
        if type(first) is not int or type(last) is not int:
            raise ValueError("请指定起始和结束小节")
        return select_passage(self.artifacts.read_json(score_folder / "score.json"), first, last)

    def edit_score(self, owner, identifier, data, *, replace):
        folder, job = self.job(owner, identifier, finished=True)
        if job.get("mode", "fingering") != "fingering":
            raise ValueError("该任务没有逐音指法数据")
        path = folder / "score_alignment.json"
        with self.score_lock:
            previous = self.artifacts.read_json(path) if path.is_file() else None
            revision = previous.get("revision", 0) if previous else 0
            if type(data.get("revision")) is not int or data["revision"] != revision:
                raise ConflictError("对齐结果已更新，请重新打开演奏后再保存")
            notes = list(self.artifacts.note_rows(folder))
            summary = self.artifacts.read_json(folder / "analysis_summary.json")
            offset = float(summary.get("offset_seconds") or 0)
            if replace:
                passage = self.score_passage(owner, data)
                fingerprint = _passage_fingerprint(passage)
                if previous:
                    previous_fingerprint = previous.get("reference_fingerprint")
                    legacy_passage = folder / "score_passage.json"
                    if not previous_fingerprint and legacy_passage.is_file():
                        previous_fingerprint = _passage_fingerprint(self.artifacts.read_json(legacy_passage))
                    if previous_fingerprint == fingerprint:
                        return effective_report(previous, notes, offset)
                predictions = [dict(row, start_frame=row["start_frame"] or None) for row in notes]
                report = analyze_passage(passage, predictions, offset)
                if previous:
                    self.artifacts.write_json(folder / f"score_alignment_revision_{revision}.json", previous)
                report.update(revision=revision + 1, score_id=data["score_id"], reference_fingerprint=fingerprint)
            else:
                if previous is None:
                    raise ValueError("请先给这条演奏补传乐谱")
                report = change_review(previous, notes, offset, data)
            self.artifacts.write_json(path, report)
            return effective_report(report, notes, offset)

    def submit(self, owner, data):
        _, video = self.assets.asset(owner, data["video_id"])
        mode = data.get("mode", "fingering")
        if mode not in STAGES:
            raise ValueError("分析模式无效")
        offset = float(data.get("offset", 0))
        if video["kind"] != "video" or not math.isfinite(offset) or abs(offset) > 120:
            raise ValueError("输入类型或偏移无效")

        mirrored = data.get("mirrored") is True
        midi_id = reference_id = mapping = exercise = None
        passage = score_id = None
        warning = False
        if mode == "performance":
            if bool(data.get("score_id")) == bool(data.get("reference_id")):
                raise ValueError("请上传一份五线谱或参考 MIDI")
            passage = self.performance_reference(owner, data)
            if not 1 <= len(passage["notes"]) <= 20000 or any(not 21 <= row["pitch"] <= 108 for row in passage["notes"]):
                raise ValueError("请使用包含 1 至 20000 个钢琴音符的曲目")
            detected = data.get("keyboard")
            if not isinstance(detected, dict):
                raise ValueError("请先完成琴键定位")
            time = float(detected.get("time", -1))
            if not math.isfinite(time) or not 0 <= time < video["duration"]:
                raise ValueError("琴键定位时刻超出视频范围")
            mapping = pianocv_mapping(detected.get("source"), detected.get("corners"), detected.get("keys"),
                                      video["width"], video["height"], mirrored)
            mapping.update(calibration_time_seconds=time)
            reference_id, score_id = data.get("reference_id"), data.get("score_id")
        if mode == "fingering":
            midi_id, warning, mapping = self.prepare_fingering(owner, data, video, offset, mirrored)
            exercise = data.get("exercise") or None
            if exercise is not None and not supports_exercise(exercise):
                raise ValueError("知识图谱练习类型无效")
            if exercise:
                if not data.get("keyboard"):
                    raise ValueError("音阶动作分析需要逐键识别")
                mapping["exercise"] = exercise
            score_id = data.get("score_id")
            if score_id:
                if exercise:
                    raise ValueError("曲目选段需要使用普通演奏模式")
                passage = self.score_passage(owner, data)
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
            if passage:
                self.artifacts.write_json(folder / ("reference_passage.json" if mode == "performance" else "score_passage.json"), passage)
            job = dict(
                id=identifier, video_id=video["id"], midi_id=midi_id, mode=mode, offset=offset if midi_id else None,
                status="queued", stage="等待分析", duration_warning=warning, mirrored=mirrored,
                reference_id=reference_id, exercise=exercise, score_id=score_id, title=video.get("name") or "演奏视频",
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
        detected = data.get("keyboard")
        if detected is not None and not isinstance(detected, dict):
            raise ValueError("琴键识别数据无效")
        time = float(detected.get("time", -1) if detected is not None else data.get("calibration_time", 0))
        if not math.isfinite(time) or not 0 <= time < video["duration"]:
            raise ValueError("校准时间超出视频范围")
        if detected is None:
            mapping = keyboard_mapping(data["corners"], video["width"], video["height"], first, last, mirrored)
        else:
            try:
                mapping = pianocv_mapping(detected.get("source"), detected.get("corners"), detected.get("keys"),
                                          video["width"], video["height"], mirrored)
            except TypeError as error:
                raise ValueError("琴键识别坐标格式无效") from error
        mapping.update(calibration_time_seconds=time, calibration_frame_index=int(time * video["fps"]))
        return midi["id"], warning, mapping

    def execute(self, job):
        try:
            run_analysis(job, self.artifacts, self.root)
            current = self.artifacts.read_json(self.artifacts.folder(job["id"]) / "job.json")
            if current["status"] == "succeeded" and job["mode"] == "performance" and self.coach:
                self.coach.overview(self.artifacts.folder(job["id"]))
        finally:
            self.queue.release()
