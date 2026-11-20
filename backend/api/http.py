"""HTTP request parsing and response writing."""

import json
import mimetypes
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler


COOKIE = "piano_session"


class HttpHandler(BaseHTTPRequestHandler):
    def session_token(self):
        try:
            cookie = SimpleCookie(self.headers.get("Cookie", "")).get(COOKIE)
            return cookie.value if cookie else ""
        except CookieError:
            return ""

    def session_cookie(self, token, max_age):
        secure = "; Secure" if self.secure_cookies else ""
        return f"{COOKIE}={token}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Strict{secure}"

    def read_json(self):
        size = int(self.headers.get("Content-Length", "0"))
        if not 0 < size < 100000:
            raise ValueError("请求过大或为空")
        data = json.loads(self.rfile.read(size))
        if not isinstance(data, dict):
            raise ValueError("需要 JSON 对象")
        return data

    def body(self, body, content_type, status=200, cookie=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        if cookie is not None:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def json(self, data, status=200, cookie=None):
        self.body(json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8", status, cookie)

    def error(self, message, status, **details):
        self.json({"error": message, **details}, status)

    def media(self, path, content_type=None, *, private=True):
        if not path.is_file():
            return self.error("文件不存在", 404)
        size = path.stat().st_size
        start, end = 0, size - 1
        byte_range = self.headers.get("Range")
        if byte_range:
            try:
                left, right = byte_range.removeprefix("bytes=").split("-")
                start = int(left or 0)
                end = min(int(right) if right else end, end)
                if start > end:
                    raise ValueError
            except ValueError:
                return self.error("无效播放范围", 416)

        self.send_response(206 if byte_range else 200)
        self.send_header("Content-Type", content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if private:
            self.send_header("Cache-Control", "private, no-store")
        if byte_range:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with path.open("rb") as file:
            file.seek(start)
            remaining = end - start + 1
            while remaining:
                data = file.read(min(remaining, 1024 * 1024))
                if not data:
                    break
                self.wfile.write(data)
                remaining -= len(data)
