#!/usr/bin/env python3
# coding: utf-8
"""Call one run-scoped API action; the platform Agent authors the explanation."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

MAX_RESPONSE_BYTES = 10 * 1024 * 1024
MAX_EXPLANATION_BYTES = 1024 * 1024


class CliError(Exception):
    """A safe diagnostic containing no credentials or task file contents."""


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise CliError("参数无效或缺失；请使用 --help 查看参数要求。")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def reject_constant(value):
    raise ValueError("Non-finite JSON number")


def read_json(raw):
    return json.loads(raw.decode("utf-8"), parse_constant=reject_constant)


def redact(value, token):
    if isinstance(value, str):
        return value.replace(token, "[REDACTED]") if token else value
    if isinstance(value, list):
        return [redact(item, token) for item in value]
    if isinstance(value, dict):
        return {redact(key, token): redact(item, token) for key, item in value.items()}
    return value


def validate_base_url(value):
    if not value or any(char.isspace() or ord(char) < 32 for char in value):
        raise CliError("base-url 必须是无凭证的 HTTP(S) 服务地址。")
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError:
        raise CliError("base-url 无效。") from None
    if (parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or chr(92) in value
            or (port is not None and not 1 <= port <= 65535)):
        raise CliError("base-url 必须是无凭证、查询参数或片段的 HTTP(S) 服务地址。")
    if any(part in (".", "..") for part in urllib.parse.unquote(parsed.path).split("/")):
        raise CliError("base-url 路径不能包含相对路径段。")
    return value.rstrip("/")


def require_text(item, key):
    if not isinstance(item.get(key), str) or not item[key].strip():
        raise CliError("解释 JSON 的必需文本字段缺失或为空。")


def compact_response(result):
    """Keep receipts and analytical facts, omitting only duplicated raw orders."""
    summary = dict(result)
    facts = result.get("facts")
    if isinstance(facts, dict):
        facts = dict(facts)
        if isinstance(facts.get("history"), dict):
            facts["history"] = {key: value for key, value in facts["history"].items() if key != "records"}
        if isinstance(facts.get("items"), list):
            items = []
            for item in facts["items"]:
                if not isinstance(item, dict):
                    items.append(item)
                    continue
                item = dict(item)
                if isinstance(item.get("history"), dict):
                    item["history"] = {key: value for key, value in item["history"].items() if key != "records"}
                items.append(item)
            facts["items"] = items
        summary["facts"] = facts
    summary["output_compacted"] = True
    summary["omitted_fields"] = ["facts.history.records", "facts.items[].history.records"] if isinstance(facts, dict) else []
    return summary


def save_response(path, result, cli_path):
    target = Path(path).expanduser().resolve()
    if target in (cli_path, cli_path.parent.parent / "SKILL.md"):
        raise CliError("output-file 不能覆盖 Skill 或 CLI 文件。")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                         prefix=".forecast-response-", delete=False) as handle:
            temporary = Path(handle.name)
            os.chmod(temporary, 0o600)
            json.dump(result, handle, ensure_ascii=False, allow_nan=False)
            handle.write("\n")
        os.replace(temporary, target)
    except (OSError, ValueError):
        raise CliError("服务已响应，但完整响应文件保存失败；不要直接重跑业务动作。") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return str(target)


def load_explanation(path):
    try:
        with Path(path).open("rb") as handle:
            raw = handle.read(MAX_EXPLANATION_BYTES + 1)
        if len(raw) > MAX_EXPLANATION_BYTES:
            raise CliError("解释 JSON 文件过大。")
        explanation = read_json(raw)
    except (OSError, ValueError, UnicodeError):
        raise CliError("无法读取有效的 UTF-8 解释 JSON 文件。") from None
    expected = {"headline", "body", "factors", "limitations", "influences", "suggestions"}
    if not isinstance(explanation, dict) or set(explanation) != expected:
        raise CliError("解释 JSON 必须为包含 headline/body/factors/limitations/influences/suggestions 的对象。")
    for field in ("headline", "body"):
        require_text(explanation, field)
    limitations = explanation["limitations"]
    if not isinstance(limitations, list) or any(not isinstance(x, str) or not x.strip() for x in limitations):
        raise CliError("limitations 必须是非空字符串组成的数组。")
    if not limitations:
        raise CliError("limitations 不能是空数组。")
    schemas = {
        "factors": {"title", "value", "detail"},
        "influences": {"title", "detail", "evidence_refs"},
        "suggestions": {"spec", "customer", "reason", "evidence_refs"},
    }
    for field, keys in schemas.items():
        if not isinstance(explanation[field], list):
            raise CliError("factors/influences/suggestions 必须是数组。")
        if field != "suggestions" and not explanation[field]:
            raise CliError("factors/influences 不能是空数组；可记录证据缺口与观察。")
        for item in explanation[field]:
            if not isinstance(item, dict) or set(item) != keys:
                raise CliError("解释 JSON 的因素、影响或合同建议字段不符合合同。")
            for key in keys - {"evidence_refs"}:
                require_text(item, key)
            if "evidence_refs" in keys:
                refs = item["evidence_refs"]
                if not isinstance(refs, list) or not refs or any(not isinstance(x, str) or not x.strip() for x in refs):
                    raise CliError("每项影响或合同建议必须引用非空证据 ID 数组。")
    return explanation


def main(argv=None):
    token = ""
    try:
        parser = SafeParser(description=__doc__)
        parser.add_argument("--action", required=True, choices=("forecast", "history", "finalize"))
        parser.add_argument("--base-url", required=True, help="Task-provided HTTP(S) service base URL")
        parser.add_argument("--run-id", required=True, help="Task-provided run identifier")
        parser.add_argument("--token", required=True, help="Task-provided run capability; never printed")
        parser.add_argument("--explanation-file", help="Agent-authored UTF-8 JSON; required for finalize")
        parser.add_argument("--output-file", help="Save complete JSON locally; stdout omits duplicated raw order records")
        parser.add_argument("--timeout", type=float, default=30, help="Request timeout seconds (1-120; default 30)")
        args = parser.parse_args(argv)
        token = args.token
        base_url = validate_base_url(args.base_url)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", args.run_id):
            raise CliError("run-id 格式无效。")
        if not token or len(token) > 4096 or not all(33 <= ord(char) <= 126 for char in token):
            raise CliError("token 格式无效。")
        if not math.isfinite(args.timeout) or not 1 <= args.timeout <= 120:
            raise CliError("timeout 必须介于 1 和 120 秒之间。")
        if bool(args.explanation_file) != (args.action == "finalize"):
            raise CliError("只有 finalize 且必须提供 --explanation-file。")
        cli_path = Path(__file__).resolve()
        try:
            payload = {
                "skill_sha256": hashlib.sha256((cli_path.parent.parent / "SKILL.md").read_bytes()).hexdigest(),
                "cli_sha256": hashlib.sha256(cli_path.read_bytes()).hexdigest(),
            }
        except OSError:
            raise CliError("无法读取本地 Skill/CLI 文件以生成执行来源摘要。") from None
        if args.action == "finalize":
            payload["explanation"] = load_explanation(args.explanation_file)
        url = base_url + "/api/runs/" + urllib.parse.quote(args.run_id, safe="") + "/" + args.action
        request = urllib.request.Request(
            url, data=json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8"),
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=args.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            error.close()
            raise CliError("服务请求失败（HTTP %d）；请核对本次任务配置和执行状态。" % error.code) from None
        except (OSError, urllib.error.URLError):
            raise CliError("服务连接失败或超时；本轮结束，未自动重试。") from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise CliError("服务响应过大。")
        try:
            result = read_json(raw)
        except (ValueError, UnicodeError):
            raise CliError("服务未返回有效的 UTF-8 JSON。") from None
        if not isinstance(result, dict):
            raise CliError("服务响应必须是 JSON 对象。")
        safe_result = redact(result, token)
        output = safe_result
        if args.output_file:
            saved = save_response(args.output_file, safe_result, cli_path)
            output = compact_response(safe_result)
            output["output_file"] = redact(saved, token)
        print(json.dumps(output, ensure_ascii=False, allow_nan=False))
        return 1 if (result.get("ok") is False or result.get("status") in ("error", "api_error", "history_error", "failed")) else 0
    except CliError as error:
        print(json.dumps(redact({"ok": False, "status": "cli_error", "message": str(error)}, token), ensure_ascii=False))
        return 1
    except Exception:
        # Never expose exception strings, headers, file contents, or credentials.
        print(json.dumps({"ok": False, "status": "cli_error", "message": "执行失败；本轮结束，未自动重试。"}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
