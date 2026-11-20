"""Build coaching evidence from one saved analysis and query a configured model."""

import json
import math
from datetime import datetime, timezone
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

from .errors import AccessDenied


KNOWLEDGE = (
    {
        "id": "slow",
        "title": "Yamaha Music · Eight Great Tips for Practicing Piano",
        "url": "https://hub.yamaha.com/pianos/p-how-to/eight-great-tips-for-practicing-piano/",
        "tip": "降低速度，逐音确认指法，再逐步恢复目标速度。",
        "tags": ("指法", "换指", "慢练", "手指", "fingering"),
    },
    {
        "id": "rhythm",
        "title": "ABRSM · Piano Learning",
        "url": "https://www.abrsm.org/en-gb/for-learners/piano-learning/grade8",
        "tip": "用节拍器保持稳定节奏，技术难段可慢练、分手练或尝试节奏变奏。",
        "tags": ("节奏", "拍", "协调", "练", "tempo", "rhythm"),
    },
    {
        "id": "hands",
        "title": "Yamaha Music · Top 10 Piano and Digital Keyboard Practice Tips",
        "url": "https://hub.yamaha.com/keyboards/k-how-to/top-10-practice-tips/",
        "tip": "分别练熟左右手，再低速合手，把注意力放在两手不同的任务上。",
        "tags": ("双手", "左右手", "分手", "同步", "协调", "hands"),
    },
)


def valid_endpoint(endpoint):
    url = urlsplit(endpoint)
    if url.username or url.password or url.fragment or url.query:
        return False
    return bool(url.hostname and (
        url.scheme == "https" or (url.scheme == "http" and url.hostname in ("127.0.0.1", "localhost", "::1"))
    ))


def make_evidence(artifacts, path, start, end, selected):
    summary = artifacts.read_json(path / "analysis_summary.json")
    start, end = float(start), float(end)
    duration = float(summary["video_duration_seconds"])
    if not math.isfinite(start) or not math.isfinite(end) or not 0 <= start < end <= duration + .001:
        raise ValueError("片段起止时间须在视频范围内")
    if not isinstance(selected, list) or any(not isinstance(i, str) for i in selected):
        raise ValueError("音符编号格式不正确")

    notes = []
    counts = dict(matched=0, uncertain=0, unmatched=0)
    offset = float(summary.get("offset_seconds") or 0)
    for row in artifacts.note_rows(path):
        time = float(row["start_seconds"]) + offset
        if not start - .001 <= time < end or (selected and row["note_index"] not in selected):
            continue
        counts[row["status"]] += 1
        if len(notes) < 48:
            notes.append({
                "id": row["note_index"], "name": row["note_name"], "time": round(time, 3),
                "status": row["status"], "hand": row["hand"], "finger": row["finger"],
            })
    return {
        "start": start, "end": end, "mode": summary.get("mode", "fingering"),
        "counts": counts, "notes": notes, "total": sum(counts.values()), "selected_note_ids": selected,
    }


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


