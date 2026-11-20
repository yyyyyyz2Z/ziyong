from datetime import datetime, timezone

import cv2
import pretty_midi

from ..analysis.calibration import read_frame, suggest_corners
from .errors import UploadSizeError


ASSET_FILES = {"video": "input.mp4", "midi": "input.mid"}


class AssetService:
    def __init__(self, artifacts, database):
        self.artifacts = artifacts
        self.database = database

    def library(self, owner):
        return self.database.library(owner)

    def asset(self, owner, identifier):
        folder = self.artifacts.owned_folder(owner, identifier)
        return folder, self.artifacts.read_json(folder / "asset.json")

    def upload(self, owner, kind, filename, stream, size, *, library):
        if not 0 < size <= 512 * 1024 * 1024:
            raise UploadSizeError("文件大小须为 1 字节至 512 MB")
        identifier, folder = self.artifacts.create_folder()
        path = folder / ASSET_FILES[kind]
        self.artifacts.write_upload(path, stream, size)
        title = filename.replace("\\", "/").rsplit("/", 1)[-1]
        metadata = dict(
            id=identifier, kind=kind, name=title[:240], created_at=datetime.now(timezone.utc).isoformat(),
            library=kind == "midi" and library,
        )
        metadata.update(video_metadata(path) if kind == "video" else midi_metadata(path))
        self.artifacts.write_json(folder / "asset.json", metadata)
        self.artifacts.register(owner, identifier, "asset", metadata if metadata["library"] else None)
        return metadata

    @staticmethod
    def calibration_data(folder, metadata, seconds, *, suggest):
        if metadata["kind"] != "video":
            raise ValueError("该资源不是视频")
        frame = read_frame(folder / ASSET_FILES["video"], metadata, seconds)
        if suggest:
            return {"corners": suggest_corners(frame)}
        ok, encoded = cv2.imencode(".jpg", frame)
        if not ok:
            raise ValueError("校准画面编码失败")
        return encoded.tobytes()


def video_metadata(path):
    capture = cv2.VideoCapture(str(path))
    try:
        ok, frame = capture.read()
        fps = capture.get(cv2.CAP_PROP_FPS)
        if not ok or fps <= 0:
            raise ValueError("视频无法解码")
        metadata = dict(width=frame.shape[1], height=frame.shape[0], duration=capture.get(cv2.CAP_PROP_FRAME_COUNT) / fps, fps=fps)
    finally:
        capture.release()
    cv2.imwrite(str(path.with_name("frame.jpg")), frame)
    return metadata


def midi_metadata(path):
    midi = pretty_midi.PrettyMIDI(str(path))
    notes = [note for instrument in midi.instruments if not instrument.is_drum for note in instrument.notes]
    if not notes:
        raise ValueError("MIDI 没有钢琴音符")
    return dict(
        duration=midi.get_end_time(), notes=len(notes),
        minimum=min(note.pitch for note in notes), maximum=max(note.pitch for note in notes),
    )
