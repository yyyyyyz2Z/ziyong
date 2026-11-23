"""Build coaching evidence from one saved analysis and query a configured model."""

import json
import math
from datetime import datetime, timezone
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4
from threading import Lock

from ..analysis.technique_graph import segment_evidence
from ..analysis.score_review import score_guidance, score_segment
from ..analysis.score_revisions import effective_report
from ..analysis.performance_graph import graph_segment
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
    evidence = {
        "start": start, "end": end, "mode": summary.get("mode", "fingering"),
        "counts": counts, "notes": notes, "total": sum(counts.values()), "selected_note_ids": selected,
    }
    report = summary.get("technique")
    graph = segment_evidence(report, start, end, selected) if report else None
    if graph:
        evidence["technique"], evidence["technique_references"] = graph
    alignment = path / "score_alignment.json"
    if alignment.is_file():
        report = effective_report(artifacts.read_json(alignment), artifacts.note_rows(path), offset)
        segment = score_segment(report, start, end, selected)
        if segment:
            rules, references = score_guidance(segment)
            evidence["score_alignment"] = dict(segment, rules=rules)
            if references:
                evidence["score_references"] = references
    graph = path / "performance_graph.json"
    if graph.is_file():
        document = artifacts.read_json(graph)
        evidence["performance"] = graph_segment(document, start, end, selected)
        evidence["score_references"] = document.get("references", [])
    return evidence


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


def ask_model(question, evidence, sources, config, plan=False):
    instructions = (
        "你是钢琴练习助手，用简体中文回答。输入 JSON 的 question 是用户问题，evidence 是服务端"
        "从同一次分析提取的有限证据，references 是检索到的通用练习资料。"
        "用自然、亲切且具体的钢琴教师语气回答，先回应用户关心的音乐表现，再给练法。"
        "优先使用有依据的观察，并用给定时间戳定位。matched 表示几何候选，"
        "uncertain 和 unmatched 是内部识别状态，不代表演奏问题。"
        "按证据区分自动候选和人工已确认的音高差异。姿势诊断、能力分数和改善结论需要另外的数据。"
        "区分数据观察和通用建议。用短段落给出一到两条可执行练习。不要编造资料或音符。"
        "有 technique 时，结合片段内 MIDI 起音、琴键位置、手部观测和图谱规则回答。"
        "使用证据给出的音符、手别与参考指法。间隔比例以同遍其他等时值间隔的中位数为基准。"
        "角度是图像中落键指的二维投影，右手下行 1→3 应描述中指。"
        "准备提前量是待复核的估计。只在给出数值时引用，不由遮挡、单次观测或未校准阈值推断技术缺陷。"
        "阐述研究背景时按相应图谱规则的 reference_ids 引用资料编号，说明其适用范围。"
        "把参考指法差异写成回看线索。多遍统计是观察值，只有给定相同目标速度时才论及同速复练。"
        "有 score_alignment 时，用行内小节号、拍点、预计或实际视频时间回答。"
        "注意区分同音高匹配、疑似漏音、疑似多弹及疑似替换音。review 表示需要核对的音符，"
        "pitch_confirmed、missing_confirmed、extra_confirmed 是人工确认。manual_review 标记 misaligned、"
        "variant 或 unclear 时，说明复核原因并避免将这个位置描述为已确认的演奏错误。"
        "missing_candidate 的时间仅是由对齐估算的回看位置。timing_delta_ms 是相对于局部速度映射的偏差。"
        "参考指法可来自谱面或人工标注，多个 reference_fingers 是可接受的备选。"
        "缺少参考指法时，围绕手指衔接和分组练习给出建议。"
        "对用户避免机械地说‘数据不确定’‘没有数据’‘无法判断’‘证据不足’，"
        "可自然表述为‘这一处可以重点听相邻两音是否连贯，再用慢速连接练习体会’。"
        "信息有限时把结论调整为练习建议或回看提示，不能补造观察、数值和技术缺陷。"
        "有 performance 时，这是整段视频中谱面音符、音轨起音、手指关键点和琴键关联构成的知识图谱。"
        "summary 聚合了选择范围内的全部音符，events 只是均匀采样。"
        "same_piece_complete 表示用户按同一曲目完整弹奏的前提，score_linked 只表示谱面关联。"
        "timing_source=audio 的音符才有实测起音指标，score_projection 供定位。"
        "不能从上传的参考 MIDI 推断真实演奏力度、节奏稳定性或正确率。"
        "全曲评价覆盖开头、中段和结尾，给出整体表现、优先关注的位置和两到三条练法。"
        "只在对应实测观察支持时评价节奏和指法表现，避免虚构听感、表情、踏板或能力分数。"
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
                {"question": question, "evidence": {k: v for k, v in evidence.items()
                                                     if k not in ("technique_references", "score_references")}
                 if evidence else None, "references": sources}, ensure_ascii=False
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


def related_sources(question, evidence=None):
    lower = question.lower()
    ranked = sorted(KNOWLEDGE, key=lambda item: sum(tag in lower for tag in item["tags"]), reverse=True)
    general = [{k: item[k] for k in ("id", "title", "url", "tip")} for item in ranked[:2]]
    combined = (evidence or {}).get("technique_references", []) + (evidence or {}).get("score_references", []) + general
    return list({item["id"]: item for item in combined}.values())


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
        sources = related_sources(question, evidence)
        message.update(answer=ask_model(question, evidence, sources, config), references=sources, status="answered")
    return message


def create_plan(data, job_path, config, artifacts):
    if not config:
        raise ValueError("管理员尚未配置 AI 服务")
    if data.get("scope") == "full":
        overview_path = job_path / "overview.json"
        overview = artifacts.read_json(overview_path) if overview_path.is_file() else {}
        if overview.get("status") != "answered":
            raise ValueError("请先生成全曲评价，再创建练习计划")
        summary = artifacts.read_json(job_path / "analysis_summary.json")
        evidence = make_evidence(artifacts, job_path, 0, summary["video_duration_seconds"], [])
        evidence["overall_evaluation"] = overview["answer"]
        question = "根据 overall_evaluation 中的全曲评价，按优先级安排每次练习的项目，给出练法、重复次数和可检查的完成目标。"
    else:
        evidence = make_evidence(artifacts, job_path, data["start"], data["end"], data.get("note_ids", []))
        question = "根据这一段演奏的分析数据，安排针对换指、节奏和复练的练习计划。"
    sources = related_sources(question, evidence)
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
        self.overview_lock = Lock()

    def overview(self, folder):
        with self.overview_lock:
            path = folder / "overview.json"
            current = self.artifacts.read_json(path) if path.is_file() else {}
            if current.get("status") == "answered":
                return current
            config = self.database.coach_config(decrypt=True)
            if not config:
                result = dict(status="configuration_required")
            else:
                self.artifacts.write_json(path, {"status": "pending"})
                try:
                    summary = self.artifacts.read_json(folder / "analysis_summary.json")
                    evidence = make_evidence(self.artifacts, folder, 0, summary["video_duration_seconds"], [])
                    question = "请先给出这次完整演奏的全曲评价，兼顾开头、中段和结尾，再给出优先练习的片段与具体方法。"
                    sources = related_sources(question, evidence)
                    result = dict(status="answered", answer=ask_model(question, evidence, sources, config),
                                  references=sources, created_at=datetime.now(timezone.utc).isoformat())
                except Exception:
                    result = dict(status="failed")
            self.artifacts.write_json(path, result)
            return result

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
