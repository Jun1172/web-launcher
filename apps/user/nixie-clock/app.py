import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def get_port():
    """端口读取：优先 LAUNCHER_APP_PORT，缺失回退 app.json 的 port，均无效返回 0。"""
    env_port = os.environ.get("LAUNCHER_APP_PORT")
    if env_port:
        try:
            return int(env_port)
        except ValueError:
            pass
    j = Path(__file__).resolve().parent / "app.json"
    if j.exists():
        try:
            return int(json.loads(j.read_text(encoding="utf-8")).get("port", 0))
        except Exception:
            pass
    return 0


PORT = get_port()
PAGE = Path(__file__).with_name("index.html").read_text(encoding="utf-8")


class Handler(BaseHTTPRequestHandler):
	def do_GET(self):
		body = PAGE.encode("utf-8")
		self.send_response(200)
		self.send_header("Content-Type", "text/html; charset=utf-8")
		self.send_header("Cache-Control", "no-store")
		self.send_header("Content-Length", str(len(body)))
		self.end_headers()
		self.wfile.write(body)

	def log_message(self, *_):
		pass


if __name__ == "__main__":
	ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
