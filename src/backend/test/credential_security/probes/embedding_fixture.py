"""Deterministic OpenAI-compatible test embeddings; not a model-quality test."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        return  # Fixture payloads and authorization headers stay out of logs.

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        values = request.get("input", [])
        if isinstance(values, str):
            values = [values]
        payload = {
            "object": "list",
            "model": "credential-embedding",
            "data": [
                {"object": "embedding", "index": i, "embedding": [0.1, 0.2, 0.3, 0.4]} for i, _ in enumerate(values)
            ],
            "usage": {"prompt_tokens": len(values), "total_tokens": len(values)},
        }
        content = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
