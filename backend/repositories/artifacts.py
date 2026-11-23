"""Read and write the existing on-disk formats for uploads and analysis jobs."""

import csv
import json
import os
import re
from uuid import uuid4


RESOURCE_ID = re.compile(r"[a-f0-9]{32}")


class ArtifactStore:
    def __init__(self, root, database):
        self.root = root
        self.database = database
        self.root.mkdir(parents=True, exist_ok=True)

    def create_folder(self):
        identifier = uuid4().hex
        path = self.root / identifier
        path.mkdir()
        return identifier, path

    def folder(self, identifier):
        if not RESOURCE_ID.fullmatch(identifier):
            raise ValueError("无效资源编号")
        path = self.root / identifier
        if not path.is_dir():
            raise ValueError("资源不存在")
        return path

    def owned_folder(self, owner, identifier):
        if not self.database.owns(owner, identifier):
            raise FileNotFoundError("资源不存在")
        return self.folder(identifier)

    def register(self, owner, identifier, kind, library=None):
        self.database.attach_resource(identifier, owner, kind, library)

    @staticmethod
    def read_json(path):
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def write_json(path, data):
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)

    @staticmethod
    def write_upload(path, stream, size):
        with path.open("wb") as file:
            remaining = size
            while remaining:
                block = stream.read(min(1024 * 1024, remaining))
                if not block:
                    raise ValueError("上传中断")
                file.write(block)
                remaining -= len(block)

    @staticmethod
    def note_rows(folder):
        path = folder / "fingering_predictions.csv"
        if path.is_file():
            with path.open(encoding="utf-8-sig") as file:
                yield from csv.DictReader(file)

    def jobs(self, owner):
        paths = [self.root / identifier / "job.json" for identifier in self.database.resources(owner, "job")]
        files = (path for path in paths if path.is_file())
        return [self.read_json(path) for path in sorted(files, key=lambda path: path.stat().st_mtime, reverse=True)]

    def mark_interrupted_jobs(self):
        for path in self.root.glob("*/job.json"):
            job = self.read_json(path)
            if job["status"] in ("queued", "running"):
                job.update(status="failed", error="服务曾中断，请重新提交")
                self.write_json(path, job)
        for path in self.root.glob("*/overview.json"):
            if self.read_json(path).get("status") == "pending":
                self.write_json(path, {"status": "available"})

    def import_legacy(self, owner):
        resources = []
        for path in self.root.iterdir():
            if path.is_dir() and RESOURCE_ID.fullmatch(path.name):
                if (path / "job.json").is_file():
                    resources.append((path.name, "job"))
                elif (path / "asset.json").is_file():
                    resources.append((path.name, "asset"))
        self.database.import_legacy_resources(resources, owner)
