"""REVIEW DRAFT: one real local task-mode turn; never run without parent go-ahead.

Default mode performs NO network request. --execute uses an existing normal web
session, discovers current allowed tool/model IDs, submits the frontend's real
unified payload, polls real persisted state, and retains private raw evidence.
No login bypass, fake tool event, Redis or direct database access is used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import stat
import time
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from datetime import datetime

API = "/api/v1"
TERMINAL = {"completed", "failed", "terminated", "sop_generation_failed"}
REPO = Path(__file__).resolve().parents[4]


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def write_private(folder, name, value):
    path = folder / name
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as output:
        json.dump(value, output, ensure_ascii=False, indent=2)


def cookie_from_file(path):
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_mode & 0o077
    ):
        raise ValueError("Auth file must be an owned regular file with mode0600")
    value = json.loads(path.read_text())
    cookie = value.get("cookie")
    if not cookie:
        token = (
            value.get("access_token_cookie")
            or value.get("token")
            or value.get("access_token")
        )
        if not isinstance(token, str) or token.count(".") != 2:
            raise ValueError(
                "Provide a normal native web-session cookie/token, not a service API key"
            )
        cookie = "access_token_cookie=" + token
    if (
        not isinstance(cookie, str)
        or "\n" in cookie
        or "\r" in cookie
        or "access_token_cookie=" not in cookie
    ):
        raise ValueError("Native web-session cookie required")
    return cookie


class Client:
    def __init__(self, base, cookie, seconds):
        url = urlsplit(base)
        if (
            url.scheme != "http"
            or url.hostname != "127.0.0.1"
            or url.username
            or url.path not in ("", "/")
        ):
            raise ValueError(
                "Draft permits only an explicit loopback HTTP platform origin"
            )
        self.base, self.cookie = base.rstrip("/"), cookie
        self.deadline, self.calls = time.monotonic() + seconds, 0
        self.opener = build_opener(NoRedirect())

    def call(self, path, payload=None, *, sse=False, cancellation=False):
        self.calls += 1
        remaining = self.deadline - time.monotonic()
        if (remaining <= 0 or self.calls > 180) and not cancellation:
            raise TimeoutError("Bounded task test budget reached")
        headers = {"Cookie": self.cookie, "Content-Type": "application/json"}
        if sse:
            headers["Accept"] = "text/event-stream"
        req = Request(
            self.base + path,
            None if payload is None else json.dumps(payload).encode(),
            headers,
        )
        with self.opener.open(
            req, timeout=10 if cancellation else max(0.1, min(10, remaining))
        ) as response:
            raw = response.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError("Response budget reached")
        if sse:
            for line in raw.decode().splitlines():
                if line.startswith("data:"):
                    event = json.loads(line[5:].strip())
                    if event.get("event") == "linsight_task_handoff":
                        return event["data"]
            raise ValueError(
                "No real task handoff returned; do not automatically resubmit"
            )
        value = json.loads(raw)
        if isinstance(value, dict) and "status_code" in value:
            if value["status_code"] != 200:
                raise ValueError("Platform business-error envelope")
            return value.get("data")
        return value


def resolve_case(client, case):
    skills = client.call(API + "/linsight/skill/selectable")
    selected = next(
        (skill for skill in skills if skill.get("name") == case["skill"]), None
    )
    if selected is None:
        raise ValueError("Selected Skill is not available to this real user")
    model_config = client.call(API + "/llm/workbench")
    if isinstance(model_config.get("data"), dict):
        model_config = model_config["data"]
    if str(case["model_id"]) not in {
        str(model["id"]) for model in model_config.get("models", [])
    }:
        raise ValueError("Explicit execution model is not in the user model catalog")
    config = client.call(API + "/workstation/config")
    tools = []
    for name in case["tool_names"]:
        matches = [
            child
            for group in config.get("tools", [])
            if group.get("enabled") is not False
            for child in group.get("children", [])
            if child.get("enabled") is not False
            and (child.get("name") == name or child.get("tool_key") == name)
        ]
        if len(matches) != 1:
            raise ValueError(
                "Required tool absent or ambiguous in current authorized picker"
            )
        tools.append(
            {
                "id": int(matches[0]["id"]),
                "tool_key": matches[0]["tool_key"],
                "type": "tool",
            }
        )
    payload = {
        "text": case["question"],
        "clientTimestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "conversationId": None,
        "parentMessageId": None,
        "model": str(case["model_id"]),
        "tools": tools,
        "task_mode": True,
        "skills": [case["skill"]],
        "files": [],
        "use_knowledge_base": {
            "personal_knowledge_enabled": False,
            "organization_knowledge_ids": [],
            "knowledge_space_ids": [],
        },
    }
    if isinstance(selected.get("id"), int):
        payload["skill_ids"] = [selected["id"]]
    return payload


def skill_read_evidence(records, skill, expected_sha=None):
    wanted = f"skills/{skill}/SKILL.md"
    for record in records:
        if (
            record.get("name") != "read_file"
            or record.get("error")
            or not record.get("output")
        ):
            continue
        params = record.get("params") or record.get("input") or {}
        if isinstance(params, str):
            try:
                params = json.loads(params)
            except ValueError:
                params = {}
        if isinstance(params, dict) and any(
            str(params.get(key, "")).lstrip("/") == wanted
            for key in ("file_path", "path")
        ):
            return True
        output = record.get("output")
        if expected_sha and isinstance(output, str):
            lines = output.splitlines()
            if lines and all(re.match(r"^\s*\d+\t", line) for line in lines):
                content = "\n".join(re.sub(r"^\s*\d+\t", "", line) for line in lines)
                if any(
                    hashlib.sha256(value.encode()).hexdigest() == expected_sha
                    for value in (content, content + "\n")
                ):
                    return True
    return False


def collect(client, folder, chat_id, version_id, case, payload):
    versions = client.call(
        API
        + "/linsight/workbench/session-version-list?"
        + urlencode({"session_id": chat_id})
    )
    detail = client.call(
        API
        + "/linsight/workbench/execute-task-detail?"
        + urlencode({"session_version_id": version_id})
    )
    messages = client.call(API + "/workstation/messages/" + chat_id + "/agent")
    write_private(folder, "versions.json", versions)
    write_private(folder, "tasks-and-tool-history.json", detail)
    write_private(folder, "messages.json", messages)
    version = next(item for item in versions if item["id"] == version_id)
    records = [
        record
        for task in detail
        for record in (task.get("history") or [])
        if isinstance(record, dict)
    ]
    answer = (version.get("output_result") or {}).get("answer") or ""
    expected_sha = None
    if case.get("skill_md_path"):
        expected_sha = hashlib.sha256(
            Path(case["skill_md_path"]).read_bytes()
        ).hexdigest()
    observed_tools = {
        str(record.get("name"))
        for record in records
        if record.get("step_type") in {"tool", "tool_call"} and record.get("status") == "end"
    }
    fragments = case.get("expected_answer_fragments") or []
    checks = {
        "required_business_tools_observed": all(
            tool["tool_key"] in observed_tools for tool in payload["tools"]
        ),
        "skill_read_observed": skill_read_evidence(
            records, case["skill"], expected_sha
        ),
        "business_expectations_checked": bool(fragments),
        "business_expectations_passed": bool(fragments)
        and all(fragment in answer for fragment in fragments),
    }
    return {
        **checks,
        "chat_id": chat_id,
        "session_version_id": version_id,
        "status": version["status"],
        "model_id": str(version.get("model")),
        "skills": version.get("skills"),
        "answer_bytes": len(answer.encode()),
        "answer_sha256": hashlib.sha256(answer.encode()).hexdigest(),
        "messages": len(messages),
        "tool_history_records": len(records),
        "completed_tool_names": sorted(
            {
                str(record.get("name"))
                for record in records
                if record.get("step_type") in {"tool", "tool_call"}
                and record.get("status") == "end"
            }
        ),
        "raw_evidence_directory": str(folder),
        "browser_ui_verified": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Only after parent has reviewed and explicitly started this local run",
    )
    parser.add_argument("--base", default="http://127.0.0.1:13001")
    parser.add_argument("--auth-file", type=Path)
    parser.add_argument(
        "--case-file",
        type=Path,
        help="Private JSON {skill,model_id,tool_names:[operationName|tool_key],question}",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="NEW private evidence directory outside the repo",
    )
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({"review_draft_only": True, "network_requests": 0}))
        return
    if (
        not all((args.auth_file, args.case_file, args.output_dir))
        or not 15 <= args.timeout <= 300
    ):
        parser.error(
            "Execution requires private auth/case files, NEW output dir and a 15-300s global budget"
        )
    folder = args.output_dir.expanduser().resolve()
    if folder.exists() or REPO == folder or REPO in folder.parents:
        parser.error("Evidence destination must be NEW and outside the repository")
    folder.mkdir(parents=True, mode=0o700)
    folder.chmod(0o700)
    client = Client(args.base, cookie_from_file(args.auth_file), args.timeout)
    case = json.loads(args.case_file.read_text())
    if (
        not isinstance(case.get("skill"), str)
        or not isinstance(case.get("question"), str)
        or not 1 <= len(case.get("tool_names", [])) <= 4
    ):
        raise ValueError("One Skill, real tool selection and a question required")
    chat_id = version_id = None
    summary = {"status": "not_submitted", "browser_ui_verified": False}
    try:
        payload = resolve_case(client, case)
        # Do not save authentication headers. Payload may contain run capabilities,
        # so even request/raw tool history evidence is private0600 outside the repo.
        write_private(folder, "submitted-payload.json", payload)
        handoff = client.call(API + "/workstation/chat/completions", payload, sse=True)
        chat_id, version_id = handoff["chat_id"], handoff["session_version_id"]
        summary.update(
            chat_id=chat_id, session_version_id=version_id, status="handed_off"
        )
        write_private(folder, "handoff.json", handoff)
        # Match useAiChat's normal post-handoff fallback. A fast completed run can
        # reject this late call; confirm persisted terminal state before accepting.
        try:
            client.call(
                API + "/linsight/workbench/start-execute",
                {"linsight_session_version_id": version_id},
            )
        except ValueError:
            versions = client.call(
                API
                + "/linsight/workbench/session-version-list?"
                + urlencode({"session_id": chat_id})
            )
            if not any(
                v["id"] == version_id and v["status"] in TERMINAL for v in versions
            ):
                raise
        while True:
            versions = client.call(
                API
                + "/linsight/workbench/session-version-list?"
                + urlencode({"session_id": chat_id})
            )
            current = next(item for item in versions if item["id"] == version_id)
            summary["status"] = current["status"]
            if current["status"] in TERMINAL:
                break
            if current["status"] == "waiting_for_user_input":
                raise ValueError(
                    "Real task parked for input; draft never invents an answer"
                )
            time.sleep(min(2, max(0, client.deadline - time.monotonic())))
        summary = collect(client, folder, chat_id, version_id, case, payload)
        summary["selection_matches"] = summary["skills"] == [case["skill"]] and summary[
            "model_id"
        ] == str(case["model_id"])
        summary["infrastructure_passed"] = (
            summary["status"] == "completed"
            and summary["selection_matches"]
            and summary["required_business_tools_observed"]
            and summary["skill_read_observed"]
        )
        summary["passed"] = (
            summary["infrastructure_passed"] and summary["business_expectations_passed"]
        )
    except (Exception, KeyboardInterrupt) as error:
        summary.update(passed=False, error_type=type(error).__name__)
        if version_id:
            try:
                client.call(
                    API + "/linsight/workbench/terminate-execute",
                    {"linsight_session_version_id": version_id},
                    cancellation=True,
                )
                summary["cancel_requested"] = True
            except Exception as cancellation_error:
                summary["cancel_error_type"] = type(cancellation_error).__name__
        # Never print exception text: HTTP/provider errors can contain credentials.
    summary["http_calls"] = client.calls
    write_private(folder, "safe-summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    raise SystemExit(0 if summary.get("passed") else 1)


if __name__ == "__main__":
    main()
