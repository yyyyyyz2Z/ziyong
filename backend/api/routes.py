"""Translate the existing HTTP routes into calls to workspace services."""

from urllib.parse import parse_qs, unquote, urlsplit

import pymysql

from ..analysis.technique_graph import exercise_catalog
from ..services.accounts import SESSION_AGE
from ..services.assets import ASSET_FILES
from ..services.errors import AccessDenied, ConflictError, InvalidCredentials, UploadSizeError
from .http import HttpHandler


ASSET_CONTENT_TYPES = {"video": "video/mp4", "midi": "audio/midi"}
JOB_DOWNLOADS = {
    "fingering_predictions.csv", "analysis_summary.json", "aligned_landmarks.jsonl",
    "notes.csv", "transcribed.mid", "comparison.csv", "mapping.json", "score_alignment.json",
    "performance_graph.json", "aligned_reference.mid",
}


class WorkspaceHandler(HttpHandler):
    def __init__(self, *args, accounts, assets, jobs, coach, practice, static_root, secure_cookies):
        self.accounts = accounts
        self.assets = assets
        self.jobs = jobs
        self.coach = coach
        self.practice = practice
        self.static_root = static_root
        self.secure_cookies = secure_cookies
        super().__init__(*args)

    def do_GET(self):
        try:
            request = urlsplit(self.path)
            parts = request.path.strip("/").split("/")
            if parts[0] != "api":
                return self.serve_site(request.path)
            if parts == ["api", "health"]:
                return self.json({"status": "ok"})
            account = self.accounts.account(self.session_token())
            if parts == ["api", "auth", "me"]:
                return self.json({"account": account})
            if not account:
                return self.error("请先登录", 401)
            self.get_workspace(parts[1:], parse_qs(request.query), account)
        except AccessDenied as exc:
            self.error(str(exc), 403)
        except ConflictError as exc:
            self.error(str(exc), 409, **exc.details)
        except FileNotFoundError:
            self.error("资源不存在", 404)
        except (ValueError, KeyError) as exc:
            self.error(str(exc), 400)
        except pymysql.MySQLError:
            self.error("数据库暂不可用，请稍后再试", 503)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def get_workspace(self, parts, query, account):
        owner = account["id"]
        if parts == ["coach", "status"]:
            return self.json({"configured": self.coach.configured()})
        if parts == ["coach"]:
            return self.json(self.coach.messages(owner))
        if parts == ["library"]:
            return self.json(self.assets.library(owner))
        if parts == ["practice"]:
            return self.json(self.practice.list_items(owner))
        if parts == ["practice", "calendar"]:
            return self.json(self.practice.calendar(owner))
        if parts == ["practice", "drafts"]:
            return self.json(self.practice.drafts(owner))
        if parts == ["practice", "calendar.ics"]:
            return self.body(self.practice.export_calendar(owner), "text/calendar; charset=utf-8")
        if parts == ["admin", "coach"]:
            return self.json(self.coach.configuration(account))
        if parts == ["jobs"]:
            return self.json(self.jobs.history(owner))
        if parts == ["technique", "exercises"]:
            return self.json(exercise_catalog())
        if len(parts) >= 2 and parts[0] == "assets":
            return self.get_asset(owner, parts[1], parts[2] if len(parts) == 3 else "", query)
        if len(parts) >= 2 and parts[0] == "jobs":
            return self.get_job(owner, parts[1], parts[2] if len(parts) >= 3 else "")
        self.error("接口不存在", 404)

    def get_asset(self, owner, identifier, action, query):
        folder, metadata = self.assets.asset(owner, identifier)
        if action in ("frame", "calibration-hint"):
            suggest = action == "calibration-hint"
            seconds = query.get("time", ["0"])[0]
            result = self.assets.calibration_data(folder, metadata, seconds, suggest=suggest)
            if suggest:
                return self.json(result)
            return self.body(result, "image/jpeg")
        if action in ASSET_FILES:
            return self.media(folder / ASSET_FILES[action], ASSET_CONTENT_TYPES[action])
        self.json(metadata)

    def get_job(self, owner, identifier, action):
        folder, job = self.jobs.job(owner, identifier, finished=bool(action))
        if not action:
            return self.json(job)
        if action == "coach":
            return self.json(self.coach.messages(owner, job["id"]))
        if action == "overview":
            path = folder / "overview.json"
            return self.json(self.jobs.artifacts.read_json(path) if path.is_file() else {"status": "available"})
        if action == "result":
            result = self.jobs.result(folder)
            if job.get("mode") == "audio":
                result["replay"] = f'/api/assets/{job["video_id"]}/video'
            else:
                result["replay"] = f'/api/jobs/{job["id"]}/replay'
            return self.json(result)
        if action == "replay":
            return self.media(folder / "replay.mp4", "video/mp4")
        if action == "score_alignment.json":
            report = self.jobs.score_result(folder)
            return self.json(report) if report is not None else self.error("这条演奏没有曲目对齐结果", 404)
        if action in JOB_DOWNLOADS:
            path = folder / action
            if action == "fingering_predictions.csv" and not path.is_file():
                return self.error("骨架模式没有逐音符指法文件", 404)
            return self.media(path)
        self.error("接口不存在", 404)

    def serve_site(self, path):
        target = (self.static_root / path.lstrip("/")).resolve()
        if not target.is_relative_to(self.static_root):
            return self.error("禁止访问", 403)
        return self.media(target if target.is_file() else self.static_root / "index.html", private=False)

    def do_POST(self):
        try:
            request = urlsplit(self.path)
            parts = request.path.strip("/").split("/")
            origin = self.headers.get("Origin")
            if origin and urlsplit(origin).netloc.lower() != self.headers.get("Host", "").lower():
                return self.error("请求来源无效", 403)
            if parts in (["api", "auth", "register"], ["api", "auth", "login"]):
                register = parts[-1] == "register"
                account, token = self.accounts.start_session(self.read_json(), self.session_token(), register=register)
                return self.json({"account": account}, 201 if register else 200, self.session_cookie(token, SESSION_AGE))
            if parts == ["api", "auth", "logout"]:
                self.accounts.logout(self.session_token())
                return self.json({"ok": True}, cookie=self.session_cookie("", 0))
            account = self.accounts.account(self.session_token())
            if not account:
                return self.error("请先登录", 401)
            self.post_workspace(request, parts, account)
        except InvalidCredentials as exc:
            self.error(str(exc), 401)
        except AccessDenied as exc:
            self.error(str(exc), 403)
        except ConflictError as exc:
            self.error(str(exc), 409, **exc.details)
        except UploadSizeError as exc:
            self.error(str(exc), 413)
        except RuntimeError as exc:
            self.error(str(exc), 502)
        except FileNotFoundError:
            self.error("资源不存在", 404)
        except pymysql.MySQLError:
            self.error("数据库暂不可用，请稍后再试", 503)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            self.error(str(exc), 400)

    def post_workspace(self, request, parts, account):
        owner = account["id"]
        if parts == ["api", "admin", "coach"]:
            if account["role"] != "admin":
                raise AccessDenied("只有管理员可以修改 AI 配置")
            return self.json(self.coach.update_configuration(account, self.read_json()))
        if parts == ["api", "practice"]:
            return self.json(self.practice.add(owner, self.read_json()), 201)
        if parts == ["api", "practice", "schedule"]:
            return self.json(self.practice.schedule(owner, self.read_json()))
        if len(parts) == 5 and parts[:3] == ["api", "practice", "drafts"] and parts[4] == "confirm":
            return self.json(self.practice.confirm(owner, parts[3], self.read_json()))
        if len(parts) == 4 and parts[:2] == ["api", "practice"] and parts[3] == "check":
            return self.json(self.practice.check(owner, parts[2], self.read_json()))
        if len(parts) == 4 and parts[:2] == ["api", "practice"] and parts[3] in ("complete", "edit", "remove"):
            return self.json(self.practice.change(owner, parts[2], parts[3], self.read_json()))
        if parts == ["api", "coach"]:
            return self.json(self.coach.add_message(owner, self.read_json()), 201)
        if len(parts) == 4 and parts[:2] == ["api", "jobs"] and parts[3] == "overview":
            folder, job = self.jobs.job(owner, parts[2], finished=True)
            return self.json(self.coach.overview(folder))
        if len(parts) == 4 and parts[:2] == ["api", "jobs"] and parts[3] in ("score-reference", "score-review"):
            return self.json(self.jobs.edit_score(owner, parts[2], self.read_json(),
                                                  replace=parts[3] == "score-reference"))
        if len(parts) == 4 and parts[:2] == ["api", "jobs"] and parts[3] in ("coach", "practice-plan"):
            folder, job = self.jobs.job(owner, parts[2], finished=True)
            data = self.read_json()
            if parts[3] == "practice-plan":
                if data.get("scope") == "full" and data.get("save") is True:
                    return self.json(self.practice.from_overview(owner, job["id"], folder, self.coach))
                if data.get("scope") == "full":
                    return self.json(self.practice.suggest(owner, job["id"], folder, self.coach))
                return self.json(self.coach.plan(data, folder))
            return self.json(self.coach.add_message(owner, data, job["id"], folder), 201)
        if request.path in ("/api/upload/video", "/api/upload/midi", "/api/upload/score"):
            size = int(self.headers.get("Content-Length", "0"))
            filename = unquote(self.headers.get("X-File-Name", ""))
            library = parse_qs(request.query).get("library") == ["1"]
            return self.json(self.assets.upload(owner, parts[-1], filename, self.rfile, size, library=library), 201)
        if request.path == "/api/jobs":
            return self.json(self.jobs.submit(owner, self.read_json()), 202)
        self.error("接口不存在", 404)
