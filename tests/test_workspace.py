"""Exercise the local workspace over HTTP, including admin and model boundaries."""

import csv
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
from backend.analysis.calibration import keyboard_mapping


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
        status, catalog = self.request("/technique/exercises")
        self.assertEqual(status, 200)
        self.assertEqual([item["id"] for item in catalog["exercises"]], ["T02", "T03", "T04"])

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
        # Known synthetic input exercises the new selector and CLI path. The
        # white test frame contains no hand, so only MIDI timing is available.
        scale = pretty_midi.PrettyMIDI()
        scale.instruments.append(pretty_midi.Instrument(0))
        for index, pitch in enumerate((72, 71, 69, 67, 65, 64, 62, 60)):
            start = .2 * (index + 1)
            scale.instruments[0].notes.append(pretty_midi.Note(80, pitch, start, start + .1))
        scale.write(str(midi_path))
        status, scale_midi = self.request("/upload/midi", midi_path.read_bytes(), {"X-File-Name": "scale.mid"})
        self.assertEqual(status, 201)
        corners = [[8,20],[310,20],[310,200],[8,200]]
        template = keyboard_mapping(corners, 320, 240, 21, 108, False)
        keys = []
        for key in template["key_centers"]:
            x, y = key["x"], key["y"]
            outline = [[x - 1, y - 2], [x + 1, y - 2], [x + 1, y + 2], [x - 1, y + 2]]
            keys.append(dict(midi_pitch=key["midi_pitch"], outline=outline, surface=outline))
        scale_job = dict(video_id=video["id"], midi_id=scale_midi["id"], mode="fingering", exercise="T03",
                         keyboard=dict(source="pianocv_auto", time=.5, corners=corners, keys=keys))
        status, submitted = self.request("/jobs", scale_job)
        self.assertEqual(status, 202)
        scale_path, result = self.wait_job(submitted)
        report = result["summary"]["technique"]
        self.assertEqual(report["task"], "T03")
        attempt, = report["attempts"]
        self.assertEqual(attempt["note_names"], ["F4", "E4"])
        self.assertEqual(attempt["motion"]["status"], "fingering_unconfirmed")
        self.assertEqual(attempt["ratio"], 1)
        status, graph_message = self.request(scale_path + "/coach", dict(question="怎么复练换指？", start=.8, end=1.4, send=True))
        self.assertEqual(status, 201)
        payload = json.loads(ModelStub.received["body"]["messages"][1]["content"])
        self.assertEqual(payload["evidence"]["technique"]["attempts"][0]["note_names"], ["F4", "E4"])
        self.assertNotIn("R09", {rule["id"] for rule in payload["evidence"]["technique"]["rules"]})
        self.assertIn("P07", {reference["id"] for reference in graph_message["references"]})
        scale.instruments[0].notes[-1].end = 25
        scale.write(str(midi_path))
        status, long_midi = self.request("/upload/midi", midi_path.read_bytes(), {"X-File-Name": "long-release.mid"})
        self.assertEqual(status, 201)
        status, with_duration_warning = self.request("/jobs", {
            "video_id": video["id"], "midi_id": long_midi["id"], "mode": "fingering",
            "corners": corners, "calibration_time": .5,
        })
        self.assertEqual(status, 202)
        self.assertTrue(with_duration_warning["duration_warning"])
        self.wait_job(with_duration_warning)
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


    def test_full_plan_calendar_and_personal_calendar_export(self):
        status, logged = self.request('/auth/login', {'username':'admin', 'password':PASSWORD})
        self.assertEqual(status, 200)
        owner = logged['account']['id']
        identifier = uuid4().hex
        folder = self.root / 'store' / identifier
        folder.mkdir()
        (folder / 'job.json').write_text(json.dumps(dict(id=identifier, status='succeeded', mode='performance',
            created_at='2026-11-23T00:00:00Z', title='全曲测试')), encoding='utf-8')
        (folder / 'analysis_summary.json').write_text(json.dumps(dict(mode='performance', video_duration_seconds=120)), encoding='utf-8')
        evaluation = '这次全曲优先练习右手换指连接，再练两手落点。'
        (folder / 'overview.json').write_text(json.dumps(dict(status='answered', answer=evaluation)), encoding='utf-8')
        connection = pymysql.connect(**self.db_options, database=self.db_name)
        with connection:
            with connection.cursor() as cursor:
                cursor.execute('INSERT INTO resources VALUES (%s,%s,%s)', (identifier, owner, 'job'))
            connection.commit()
        self.assertEqual(self.request('/admin/coach', {'endpoint':f'http://127.0.0.1:{self.model.server_port}/chat/completions',
            'model':'calendar-test', 'api_key':TOKEN})[0], 200)
        route = '/jobs/' + identifier + '/practice-plan'
        status, plan = self.request(route, {'scope':'full','save':True, 'start':30, 'end':31})
        self.assertEqual(status, 200)
        self.assertEqual(len(plan['items']), 2)
        evidence = json.loads(ModelStub.received['body']['messages'][1]['content'])['evidence']
        self.assertEqual(evidence['overall_evaluation'], evaluation)
        self.assertEqual((evidence['start'], evidence['end']), (0,120))
        again = self.request(route, {'scope':'full','save':True})[1]
        self.assertEqual({item['id'] for item in plan['items']}, {item['id'] for item in again['items']})
        self.assertEqual(len(self.request('/practice')[1]), 2)
        self.assertEqual(self.request('/practice/calendar.ics')[0], 400)
        schedule = {'weekdays':[0,2,4], 'start_date':'2026-11-24', 'end_date':'2026-12-20'}
        self.assertEqual(self.request('/practice/schedule', schedule)[0], 200)
        self.assertEqual(self.request('/practice/schedule', {**schedule,'weekdays':[0,0]})[0], 400)
        self.assertEqual(self.request('/practice/schedule', {**schedule,'end_date':'2026-11-01'})[0], 400)
        task = plan['items'][0]
        self.assertEqual(self.request('/practice/' + task['id'] + '/check', {'date':'2026-11-25','completed':True})[0], 200)
        self.assertEqual(self.request('/practice/' + task['id'] + '/check', {'date':'2026-11-27','completed':True})[0], 200)
        exported = self.request('/practice/calendar.ics')[1].decode().replace('\r\n ', '')
        self.assertIn('DTSTART;VALUE=DATE:20261125', exported)
        self.assertIn('BYDAY=MO,WE,FR', exported)
        self.assertIn('UNTIL=20261220', exported)
        self.assertIn(task['title'], exported)
        self.stop_api(); self.start_api()
        calendar = self.request('/practice/calendar')[1]
        self.assertEqual(calendar['schedule'], schedule)
        self.assertEqual(len(calendar['checks']), 2)
        self.assertEqual(self.request('/practice/' + task['id'] + '/check', {'date':'2026-11-25','completed':False})[0], 200)
        self.assertEqual(len(self.request('/practice/calendar')[1]['checks']), 1)
        self.assertEqual(self.request('/practice/' + task['id'] + '/remove', {})[0], 200)
        self.assertEqual(self.request('/practice/calendar')[1]['checks'], [])
        self.assertEqual(self.request('/auth/register', {'username':'calendar-other','password':PASSWORD})[0], 201)
        self.assertEqual(self.request('/practice/calendar')[1], {'schedule':None,'checks':[]})
        self.assertEqual(self.request('/practice/' + plan['items'][1]['id'] + '/check', {'date':'2026-11-25','completed':True})[0], 400)
        self.assertEqual(self.request(route, {'scope':'full','save':True})[0], 404)

    def test_ai_suggestions_require_confirmation_and_keep_edits(self):
        self.assertEqual(self.request('/auth/login', {'username':'admin','password':PASSWORD})[0], 200)
        owner = self.request('/auth/me')[1]['account']['id']
        identifier = uuid4().hex
        folder = self.root / 'store' / identifier
        folder.mkdir()
        (folder / 'job.json').write_text(json.dumps(dict(id=identifier,status='succeeded',mode='performance')))
        (folder / 'analysis_summary.json').write_text(json.dumps(dict(video_duration_seconds=60,mode='performance')))
        (folder / 'overview.json').write_text(json.dumps(dict(status='answered',answer='先练节奏，再练换指。')))
        connection = pymysql.connect(**self.db_options, database=self.db_name)
        with connection:
            with connection.cursor() as cursor:
                cursor.execute('INSERT INTO resources VALUES (%s,%s,%s)', (identifier,owner,'job'))
            connection.commit()
        self.request('/admin/coach', {'endpoint':f'http://127.0.0.1:{self.model.server_port}/chat/completions','model':'draft-test','api_key':TOKEN})
        status, draft = self.request('/jobs/' + identifier + '/practice-plan', {'scope':'full'})
        self.assertEqual(status, 200)
        self.assertEqual(draft['status'],'pending')
        self.assertEqual(self.request('/practice')[1], [])
        self.assertEqual(len(self.request('/practice/drafts')[1]),1)
        self.stop_api(); self.start_api()
        self.assertEqual(self.request('/practice/drafts')[1][0]['id'],draft['id'])
        edited = {'title':'我修改的慢练项目','detail':'分手慢练三个循环','weekdays':[0,4]}
        path = '/practice/drafts/' + draft['id'] + '/confirm'
        status, confirmed = self.request(path, {'items':[edited]})
        self.assertEqual(status,200)
        self.assertEqual(self.request(path, {'items':[edited]})[1],confirmed)
        tasks = self.request('/practice')[1]
        self.assertEqual(len(tasks),1)
        self.assertEqual({key:tasks[0][key] for key in edited}, edited)
        self.assertEqual(self.request('/practice/drafts')[1],[])
        task = tasks[0]
        self.assertEqual(self.request('/practice/' + task['id'] + '/edit', {'title':'再次修改','detail':'五遍','weekdays':[2]})[1]['weekdays'],[2])
        self.assertEqual(self.request('/practice/' + task['id'] + '/edit', {'title':'保留星期','detail':'六遍'})[1]['weekdays'],[2])

    def test_historical_score_review_reaches_coach(self):
        admin = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))
        self.assertEqual(self.request("/auth/login", {"username": "admin", "password": PASSWORD}, client=admin)[0], 200)
        status, player = self.request("/auth/register", {"username": "score-reviewer", "password": PASSWORD})
        self.assertEqual(status, 201)
        self.assertEqual(self.request("/admin/coach", {
            "endpoint": f"http://127.0.0.1:{self.model.server_port}/v1/chat/completions",
            "model": "workspace-test", "api_key": TOKEN,
        }, client=admin)[0], 200)

        # Seed immutable outputs from an already completed job. Attaching a
        # score or changing its review should never enqueue a video job.
        identifier = uuid4().hex
        folder = self.root / "store" / identifier
        folder.mkdir()
        original_job = dict(id=identifier, mode="fingering", status="succeeded")
        (folder / "job.json").write_text(json.dumps(original_job), encoding="utf-8")
        (folder / "analysis_summary.json").write_text(json.dumps({
            "mode": "fingering", "video_duration_seconds": 2, "offset_seconds": 0,
        }), encoding="utf-8")
        predictions = []
        for index, pitch in enumerate((72, 71, 69, 67, 65, 64, 62, 60)):
            attack = (index + 1) * .2
            predictions.append(dict(note_index=index, pitch=pitch, note_name=pretty_midi.note_number_to_name(pitch),
                                    start_seconds=attack, end_seconds=attack + .1, start_frame=index + 1,
                                    status="matched", hand="right", finger=2))
        with (folder / "fingering_predictions.csv").open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=list(predictions[0]))
            writer.writeheader()
            writer.writerows(predictions)
        with pymysql.connect(**self.db_options, database=self.db_name, autocommit=True) as connection:
            with connection.cursor() as cursor:
                cursor.execute("INSERT INTO resources (resource_id, owner_id, kind) VALUES (%s, %s, 'job')",
                               (identifier, player["account"]["id"]))
        scale_path = "/jobs/" + identifier
        from music21 import meter, note, stream, tempo

        score = stream.Score()
        part = stream.Part()
        for bar, pitches in enumerate(((72, 71, 69, 66), (65, 64, 62, 60)), 1):
            measure = stream.Measure(number=bar)
            if bar == 1:
                measure.insert(0, meter.TimeSignature("4/4"))
                measure.insert(0, tempo.MetronomeMark(number=120))
            for pitch in pitches:
                measure.append(note.Note(pitch))
            part.append(measure)
        score.append(part)
        score_source = self.root / "review.musicxml"
        score.write("musicxml", fp=str(score_source))
        status, score_asset = self.request("/upload/score", score_source.read_bytes(), {"X-File-Name": "review.musicxml"})
        self.assertEqual(status, 201)
        attach = dict(score_id=score_asset["id"], measure_first=1, measure_last=2, revision=0)
        self.assertEqual(self.request(scale_path + "/score-reference", attach, client=admin)[0], 404)
        status, aligned = self.request(scale_path + "/score-reference", attach)
        self.assertEqual(status, 200)
        self.assertEqual(aligned["status"], "aligned")
        differing, = (row for row in aligned["rows"] if row["status"] == "pitch_candidate")
        self.assertEqual((differing["expected_note"], differing["played_note"]), ("F#4", "G4"))
        edit = dict(row_id=differing["id"], revision=aligned["revision"], verdict="confirmed", fingers=[1, 3])
        status, revised = self.request(scale_path + "/score-review", edit)
        self.assertEqual(status, 200)
        confirmed = next(row for row in revised["rows"] if row["id"] == differing["id"])
        self.assertEqual(confirmed["status"], "pitch_confirmed")
        self.assertEqual(confirmed["reference_fingers"], [1, 3])
        self.assertEqual(self.request(scale_path + "/score-review", edit)[0], 409)
        same = dict(attach, revision=revised["revision"])
        self.assertEqual(self.request(scale_path + "/score-reference", same)[1]["revision"], revised["revision"])
        self.assertEqual(self.request(scale_path + "/score_alignment.json")[1]["counts"]["pitch_confirmed"], 1)
        status, edited_message = self.request(scale_path + "/coach", dict(question="这一拍怎么改？", start=.65, end=.95, send=True))
        self.assertEqual(status, 201)
        payload = json.loads(ModelStub.received["body"]["messages"][1]["content"])
        actual, = payload["evidence"]["score_alignment"]["rows"]
        self.assertEqual(actual["manual_review"], "confirmed")
        self.assertEqual(actual["reference_fingers"], [1, 3])
        self.assertEqual(payload["evidence"]["score_alignment"]["revision"], revised["revision"])
        self.assertIn("P13", {item["id"] for item in edited_message["references"]})
        self.assertEqual(self.request(scale_path)[1]["status"], "succeeded")

        self.stop_api()
        self.start_api()
        self.assertEqual(self.request(scale_path + "/result")[1]["score_alignment"]["revision"], revised["revision"])
        self.assertEqual(self.request(scale_path)[1], original_job)


if __name__ == "__main__":
    unittest.main()
