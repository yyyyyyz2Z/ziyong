"""Serve both training workspaces on separate loopback ports."""

import argparse
import base64
import binascii
import json
import mimetypes
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.parse import urlsplit
from zipfile import BadZipFile, ZipFile

import pretty_midi
from music21.exceptions21 import Music21Exception

from backend.analysis.score_excerpt import excerpt_midi, read_musicxml, score_measures
from . import alignment, demo
from .recognition import MUSICXML_EXTENSIONS, find_audiveris, recognize_pdf


ROOT = Path(__file__).resolve().parent
ASSETS = {"/styles.css": "styles.css", "/common.js": "common.js",
          "/score.js": "score.js", "/alignment.js": "alignment.js"}
LIMIT = 16 * 1024 * 1024
SCRATCH = ROOT.parent / "temp"


def read_file(payload, label, extensions, max_mb=5):
    if not isinstance(payload, dict) or not isinstance(payload.get("name"), str):
        raise ValueError(f"请选择{label}文件")
    suffix = Path(payload["name"]).suffix.lower()
    if suffix not in extensions:
        raise ValueError(f"{label}文件支持 {'、'.join(extensions)}")
    try:
        content = base64.b64decode(payload.get("data"), validate=True)
    except (ValueError, TypeError, binascii.Error) as exc:
        raise ValueError(f"无法读取{label}文件") from exc
    if not content or len(content) > max_mb * 1024 * 1024:
        raise ValueError(f"{label}文件须在 {max_mb} MB 以内")
    return suffix, content


def load_midi(content):
    try:
        return pretty_midi.PrettyMIDI(BytesIO(content))
    except (ValueError, EOFError, OSError, IndexError) as exc:
        raise ValueError("无法解析 MIDI，请检查文件是否完整") from exc


def midi_notes(midi, prefix):
    events = sorted((note.start, note.pitch, note.end, track)
                    for track, instrument in enumerate(midi.instruments)
                    if not instrument.is_drum for note in instrument.notes)
    return [{"id": f"{prefix}{index:04d}", "pitch": int(pitch), "onset": round(float(start), 6),
             "duration": round(float(end - start), 6), "track": track}
            for index, (start, pitch, end, track) in enumerate(events, 1)]


def score_api(payload, export=False):
    suffix, content = read_file(payload.get("file"), "乐谱", MUSICXML_EXTENSIONS)
    if suffix == ".mxl":
        try:
            with ZipFile(BytesIO(content)) as archive:
                members = archive.infolist()
                if len(members) > 100 or sum(item.file_size for item in members) > 15 * 1024 * 1024:
                    raise ValueError("MXL 解压后过大，请先截取乐谱")
        except BadZipFile as exc:
            raise ValueError("无法打开 MXL 压缩乐谱") from exc

    SCRATCH.mkdir(exist_ok=True)
    with TemporaryDirectory(dir=SCRATCH) as directory:
        source = Path(directory) / f"score{suffix}"
        source.write_bytes(content)
        score = read_musicxml(source)
    if not export:
        return {"measures": score_measures(score), "parts": len(score.parts)}

    first, last = payload.get("first"), payload.get("last")
    if type(first) is not int or type(last) is not int:
        raise ValueError("起止小节须为整数")
    midi = excerpt_midi(score, first, last)
    buffer = BytesIO()
    midi.save(file=buffer)
    blob = buffer.getvalue()
    preview = load_midi(blob)
    notes = midi_notes(preview, "r")
    tempos, rates = preview.get_tempo_changes()
    return {"midi": base64.b64encode(blob).decode("ascii"), "notes": notes,
            "duration": midi.length, "tracks": len({note["track"] for note in notes}),
            "tempos": [{"time": float(time), "bpm": round(float(rate), 1)} for time, rate in zip(tempos, rates)]}


def recognize_api(payload, executable):
    _, content = read_file(payload.get("file"), "PDF 乐谱", (".pdf",), max_mb=10)
    SCRATCH.mkdir(exist_ok=True)
    with TemporaryDirectory(dir=SCRATCH) as directory:
        suffix, xml = recognize_pdf(content, executable, Path(directory))
    return {"file": {"name": f"recognized{suffix}", "data": base64.b64encode(xml).decode("ascii")}}


