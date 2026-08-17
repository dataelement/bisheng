"""Smallest hosted application the F055 tests publish.

Deliberately dependency-free and side-effect-free: it exists so a package has
something other than the manifest in it, and so the "no secret in the code"
negative samples have a realistic file to live in.
"""

import os
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(os.environ.get("PORT", "8080"))


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # stdlib callback name, not a project naming choice
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"ok")


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