def ask_model(question, evidence, sources, config, plan=False):
    instructions = (
        "你是钢琴练习助手，用简体中文回答。输入 JSON 的 question 是用户问题，evidence 是服务端"
        "从同一次分析提取的有限证据，references 是检索到的通用练习资料。"
        "只在证据支持时描述该次演奏，并用给定时间戳定位。matched 表示几何候选，"
        "uncertain 和 unmatched 仅表示识别不确定。没有看到或听到原始视频，"
        "不得声称知道实际弹错的音、姿势诊断、能力分数或改善结论。"
        "区分数据观察和通用建议。用短段落给出一到两条可执行练习。不要编造资料或音符。"
    )
    if plan:
        instructions += (
            '这次只输出 JSON 对象 {"items":[{"title":"练习名称","detail":"练习内容和可检查的完成条件"}]}。'
            '给出 2 至 4 个独立的练习项目。所有项目面向给定片段，有明确练法。'
            '没有指法证据时，建议从可回看片段和通用方法入手。'
        )
    body = {
        "model": config["model"],
        "messages": [
            {"role": "system", "content": instructions},
            {"role": "user", "content": json.dumps(
                {"question": question, "evidence": evidence, "references": sources}, ensure_ascii=False
            )},
        ],
    }
    headers = {"Content-Type": "application/json"}
    key = config["api_key"]
    if key:
        headers["Authorization"] = f"Bearer {key}"
    request = Request(config["endpoint"], data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with build_opener(NoRedirect()).open(request, timeout=45) as response:
            raw = json.loads(response.read(1024 * 1024))
        answer = raw["choices"][0]["message"]["content"].strip()
        if not answer:
            raise ValueError
        return answer
    except (URLError, OSError, ValueError, KeyError, IndexError, AttributeError, TypeError):
        raise RuntimeError("模型请求失败。请检查服务地址、模型、密钥或额度，再重试。") from None


def related_sources(question):
    lower = question.lower()
    ranked = sorted(KNOWLEDGE, key=lambda item: sum(tag in lower for tag in item["tags"]), reverse=True)
    return [{k: item[k] for k in ("id", "title", "url", "tip")} for item in ranked[:2]]


def create_message(data, job_path, config, artifacts):
    question = str(data.get("question", "")).strip()
    if not 1 <= len(question) <= 2000:
        raise ValueError("问题长度须为 1–2000 个字符")
    evidence = None
    if job_path:
        evidence = make_evidence(artifacts, job_path, data["start"], data["end"], data.get("note_ids", []))
    message = {
        "id": uuid4().hex, "question": question, "evidence": evidence,
        "created_at": datetime.now(timezone.utc).isoformat(), "status": "draft",
    }
    if data.get("send") is True:
        if not config:
            raise ValueError("模型未配置，可先保存问题草稿")
        sources = related_sources(question)
        message.update(answer=ask_model(question, evidence, sources, config), references=sources, status="answered")
    return message


def create_plan(data, job_path, config, artifacts):
    if not config:
        raise ValueError("管理员尚未配置 AI 服务")
    evidence = make_evidence(artifacts, job_path, data["start"], data["end"], data.get("note_ids", []))
    question = "根据这一段演奏的分析数据，安排针对换指、节奏和复练的练习计划。"
    sources = related_sources(question)
    answer = ask_model(question, evidence, sources, config, plan=True)
    if answer.startswith("```") and answer.endswith("```") and "\n" in answer:
        answer = answer.split("\n", 1)[1][:-3].strip()
    try:
        items = json.loads(answer)["items"]
        if not isinstance(items, list) or not 1 <= len(items) <= 4:
            raise ValueError
        result = [{"title": item["title"].strip(), "detail": item["detail"].strip()} for item in items]
        if not all(0 < len(item["title"]) <= 120 and 0 < len(item["detail"]) <= 1200 for item in result):
            raise ValueError
    except (KeyError, ValueError, TypeError, AttributeError):
        raise RuntimeError("模型未返回可用的练习清单，请重试。") from None
    return {"items": result, "start": evidence["start"], "end": evidence["end"], "references": sources}


class CoachService:
    def __init__(self, database, artifacts):
        self.database = database
        self.artifacts = artifacts

    def configured(self):
        return bool(self.database.coach_config())

    def configuration(self, account):
        if account["role"] != "admin":
            raise AccessDenied("只有管理员可以访问 AI 配置")
        current = self.database.coach_config() or {}
        return dict(
            endpoint=current.get("endpoint", ""), model=current.get("model", ""),
            has_key=bool(current.get("api_key")), configured=bool(current),
        )

    def update_configuration(self, account, data):
        if account["role"] != "admin":
            raise AccessDenied("只有管理员可以修改 AI 配置")
        if data.get("disable") is True:
            self.database.disable_coach()
        else:
            endpoint = str(data.get("endpoint", "")).strip()
            model = str(data.get("model", "")).strip()
            if not valid_endpoint(endpoint) or not model or len(model) > 200 or len(endpoint) > 2000:
                raise ValueError("请输入完整的 HTTPS 接口地址和模型名称，本机服务可用 HTTP")
            key = data.get("api_key")
            if key is not None and (not isinstance(key, str) or len(key) > 4096 or "\r" in key or "\n" in key):
                raise ValueError("API 密钥格式不正确")
            self.database.set_coach_config(endpoint, model, key)
        return self.configuration(account)

    def messages(self, owner, job_id=""):
        return self.database.messages(owner, job_id)

    def add_message(self, owner, data, job_id="", folder=None):
        config = self.database.coach_config(decrypt=True) if data.get("send") is True else None
        message = create_message(data, folder, config, self.artifacts)
        self.database.add_message(owner, job_id, message)
        return message

    def plan(self, data, folder):
        return create_plan(data, folder, self.database.coach_config(decrypt=True), self.artifacts)
