import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = int(os.environ.get("LAUNCHER_APP_PORT", 8168))
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
