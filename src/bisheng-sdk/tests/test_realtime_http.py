"""Real HTTP/SSE and subprocess restart using the shipped workbench example.

Headers here model the trusted ingress contract. Real enterprise login/FGA
acceptance is separate; these tests do not claim to authenticate real accounts.
"""

import http.client
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

EXAMPLE = (
    Path(__file__).resolve().parents[3]
    / "src/backend/bisheng/dev_toolkit/skills/platform-wiring/workbench-realtime/main.py"
)
SDK = Path(__file__).resolve().parents[1]


def headers(user):
    return {
        "X-BiSheng-User-Id": user,
        "X-BiSheng-Tenant-Id": "team",
        "X-BiSheng-App-Id": "shared-demo",
        "Content-Type": "application/json",
    }


def start(database):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    process = subprocess.Popen(
        [sys.executable, str(EXAMPLE)],
        env={
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(SDK),
            "PORT": str(port),
            "BISHENG_APP_DB_PATH": str(database),
            "BISHENG_APP_BIND": "127.0.0.1",
        },
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(100):
            if process.poll() is not None:
                raise AssertionError("Sample process exited before readiness")
            try:
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
                conn.request("GET", "/")
                response = conn.getresponse()
                response.read()
                conn.close()
                if response.status == 200:
                    return process, port
            except OSError:
                time.sleep(0.03)
        raise AssertionError("Sample process did not become ready")
    except BaseException:
        stop(process)
        raise


def stop(process):
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def request(port, method, path, body=None, user="alice"):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        connection.request(
            method, path, body=json.dumps(body) if body is not None else None, headers=headers(user) if user else {}
        )
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


def test_ac07_ac08_ac09_http_sse_conflict_retry_and_process_restart(tmp_path):
    database = tmp_path / "app.db"
    process, port = start(database)
    stream = http.client.HTTPConnection("127.0.0.1", port, timeout=4)
    try:
        assert request(port, "GET", "/api/snapshot", user=None)[0] == 401
        initial = request(port, "GET", "/api/snapshot", user="bob")[1]
        stream.request("GET", "/api/events?after=" + str(initial["cursor"]), headers=headers("bob"))
        events = stream.getresponse()
        assert events.status == 200
        body = {"text": "Alice saved this record", "expected_revision": 0, "operation_id": "alice-save"}
        status, saved = request(port, "POST", "/api/record", body)
        assert status == 200 and saved["revision"] == 1
        for _ in range(12):
            line = events.readline()
            if line.startswith(b"data:"):
                event = json.loads(line[5:])
                assert event["record_id"] == "shared-note" and event["revision"] == 1
                break
        else:
            raise AssertionError("Bob did not receive Alice's change event")
        assert request(port, "POST", "/api/record", body)[1] == saved
        assert (
            request(
                port,
                "POST",
                "/api/record",
                {**body, "operation_id": "bob-stale", "text": "Stale overwrite"},
                user="bob",
            )[0]
            == 409
        )
        after = request(port, "GET", "/api/snapshot", user="bob")[1]
        assert after["records"][0]["value"]["text"] == body["text"]
    finally:
        stream.close()
        stop(process)
    restarted, new_port = start(database)
    try:
        assert request(new_port, "GET", "/api/snapshot", user="bob")[1] == after
    finally:
        stop(restarted)
