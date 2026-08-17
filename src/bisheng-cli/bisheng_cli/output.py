"""Dual-shape output: machine-readable NDJSON on stdout, human text on stderr.

Why the split (design D2): a local coding agent is the primary caller, and the
only way it can do `bisheng deploy --wait --json | jq -c 'select(.event=="stage")'`
is if *every* line on stdout parses as JSON. Interleaving progress text there
blows up the pipeline on its first line. Human text therefore always goes to
stderr — in `--json` mode and outside it — so a person watching the terminal still
sees the run while the pipe stays clean.

The masker lives here because every exit from the process funnels through this
module; a masker attached to any single call site is one that some other call
site will forget.
"""

from __future__ import annotations

import io
import json
import re
import sys
import time
from typing import Any, TextIO

# Server-side `stage` values are the machine-readable truth (design D6); this
# table is *display only* and deliberately unordered. Two consequences that are
# easy to get wrong:
#   - an unknown stage is printed verbatim, never an error — the server is free
#     to add stages without breaking the CLI;
#   - the dict order says nothing about execution order. The server reordered
#     secret_scan relative to precheck_* once already; a CLI that asserts an
#     order turns the next reordering into a client-side bug.
STAGE_LABELS: dict[str, str] = {
    "received": "已接收",
    "secret_scan": "安全扫描",
    "precheck_manifest": "应用声明校验",
    "precheck_build": "依赖构建",
    "precheck_probe": "启动探活",
    "version_recorded": "版本已记录",
    "approval_created": "审批单已生成",
    "approved": "审批通过",
    "publishing": "发布中",
    "online": "已上线",
    "pending_online": "待上线",
}

_MASK_PATTERNS = (
    # Service-account keys. The tail is greedy on purpose: a partially matched
    # key is still a leaked key.
    (re.compile(r"bs-sak-[A-Za-z0-9_\-]+"), "bs-sak-****"),
    (re.compile(r"(?i)(authorization\W{0,4}bearer)\s+\S+"), r"\1 ****"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9_\-\.]{8,}"), "Bearer ****"),
)

_MILESTONES = (25, 50, 75, 100)


def mask(text: str) -> str:
    """Redact key material from any string on its way out of the process."""
    for pattern, replacement in _MASK_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def wrap_stream(stream: TextIO) -> TextIO:
    """Make `stream` survive non-UTF-8 consoles.

    A Windows console defaults to GBK. Printing a Chinese hint that happens to
    contain one character outside that codepage raises UnicodeEncodeError, and
    the user sees a Python traceback instead of "缺 app:manage 位" — the crash
    hides the very message it was crashing on.
    """
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        return stream
    except (AttributeError, ValueError, io.UnsupportedOperation):
        pass
    buffer = getattr(stream, "buffer", None)
    if buffer is None:
        return stream
    return io.TextIOWrapper(buffer, encoding="utf-8", errors="replace", line_buffering=True)


def stage_label(stage: str) -> str:
    """Display phrase for a server stage; unknown stages pass through verbatim."""
    return STAGE_LABELS.get(stage, stage)


class Emitter:
    """Single exit point for everything the CLI says.

    Invariant relied upon by callers: exactly one `result` event per command run,
    and it is the last line on stdout. An agent that reads only the final line
    can therefore always reach a verdict, including on the crash path.
    """

    def __init__(
        self,
        *,
        json_mode: bool = False,
        quiet: bool = False,
        verbose: bool = False,
        is_tty: bool | None = None,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
    ) -> None:
        self.json_mode = json_mode
        self.quiet = quiet
        self.verbose = verbose
        self._stdout = stdout if stdout is not None else sys.stdout
        self._stderr = stderr if stderr is not None else sys.stderr
        if is_tty is None:
            is_tty = bool(getattr(self._stderr, "isatty", lambda: False)())
        self.is_tty = is_tty
        self._result_emitted = False
        self._last_milestone: dict[str, int] = {}

    # ---- machine events -------------------------------------------------

    def _emit(self, payload: dict[str, Any]) -> None:
        if not self.json_mode:
            return
        line = json.dumps(payload, ensure_ascii=False, sort_keys=False, default=str)
        self._stdout.write(mask(line) + "\n")
        self._stdout.flush()

    def stage(
        self,
        command: str,
        stage: str,
        status: str,
        *,
        failure: dict[str, Any] | None = None,
        **extra: Any,
    ) -> None:
        payload: dict[str, Any] = {
            "event": "stage",
            "command": command,
            "stage": stage,
            "status": status,
            "ts": _now(),
        }
        if failure is not None:
            payload["failure"] = failure
        payload.update(extra)
        self._emit(payload)
        label = stage_label(stage)
        self.info(f"[{status}] {label}")

    def progress(self, command: str, phase: str, sent_bytes: int, total_bytes: int) -> None:
        percent = int(sent_bytes * 100 / total_bytes) if total_bytes else 100
        if not self._should_report(phase, percent):
            return
        self._emit(
            {
                "event": "progress",
                "command": command,
                "phase": phase,
                "sent_bytes": sent_bytes,
                "total_bytes": total_bytes,
            }
        )
        self.info(f"已上传 {_mb(sent_bytes)} / {_mb(total_bytes)} ({percent}%)")

    def result(
        self,
        command: str,
        ok: bool,
        exit_code: int,
        *,
        data: dict[str, Any] | None = None,
        failure: dict[str, Any] | None = None,
    ) -> None:
        if self._result_emitted:
            return
        self._result_emitted = True
        self._emit(
            {
                "event": "result",
                "command": command,
                "ok": ok,
                "exit_code": exit_code,
                "data": data or {},
                "failure": failure,
            }
        )

    @property
    def result_emitted(self) -> bool:
        return self._result_emitted

    # ---- human text -----------------------------------------------------

    def info(self, text: str) -> None:
        if self.quiet:
            return
        self._write_human(text)

    def warn(self, text: str) -> None:
        self._write_human(f"警告: {text}")

    def error(self, text: str) -> None:
        self._write_human(text)

    def debug(self, text: str) -> None:
        if not self.verbose:
            return
        self._write_human(f"[debug] {text}")

    def _write_human(self, text: str) -> None:
        self._stderr.write(mask(text) + "\n")
        self._stderr.flush()

    # ---- helpers --------------------------------------------------------

    def _should_report(self, phase: str, percent: int) -> bool:
        """Throttle progress on non-TTY callers.

        A pipe has no cursor to rewrite, so a per-chunk progress line becomes
        thousands of lines in the agent's transcript. Milestones keep the signal
        without the flood.
        """
        if self.is_tty:
            return True
        last = self._last_milestone.get(phase, -1)
        reached = max((m for m in _MILESTONES if percent >= m), default=None)
        if reached is None or reached <= last:
            return False
        self._last_milestone[phase] = reached
        return True


def format_scan_hits(hits: list[dict[str, Any]]) -> str:
    """Render secret-scan hits as `file:line` plus the rule name — never a value.

    The server withholds even a redacted value on purpose. Reading the offending
    line back out of the local file to "complete" the report would hand back
    exactly what the platform refused to hand over.
    """
    lines = []
    for hit in hits:
        location = f"{hit.get('file', '?')}:{hit.get('line', '?')}"
        rule = hit.get("rule_id") or hit.get("name_i18n_key") or "unknown-rule"
        lines.append(f"  {location}  规则 {rule}")
    return "\n".join(lines)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _mb(size: int) -> str:
    return f"{size / (1024 * 1024):.1f} MB"
