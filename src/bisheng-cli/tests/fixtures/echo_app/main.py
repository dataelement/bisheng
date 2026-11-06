"""Echo app for the `bisheng dev` end-to-end test: answers with what it received.

Reads `PORT` (铁律①), binds 0.0.0.0 (铁律②) and reports every header plus the
platform environment it was given, so the test can assert what crossed the
proxy and what entered the process.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PORT") or os.environ.get("BISHENG_APP_PORT") or 8080)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        payload = {
            "path": self.path,
            "headers": {k.lower(): v for k, v in self.headers.items()},
            "env": {k: v for k, v in os.environ.items() if k.startswith(("BISHENG_", "PORT"))},
        }
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
