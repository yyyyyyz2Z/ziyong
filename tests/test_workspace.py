"""Exercise the local workspace over HTTP, including admin and model boundaries."""

import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookiejar import CookieJar
from pathlib import Path
from uuid import uuid4
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener

import pretty_midi
import pymysql
from cryptography.fernet import Fernet


ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "integration-admin"
TOKEN = "integration-model-key"


class ModelStub(BaseHTTPRequestHandler):
    received = None

    def do_POST(self):
        ModelStub.received = {
            "token": self.headers.get("Authorization"),
            "body": json.loads(self.rfile.read(int(self.headers["Content-Length"]))),
        }
        system_message = self.received["body"]["messages"][0]["content"]
        answer = "这是本地接口验证用响应。"
        if "JSON 对象" in system_message:
            answer = json.dumps({"items": [{"title": "慢速练习", "detail": "以慢速重复三次。"},
                                           {"title": "节奏复练", "detail": "用节拍器完整回放一次。"}]})
        response = json.dumps({"choices": [{"message": {"content": answer}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, *_args):
        pass


class WorkspaceIntegration(unittest.TestCase):
    def setUp(self):
        if not os.environ.get("PIANO_TEST_DB_PORT"):
            self.skipTest("Set PIANO_TEST_DB_PORT for a disposable local MySQL instance")
        self.db_options = {
            "host": "127.0.0.1", "port": int(os.environ["PIANO_TEST_DB_PORT"]),
            "user": os.environ.get("PIANO_TEST_DB_USER", "root"),
            "password": os.environ.get("PIANO_TEST_DB_PASSWORD", ""),
        }
        self.db_name = "piano_test_" + uuid4().hex
        self.database_command("CREATE DATABASE")
        self.addCleanup(self.database_command, "DROP DATABASE")
        self.secret = Fernet.generate_key().decode()
        self.client = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        with socket.socket() as reserve:
            reserve.bind(("127.0.0.1", 0))
            self.port = reserve.getsockname()[1]
        self.model = ThreadingHTTPServer(("127.0.0.1", 0), ModelStub)
        self.addCleanup(self.model.server_close)
        threading.Thread(target=self.model.serve_forever, daemon=True).start()
        self.addCleanup(self.model.shutdown)
        self.process = None
        self.addCleanup(self.stop_api)
        self.start_api()

    def database_command(self, command):
        connection = pymysql.connect(**self.db_options)
        try:
            with connection.cursor() as cursor:
                cursor.execute(f"{command} `{self.db_name}`")
        finally:
            connection.close()

    def start_api(self):
        env = {**os.environ, "PIANO_STORE": str(self.root / "store"), "PIANO_PORT": str(self.port),
               "PIANO_ADMIN_USERNAME": "admin", "PIANO_ADMIN_PASSWORD": PASSWORD,
               "PIANO_DB_HOST": self.db_options["host"], "PIANO_DB_PORT": str(self.db_options["port"]),
               "PIANO_DB_USER": self.db_options["user"], "PIANO_DB_PASSWORD": self.db_options["password"],
               "PIANO_DB_NAME": self.db_name, "PIANO_SECRET_KEY": self.secret,
               "PIANO_COOKIE_SECURE": "0", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1"}
        log_path = self.root / "api.log"
        with log_path.open("ab") as log:
            self.process = subprocess.Popen([sys.executable, str(ROOT / "backend" / "api_server.py")],
                                            cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        for _ in range(60):
            if self.process.poll() is not None:
                break
            try:
                if self.request("/health")[0] == 200:
                    return
            except URLError:
                time.sleep(.2)
        self.fail("API did not start:\n" + log_path.read_text(encoding="utf-8", errors="replace")[-3500:])

    def stop_api(self):
        if self.process:
            self.process.terminate()
            self.process.wait(timeout=10)
            self.process = None

    def request(self, path, data=None, headers=None, client=None):
        headers = dict(headers or {})
        if isinstance(data, dict):
            data = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
        request = Request(f"http://127.0.0.1:{self.port}/api" + path, data=data, headers=headers)
        try:
            response = (client or self.client).open(request, timeout=55)
        except HTTPError as error:
            response = error
        with response:
            content = response.read()
            if response.headers.get_content_type() == "application/json":
                content = json.loads(content)
            return response.code, content

    def wait_job(self, job):
        path = "/jobs/" + job["id"]
        for _ in range(240):
            _, current = self.request(path)
            if current["status"] == "failed":
                self.fail(current["error"])
            if current["status"] == "succeeded":
                return path, self.request(path + "/result")[1]
            time.sleep(.5)
        self.fail(f"Job timed out: {job['id']}")

    def test_admin_analysis_and_persistence(self):
        admin = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))
        model_config = {"endpoint": f"http://127.0.0.1:{self.model.server_port}/v1/chat/completions",
                        "model": "workspace-test", "api_key": TOKEN}
        self.assertEqual(self.request("/admin/coach")[0], 401)
        self.assertEqual(self.request("/auth/register", {"username": "admin", "password": PASSWORD})[0],400)
        status, registered = self.request("/auth/register", {"username":"student", "password":PASSWORD,"role":"admin"})
        self.assertEqual(status,201)
        self.assertEqual(registered["account"]["role"],"user")
        self.assertEqual(self.request("/auth/login", {"username":"admin", "password":PASSWORD}, client=admin)[0],200)
        self.assertEqual(self.request("/admin/coach", model_config)[0], 403)
        self.assertEqual(self.request("/admin/coach")[0], 403)
        self.assertEqual(self.request("/coach/status")[1], {"configured": False})
        self.assertEqual(self.request("/coach", {"question": "草稿", "send": False})[0], 201)
        self.assertEqual(self.request("/coach", {"question": "未配置", "send": True})[0], 400)
        status, saved = self.request("/admin/coach", model_config, client=admin)
        self.assertEqual(status, 200)
        self.assertEqual(saved, {"endpoint": model_config["endpoint"], "model": model_config["model"], "has_key": True, "configured": True})
        self.assertEqual(self.request("/coach/status")[1], {"configured": True})

        midi_path = self.root / "take.mid"
        midi = pretty_midi.PrettyMIDI()
        instrument = pretty_midi.Instrument(0)
        instrument.notes.append(pretty_midi.Note(80, 60, .4, 1.0))
        midi.instruments.append(instrument)
        midi.write(str(midi_path))
        status, imported = self.request("/upload/midi?library=1", midi_path.read_bytes(), {"X-File-Name": quote("练习.mid")})
        self.assertEqual(status, 201)
        self.assertEqual(self.request("/library")[1][0]["name"], "练习.mid")
        self.assertEqual(self.request("/assets/" + imported["id"] + "/midi")[1], midi_path.read_bytes())

        video_path = self.root / "take.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=white:s=320x240:r=24",
                        "-f", "lavfi", "-i", "sine=frequency=261.63:duration=2:sample_rate=44100",
                        "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(video_path)], check=True)
        status, video = self.request("/upload/video", video_path.read_bytes(), {"X-File-Name": quote("测试.mp4")})
        self.assertEqual(status, 201)
        asset = "/assets/" + video["id"]
        self.assertEqual(self.request(asset + "/frame?time=.5")[0], 200)
        self.assertEqual(self.request(asset + "/calibration-hint?time=.5")[0], 200)
        self.assertEqual(self.request("/jobs", {"video_id": video["id"], "mode": "fingering"})[0], 400)
        status, skeleton = self.request("/jobs", {"video_id": video["id"], "mode": "skeleton_only"})
        self.assertEqual(status, 202)
        status, fingering = self.request("/jobs", {
            "video_id": video["id"], "midi_id": imported["id"], "mode": "fingering", "offset": .15,
            "corners": [[8,20],[310,20],[310,200],[8,200]], "calibration_time": .5,
        })
        self.assertEqual(status, 202)
        status, audio = self.request("/jobs", {"video_id": video["id"], "mode": "audio", "reference_id": imported["id"]})
        self.assertEqual(status, 202)

        skeleton_path, result = self.wait_job(skeleton)
        self.assertEqual(result["notes"], [])
        self.assertEqual(result["summary"]["mode"], "skeleton_only")
        self.assertEqual(self.request(skeleton_path + "/replay", headers={"Range": "bytes=0-31"})[0], 206)
        fingering_path, result = self.wait_job(fingering)
        self.assertEqual(len(result["notes"]), 1)
        self.assertEqual(result["notes"][0]["status"], "unmatched")
        self.assertEqual(result["summary"]["offset_seconds"], .15)
        audio_path, result = self.wait_job(audio)
        self.assertEqual(result["summary"]["comparison_status"], "insufficient")
        self.assertGreater(result["summary"]["notes"], 0)
        self.assertEqual(self.request(audio_path + "/transcribed.mid")[0], 200)

        coach_path = fingering_path + "/coach"
        segment = {"question": "这段指法怎么练？", "start": .5, "end": .9, "note_ids": ["0"], "send": True}
        status, message = self.request(coach_path, segment)
        self.assertEqual(status, 201)
        self.assertEqual(message["status"], "answered")
        self.assertEqual(message["evidence"]["notes"][0]["time"], .55)
        self.assertEqual(message["evidence"]["counts"]["unmatched"], 1)
        self.assertEqual(ModelStub.received["token"], "Bearer " + TOKEN)
        payload = json.loads(ModelStub.received["body"]["messages"][1]["content"])
        self.assertEqual(set(payload), {"question", "evidence", "references"})
        self.assertEqual(payload["evidence"], message["evidence"])
        self.assertEqual(self.request(coach_path, {**segment, "end": 20})[0], 400)
        status, plan = self.request(fingering_path + "/practice-plan", segment)
        self.assertEqual(status,200)
        self.assertEqual(len(plan["items"]),2)
        status, task = self.request("/practice", {**plan["items"][0], "job_id":fingering["id"], "start":.5, "end":.9})
        self.assertEqual(status, 201)
        self.assertEqual(self.request("/practice/" + task["id"] + "/edit", {"title":"修改后的计划", "detail":"两个循环"})[0],200)
        self.assertTrue(self.request("/practice/" + task["id"] + "/complete", {"completed":True})[1]["completed_at"])
        self.assertEqual(self.request("/jobs", client=admin)[1],[])
        self.assertEqual(self.request(fingering_path + "/result", client=admin)[0],404)
        self.assertEqual(self.request(asset + "/video", client=admin)[0],404)
        self.assertEqual(self.request(fingering_path + "/practice-plan", segment, client=admin)[0],404)
        self.assertEqual(self.request("/practice", client=admin)[1],[])
        self.assertEqual(self.request("/practice/" + task["id"] + "/remove", {}, client=admin)[0],400)

        self.stop_api()
        self.start_api()
        self.assertEqual(self.request("/coach/status")[1], {"configured": True})
        self.assertEqual(self.request(coach_path)[1][0]["id"], message["id"])
        self.assertEqual(self.request("/practice")[1][0]["id"], task["id"])
        self.assertEqual(self.request("/library")[1][0]["id"], imported["id"])
        self.assertEqual(self.request("/practice/" + task["id"] + "/remove", {})[0],200)
        self.assertEqual(self.request("/practice")[1],[])
        self.assertEqual(self.request("/admin/coach", {"disable":True}, client=admin)[0], 200)
        self.assertEqual(self.request("/coach/status")[1], {"configured": False})
        self.assertEqual(self.request("/auth/logout", {})[0],200)
        self.assertEqual(self.request("/jobs")[0],401)


if __name__ == "__main__":
    unittest.main()
