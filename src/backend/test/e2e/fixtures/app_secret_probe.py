"""Dedicated F055 test app. Only synthetic values are used; output contains booleans."""

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer


class ProbeHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        value = os.environ.get("F055_TEST_COLOR", "")
        body = json.dumps(
            {"before": value == "e2e-before", "after": value == "e2e-after", "empty": value == ""}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    print("F055 probe active: " + os.environ.get("F055_TEST_COLOR", ""), flush=True)
    HTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8080"))), ProbeHandler).serve_forever()
