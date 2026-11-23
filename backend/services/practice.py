from datetime import date, datetime, timezone
import hashlib
from uuid import uuid4

from .coach import make_evidence
from .practice_calendar import calendar_file


def practice_text(data):
    title = str(data.get("title", "")).strip()
    detail = str(data.get("detail", "")).strip()
    if not title or len(title) > 120 or len(detail) > 1200:
        raise ValueError("练习标题或说明超出长度限制")
    return title, detail


def practice_date(value):
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError
        return value
    except (ValueError, TypeError):
        raise ValueError("请选择有效的练习日期") from None


def task_weekdays(data):
    days = data.get("weekdays", [])
    if (not isinstance(days, list) or len(days) > 7
            or any(type(day) is not int or not 0 <= day <= 6 for day in days) or len(set(days)) != len(days)):
        raise ValueError("练习星期须为周一至周日")
    return sorted(days)


class PracticeService:
    def __init__(self, database, artifacts):
        self.database = database
        self.artifacts = artifacts

    def list_items(self, owner):
        return self.database.practice(owner)

    def calendar(self, owner):
        return self.database.practice_calendar(owner)

    def export_calendar(self, owner):
        return calendar_file(owner, self.database.practice_calendar(owner)["schedule"], self.database.practice(owner))

    def schedule(self, owner, data):
        weekdays = data.get("weekdays")
        if (not isinstance(weekdays, list) or not 1 <= len(weekdays) <= 7
                or any(type(day) is not int or not 0 <= day <= 6 for day in weekdays)
                or len(set(weekdays)) != len(weekdays)):
            raise ValueError("请选择每周 1 至 7 个练习日")
        first = practice_date(data.get("start_date"))
        last = practice_date(data["end_date"]) if data.get("end_date") else None
        if last is not None and last < first:
            raise ValueError("截止日期须在起始日期当天或之后")
        return self.database.save_practice_schedule(owner, sorted(weekdays), first, last)

    def drafts(self, owner):
        return self.database.practice_drafts(owner)

    def suggest(self, owner, job_id, folder, coach):
        plan = coach.plan({"scope": "full"}, folder)
        overview = self.artifacts.read_json(folder / "overview.json")
        return self.database.save_practice_draft(dict(id=uuid4().hex, owner_id=owner, job_id=job_id,
            source_hash=hashlib.sha256(overview["answer"].encode()).hexdigest(), items=plan["items"],
            start_seconds=plan["start"], end_seconds=plan["end"], created_at=datetime.now(timezone.utc).isoformat()))

    def confirm(self, owner, identifier, data):
        items = data.get("items")
        if not isinstance(items, list) or not 1 <= len(items) <= 4:
            raise ValueError("请选择 1 至 4 个练习项目")
        selected = []
        for item in items:
            title, detail = practice_text(item)
            selected.append(dict(title=title, detail=detail, weekdays=task_weekdays(item)))
        return self.database.confirm_practice_draft(owner, identifier, selected)

    def check(self, owner, identifier, data):
        day = practice_date(data.get("date"))
        completed = datetime.now(timezone.utc).isoformat() if data.get("completed") is True else None
        return self.database.check_practice(owner, identifier, day, completed)

    def from_overview(self, owner, job_id, folder, coach):
        overview = self.artifacts.read_json(folder / "overview.json") if (folder / "overview.json").is_file() else {}
        if overview.get("status") != "answered":
            raise ValueError("请先生成全曲评价，再创建练习计划")
        source_hash = hashlib.sha256(overview["answer"].encode()).hexdigest()
        identifiers = self.database.practice_batch(owner, job_id, source_hash)
        if identifiers is None:
            plan = coach.plan({"scope": "full"}, folder)
            tasks = []
            for item in plan["items"]:
                title, detail = practice_text(item)
                tasks.append(dict(id=uuid4().hex, owner_id=owner, title=title, detail=detail, job_id=job_id,
                                  start_seconds=plan["start"], end_seconds=plan["end"],
                                  created_at=datetime.now(timezone.utc).isoformat()))
            identifiers = self.database.add_practice_batch(owner, job_id, source_hash, tasks)
        selected = set(identifiers)
        return {"items": [task for task in self.database.practice(owner) if task["id"] in selected], "scope": "full"}

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
            weekdays=task_weekdays(data),
        ))

    def change(self, owner, identifier, action, data):
        if action == "edit":
            values = (*practice_text(data), task_weekdays(data) if "weekdays" in data else None)
        else:
            completed = datetime.now(timezone.utc).isoformat() if data.get("completed") is True else None
            values = (completed,)
        return self.database.change_practice(owner, identifier, action, values)
