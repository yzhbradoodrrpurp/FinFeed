"""Loopback-only local dashboard. No paid platform credentials or scraping."""
import argparse
import json
import re
import threading
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from data import security
from state import read_state, update_state

ROOT = Path(__file__).resolve().parent
SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9.^=-]{0,19}$")


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        host = self.headers.get("Host", "").split(":")[0]
        if host not in ("127.0.0.1", "localhost"):
            return self.send_json({"error": "仅支持本机访问"}, 403)
        url = urlsplit(self.path)
        if url.path == "/api/state":
            try:
                return self.send_json({"state": read_state()})
            except (ValueError, OSError):
                return self.send_json({"error": "本机记录读取失败，请检查 dashboard/.local/state.json"}, 500)
        if url.path == "/api/health":
            return self.send_json({"ok": True, "service": "FinFeed"})
        if url.path.startswith("/api/security/"):
            symbol = unquote(url.path.removeprefix("/api/security/")).upper()
            if not SYMBOL.fullmatch(symbol):
                return self.send_json({"error": "无效 ticker"}, 400)
            return self.send_json(security(symbol, parse_qs(url.query).get("refresh") == ["1"]))
        if url.path.startswith("/api/"):
            return self.send_json({"error": "接口不存在"}, 404)
        return super().do_GET()

    def do_PUT(self):
        host = self.headers.get("Host", "").split(":")[0]
        origin = self.headers.get("Origin")
        if host not in ("127.0.0.1", "localhost") or (origin and origin != f"http://{self.headers.get('Host')}"):
            return self.send_json({"error": "仅支持同源本机访问"}, 403)
        if urlsplit(self.path).path != "/api/state":
            return self.send_json({"error": "接口不存在"}, 404)
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            return self.send_json({"error": "需要 JSON"}, 415)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 65536:
                raise ValueError("请求大小无效")
            patch = json.loads(self.rfile.read(length))
            if not isinstance(patch, dict):
                raise ValueError("无效保存格式")
            return self.send_json({"state": update_state(patch)})
        except ValueError as exc:
            return self.send_json({"error": str(exc)}, 400)
        except OSError:
            return self.send_json({"error": "本机文件保存失败"}, 500)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="启动后在默认浏览器打开")
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), partial(Handler, directory=str(ROOT / "public")))
    print(f"FinFeed local: http://127.0.0.1:{args.port}", flush=True)
    if args.open:
        threading.Timer(1, lambda: webbrowser.open(f"http://127.0.0.1:{args.port}")).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
