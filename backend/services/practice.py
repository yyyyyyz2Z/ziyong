from datetime import datetime, timezone
from uuid import uuid4

from .coach import make_evidence


def practice_text(data):
    title = str(data.get("title", "")).strip()
    detail = str(data.get("detail", "")).strip()
    if not title or len(title) > 120 or len(detail) > 1200:
        raise ValueError("练习标题或说明超出长度限制")
    return title, detail


class PracticeService:
    def __init__(self, database, artifacts):
        self.database = database
        self.artifacts = artifacts

    def list_items(self, owner):
        return self.database.practice(owner)

    def add(self, owner, data):
        title, detail = practice_text(data)
        job_id = data.get("job_id") or ""
        start = end = None
        if job_id:
            folder = self.artifacts.owned_folder(owner, job_id)
            evidence = make_evidence(self.artifacts, folder, data["start"], data["end"], [])
            start, end = evidence["start"], evidence["end"]
        return self.database.add_practice(dict(
            id=uuid4().hex, owner_id=owner, title=title, detail=detail, job_id=job_id,
            start_seconds=start, end_seconds=end, created_at=datetime.now(timezone.utc).isoformat(),
        ))

    def change(self, owner, identifier, action, data):
        if action == "edit":
            values = practice_text(data)
        else:
            completed = datetime.now(timezone.utc).isoformat() if data.get("completed") is True else None
            values = (completed,)
        return self.database.change_practice(owner, identifier, action, values)
