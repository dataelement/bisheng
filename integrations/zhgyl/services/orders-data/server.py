"""Private read-only synthetic-order API for the isolated acceptance stack."""

import argparse
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # Never log authorization headers or business payloads.

    def send_json(self, code, payload):
        raw = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/health":
            return self.send_json(200, {"status": "ok", "synthetic_only": True})
        if self.path != "/api/zhgyl/orders":
            return self.send_json(404, {"error": "not_found"})
        supplied = self.headers.get("X-Zhgyl-Data-Key", "")
        if not hmac.compare_digest(supplied.encode(), self.server.api_key.encode()):
            return self.send_json(403, {"error": "forbidden"})
        # Fail closed on missing/corrupt datasets; no fallback pretending an empty source.
        try:
            raw = self.server.dataset.read_bytes()
            if len(raw) > 8 * 1024 * 1024:
                raise ValueError("dataset budget")
            value = json.loads(raw)
            if not isinstance(value, dict) or not isinstance(value.get("orders"), list):
                raise ValueError("dataset shape")
            if not all(order.get("mock") is True for order in value["orders"]):
                raise ValueError("synthetic-only boundary")
        except (OSError, ValueError, TypeError, AttributeError):
            return self.send_json(503, {"error": "synthetic_dataset_unavailable"})
        return self.send_json(200, value)

    def do_POST(self):
        return self.send_json(405, {"error": "read_only"})

    do_PUT = do_PATCH = do_DELETE = do_POST


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--bind", default="127.0.0.1", choices=["127.0.0.1", "0.0.0.0"])
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    key = os.environ.get("ZHGYL_ORDERS_DATA_KEY", "")
    if len(key) < 24:
        raise ValueError("Local service credential required")
    server = ThreadingHTTPServer((args.bind, args.port), Handler)
    server.api_key, server.dataset = key, Path(args.dataset)
    server.serve_forever()


if __name__ == "__main__":
    main()