def align_api(payload):
    reference = load_midi(read_file(payload.get("reference"), "参考 MIDI", (".mid", ".midi"))[1])
    performance = load_midi(read_file(payload.get("performance"), "演奏 MIDI", (".mid", ".midi"))[1])
    return alignment.align_one(alignment.read_notes(midi_notes(reference, "r"), "参考 MIDI"),
                               alignment.read_notes(midi_notes(performance, "p"), "演奏 MIDI"),
                               alignment.read_model(payload.get("model")))


def handler_for(site, audiveris=None):
    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, content, mime):
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; object-src 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(content)

        def json(self, content, status=200):
            self.reply(status, json.dumps(content, ensure_ascii=False, allow_nan=False).encode("utf-8"),
                       "application/json; charset=utf-8")

        def do_GET(self):
            path = urlsplit(self.path).path
            if site == "score" and path == "/api/score-capabilities":
                self.json({"pdf_recognition": audiveris is not None})
                return
            if site == "score" and path == "/api/demo-score":
                self.reply(200, demo.score_file(), "application/xml; charset=utf-8")
                return
            if site == "alignment" and path == "/api/demo-dataset":
                self.json(demo.alignment_dataset())
                return
            name = f"{site}.html" if path == "/" else ASSETS.get(path)
            if name is None:
                self.json({"error": "页面不存在"}, 404)
                return
            asset = ROOT / "web" / name
            content_type = mimetypes.guess_type(asset.name)[0] or "application/octet-stream"
            self.reply(200, asset.read_bytes(), f"{content_type}; charset=utf-8")

        def do_POST(self):
            path = urlsplit(self.path).path
            endpoints = ({"/api/score": score_api, "/api/export": lambda data: score_api(data, export=True),
                          "/api/recognize": lambda data: recognize_api(data, audiveris)}
                         if site == "score" else {"/api/train": alignment.train, "/api/align": align_api})
            if path not in endpoints:
                self.json({"error": "接口不存在"}, 404)
                return
            host = self.headers.get("Host")
            origin = self.headers.get("Origin")
            if origin and origin != f"http://{host}":
                self.json({"error": "请从本地页面提交数据"}, 403)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length > LIMIT:
                    self.json({"error": "请求超过 16 MB，请分批提交"}, 413)
                    return
                if self.headers.get_content_type() != "application/json" or length < 1:
                    raise ValueError("请求须包含 JSON 数据")
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError("请求须为 JSON 对象")
                result = endpoints[path](data)
            except (ValueError, UnicodeError, Music21Exception, BadZipFile) as exc:
                self.json({"error": str(exc) or "无法读取输入文件"}, 422)
                return
            except Exception as exc:
                self.log_error("%s: %s", type(exc).__name__, exc)
                self.json({"error": "无法处理数据，请检查文件格式和本地服务日志"}, 500)
                return
            self.json(result)

        def log_message(self, fmt, *args):
            if not self.path.endswith((".css", ".js", "/favicon.ico")):
                super().log_message(fmt, *args)

    return Handler


def main():
    parser = argparse.ArgumentParser(description="启动乐谱选段与对齐训练两个本地网站")
    parser.add_argument("--score-port", type=int, default=8761)
    parser.add_argument("--alignment-port", type=int, default=8762)
    parser.add_argument("--audiveris", default=os.environ.get("AUDIVERIS_COMMAND"), help="Audiveris 可执行文件路径")
    args = parser.parse_args()
    audiveris = find_audiveris(args.audiveris)
    if args.audiveris and audiveris is None:
        parser.error("指定的 Audiveris 可执行文件不存在")
    with ThreadingHTTPServer(("127.0.0.1", args.score_port), handler_for("score", audiveris)) as score:
        with ThreadingHTTPServer(("127.0.0.1", args.alignment_port), handler_for("alignment")) as align:
            thread = Thread(target=score.serve_forever, daemon=True)
            thread.start()
            print(f"Score excerpts      http://127.0.0.1:{score.server_port}", flush=True)
            print(f"Alignment training  http://127.0.0.1:{align.server_port}", flush=True)
            if audiveris:
                print(f"Audiveris           {audiveris}", flush=True)
            try:
                align.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                score.shutdown()
                thread.join()


if __name__ == "__main__":
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
    main()
