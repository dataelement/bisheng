"""`bisheng deploy` — package, upload, then follow the server's own pipeline.

The single most important fact about this command is that **`POST /apps/deploy`
answers synchronously with most of the verdicts**. Ownership, the size gate, the
unpack gate, manifest validation, local-reference validation and the in-flight /
pending-online gates all run before the deployment row exists (F055 design §4.1
①). Only after they pass does the server insert `stage=received` and hand back a
`deployment_id`. So the failure a first-time user hits most often — a manifest
missing a field — never appears in the polling payload. Code that waits for a
`stage=precheck_manifest` failure event waits until the timeout.

Two smaller rules with outsized consequences:

**The app id is saved the moment HTTP 200 arrives**, not when the pipeline
succeeds. A first deploy whose precheck fails has still created a draft
application on the platform and been assigned an id; saving only on success means
the developer's next attempt creates a *second* application, and the build page
fills with identically named drafts.

**`details` and `hints` are forwarded untouched.** They are the entire input a
local agent has for repairing the failure by itself; summarising them is the
difference between an agent that fixes the manifest and one that asks a human.
"""

from __future__ import annotations

import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO

from bisheng_cli import agent_skills, credentials, packaging, project
from bisheng_cli import ignore as ignore_rules
from bisheng_cli.cli import confirm
from bisheng_cli.commands import skills
from bisheng_cli.errors import (
    EXIT_APPROVAL_EXCEPTION,
    EXIT_CANCELLED,
    EXIT_OK,
    EXIT_PENDING_ONLINE,
    EXIT_REJECTED,
    EXIT_UNKNOWN_CODE,
    EXIT_USAGE,
    EXIT_WAIT_TIMEOUT,
    EXIT_WITHDRAWN,
    CliError,
    error_from_platform,
)
from bisheng_cli.http import UPLOAD_READ_TIMEOUT, PlatformClient
from bisheng_cli.output import Emitter, format_scan_hits

COMMAND = "deploy"
DEPLOY_PATH = "/api/v2/apps/deploy"
DEPLOYMENT_PATH = "/api/v2/apps/deployments/{deployment_id}"
PACKAGE_FIELD = "package"

# 2s, then ×1.5 every five polls, capped at 10s. A long connection is not an
# option here: nginx caps `proxy_read_timeout` at 300s while an approval is a
# human action that can take days.
POLL_INTERVAL_START = 2.0
POLL_BACKOFF_EVERY = 5
POLL_BACKOFF_FACTOR = 1.5
POLL_INTERVAL_MAX = 10.0

ONLINE_APP_STATE = "已上线"
PENDING_REASONS = {"capacity", "deploy_failed"}

# The six values `approval.status` can hold. The last two matter most: an
# application deleted mid-flight cancels its approval, and an approval whose
# approver set resolves to empty is parked as an exception. Neither will ever
# reach a decision, so a `--wait` that does not recognise them polls to the
# timeout and then prints "this is not a failure, keep waiting" about a request
# that is already dead.
APPROVAL_TERMINALS: dict[str, int] = {
    "rejected": EXIT_REJECTED,
    "withdrawn": EXIT_WITHDRAWN,
    "cancelled": EXIT_CANCELLED,
    "exception": EXIT_APPROVAL_EXCEPTION,
}
APPROVAL_PASSED = ("executed", "approved")

DETAIL_PAGE = "应用详情页 · 发布"
TRACKING_PATHS = (
    f"在 {DETAIL_PAGE} 查看审批与上线进度",
    "用 MCP 的应用状态工具查询",
    "重新执行 bisheng deploy --wait 继续等待",
)


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _monotonic() -> float:
    return time.monotonic()


def next_interval(interval: float, polls_done: int) -> float:
    """Backoff step. Split out so the schedule is testable without 30 polls."""
    if polls_done and polls_done % POLL_BACKOFF_EVERY == 0:
        return min(interval * POLL_BACKOFF_FACTOR, POLL_INTERVAL_MAX)
    return interval


@dataclass
class Outcome:
    exit_code: int
    kind: str


# ---- upload -------------------------------------------------------------


class _ProgressReader:
    """File wrapper that reports upload progress as httpx streams it.

    A file object rather than `read_bytes()` is what keeps a 50 MB package out of
    memory; the counter is bolted on here so that the streaming property is not
    quietly traded away for a progress bar.
    """

    def __init__(self, fh: BinaryIO, total: int, emitter: Emitter) -> None:
        self._fh = fh
        self._total = total
        self._emitter = emitter
        self._sent = 0
        self._last_percent = -1

    def read(self, size: int = -1) -> bytes:
        chunk = self._fh.read(size)
        if chunk:
            self._sent += len(chunk)
            percent = int(self._sent * 100 / self._total) if self._total else 100
            if percent != self._last_percent:
                self._last_percent = percent
                self._emitter.progress(COMMAND, "upload", self._sent, self._total)
        return chunk

    def seek(self, offset: int, whence: int = 0) -> int:
        position = self._fh.seek(offset, whence)
        if position == 0:
            self._sent = 0
            self._last_percent = -1
        return position

    def tell(self) -> int:
        return self._fh.tell()

    def fileno(self) -> int:
        return self._fh.fileno()


# ---- command ------------------------------------------------------------


def run(args: Any, emitter: Emitter) -> int:
    profile = credentials.load_current()
    base_url = profile.base_url
    root = project.find_project_root(args.path)
    project.load_manifest(root)

    ignore_result = ignore_rules.collect_files(root)
    for note in ignore_result.notes:
        emitter.info(note)

    with tempfile.TemporaryDirectory(prefix="bisheng-cli-") as tmp:
        package_path = Path(tmp) / "package.tar.gz"
        package_stat = packaging.build_package(root, ignore_result, package_path)

        if args.dry_run:
            emitter.info(packaging.format_size_report(package_stat, packaging.DEFAULT_LIMITS))
            emitter.info("--dry-run：本地校验与打包已完成，未上传，平台上什么都没有创建。")
            emitter.result(
                COMMAND,
                ok=True,
                exit_code=EXIT_OK,
                data={
                    "dry_run": True,
                    "entry_count": package_stat.entry_count,
                    "compressed_bytes": package_stat.compressed_bytes,
                    "raw_bytes": package_stat.raw_bytes,
                    "excluded_count": package_stat.excluded_count,
                    "package_sha256": package_stat.sha256,
                },
            )
            return EXIT_OK

        client = PlatformClient(
            base_url,
            api_key=profile.api_key,
            trust_env=not getattr(args, "no_proxy", False),
            timeout=getattr(args, "timeout", None),
            emitter=emitter,
        )
        target_app_id = project.resolve_app_id(root, base_url, args.app_id)
        state: dict[str, Any] = {
            "deployment_id": None,
            "app_id": target_app_id,
            "version_id": None,
            "entry_url": None,
            "stage": None,
            "app_state": None,
            "pending_reason": None,
            "approval": None,
        }
        try:
            with client:
                _check_size(client, emitter, package_stat)
                _confirm_target(args, emitter, root, base_url, target_app_id)
                accepted = _upload(client, emitter, args, package_path, package_stat, target_app_id)
                package_path.unlink(missing_ok=True)
                _accept(emitter, root, base_url, accepted, state)
                _ensure_agents_pointer(args, emitter, root, base_url)
                return _follow(client, emitter, args, state)
        except CliError as exc:
            failure = getattr(exc, "server_failure", None) or exc.as_failure(stage=state["stage"])
            _print_scan_hits(emitter, failure)
            emitter.result(COMMAND, ok=False, exit_code=exc.exit_code, data=state, failure=failure)
            raise


def _ensure_agents_pointer(args: Any, emitter: Emitter, root: Path, base_url: str) -> None:
    """Leave a pointer to the skill packs in the project's AGENTS.md (best effort).

    Deploy is the right moment for two reasons: the project certainly exists by
    now (login often runs before there is one), and a project that deploys is a
    project whose next editor — a teammate, a different AI tool, the same
    developer in six weeks — needs to know the hosting contract exists.

    Placed *after* the platform accepts the upload, not before it. "This project
    deploys to this platform" is the fact the pointer asserts, and until the
    platform has taken the package that fact is still a guess — a failed deploy
    must leave the developer's tree exactly as it found it.

    Best effort in the strict sense: this touches the developer's repository, so
    it appends and never rewrites, it is skippable with --no-agents-note, and any
    failure is a debug line. Nothing here may stand between a valid project and
    its deploy.
    """
    if getattr(args, "no_agents_note", False) or getattr(args, "dry_run", False):
        # --dry-run promises "nothing was created"; that has to include the
        # developer's own working tree, not just the platform.
        return
    try:
        outcome = agent_skills.ensure_project_pointer(root, skills.skills_root(base_url), list(skills.DEFAULT_PACKS))
    except Exception as exc:  # deliberately broad: a note must never block a deploy
        emitter.debug(f"AGENTS.md 指针未写入：{exc.__class__.__name__}")
        return
    status = outcome.get("status")
    if status == "created":
        emitter.info(f"已创建 {agent_skills.POINTER_FILE}，写明技能包位置（供其它 AI 工具查阅，建议提交到仓库）")
    elif status == "appended":
        emitter.info(f"已在 {agent_skills.POINTER_FILE} 追加技能包位置说明（建议提交到仓库）")
    elif status == "failed":
        emitter.debug(f"AGENTS.md 指针未写入：{outcome.get('reason')}")


def _check_size(client: PlatformClient, emitter: Emitter, package_stat: packaging.PackageStat) -> None:
    """Self-check against the server's ceilings — advisory when they are unknown.

    `deploy-limits` failing must never be able to block a deploy: the endpoint
    may not be deployed yet, or the hop may be flaky, and a soft check that can
    kill the main flow is worse than no check. The server's 16201 stays the
    authority either way.
    """
    limits = packaging.fetch_limits(client)
    if limits.degraded:
        emitter.warn("未能从平台取到包体上限，已按内置默认值提示并继续上传；是否超限最终由平台判定。")
    else:
        packaging.check_limits(package_stat, limits)
    emitter.info(packaging.format_size_report(package_stat, limits))


def _confirm_target(args: Any, emitter: Emitter, root: Path, base_url: str, app_id: str | None) -> None:
    """Misdirection guard for an iterative deploy.

    Pointing at an application owned by somebody else is refused by the server
    (16205). Pointing at *another application of your own* is not — it silently
    updates that one. In an unattended run this printed line is the only guard
    that exists, which is why it is printed even when nobody can answer it.
    """
    if not app_id:
        return
    entry = project.read_app_ref(root, base_url) or {}
    name = entry.get("app_name") or "(名称未知，本次发布后回填)"
    emitter.info(f"目标应用：{name}（标识 {app_id}）")
    emitter.info("若这不是要更新的应用，请中止并用 --app-id 指定正确的目标。")
    if emitter.is_tty and not args.yes:
        if not confirm("确认更新以上应用?", assume_yes=False, is_tty=True, flag_name="--yes"):
            raise CliError(
                "已按用户要求取消本次发布",
                exit_code=EXIT_USAGE,
                next_step="用 --app-id 指定正确的目标应用后重试。",
            )


def _upload(
    client: PlatformClient,
    emitter: Emitter,
    args: Any,
    package_path: Path,
    package_stat: packaging.PackageStat,
    app_id: str | None,
) -> dict[str, Any]:
    fields: dict[str, str] = {"confirm_schema_change": "true" if args.confirm_schema_change else "false"}
    if app_id:
        fields["app_id"] = app_id
    emitter.info(f"开始上传（{package_stat.entry_count} 个条目，sha256 {package_stat.sha256[:12]}…）")
    with open(package_path, "rb") as fh:
        reader = _ProgressReader(fh, package_stat.compressed_bytes, emitter)
        data = client.post_json(
            DEPLOY_PATH,
            files={PACKAGE_FIELD: (package_path.name, reader, "application/gzip")},
            data=fields,
            read_timeout=UPLOAD_READ_TIMEOUT,
        )
    return data or {}


def _accept(emitter: Emitter, root: Path, base_url: str, accepted: dict[str, Any], state: dict[str, Any]) -> None:
    state["deployment_id"] = accepted.get("deployment_id")
    state["app_id"] = accepted.get("app_id") or state["app_id"]
    state["version_id"] = accepted.get("version_id")
    state["entry_url"] = accepted.get("entry_url")

    if state["app_id"]:
        # Written now, not on success — see the module docstring.
        project.save_app_ref(
            root,
            base_url,
            app_id=str(state["app_id"]),
            app_name=accepted.get("app_name"),
            slug=accepted.get("slug"),
            last_deployment_id=state["deployment_id"],
        )
    emitter.info(f"平台已接收，应用标识 {state['app_id']}，发布单 {state['deployment_id']}")
    if state["entry_url"]:
        emitter.info(f"入口地址：{state['entry_url']}")
    else:
        # A first deploy has no application row yet at this instant, so there is
        # genuinely no address to print. Printing "None" would read as a broken
        # URL; the polling payload carries the address as soon as it exists.
        emitter.info(f"入口地址暂不可得，请在 {DETAIL_PAGE} 获取。")


def _print_scan_hits(emitter: Emitter, failure: Any) -> None:
    if not isinstance(failure, dict):
        return
    details = failure.get("details")
    hits = details.get("hits") if isinstance(details, dict) else None
    if isinstance(hits, list) and hits:
        emitter.error("扫描命中（平台不回显命中的值，CLI 也不会从本地文件补读）:")
        emitter.error(format_scan_hits(hits))


# ---- polling ------------------------------------------------------------


def _follow(client: PlatformClient, emitter: Emitter, args: Any, state: dict[str, Any]) -> int:
    deployment_id = state["deployment_id"]
    if not deployment_id:
        # Nothing to poll: the server accepted the package but gave no handle.
        emitter.warn("平台未返回发布单标识，无法跟踪进度。")
        emitter.result(COMMAND, ok=True, exit_code=EXIT_OK, data=state)
        return EXIT_OK

    path = DEPLOYMENT_PATH.format(deployment_id=deployment_id)
    wait = bool(args.wait)
    deadline = float(args.wait_timeout)
    interval = POLL_INTERVAL_START
    polls = 0
    started = _monotonic()
    last_stage: str | None = None

    while True:
        payload = client.get_json(path) or {}
        _absorb(payload, state)
        stage = payload.get("stage")
        status = payload.get("status")
        failure = payload.get("failure")

        if stage and stage != last_stage and status != "failed":
            last_stage = stage
            emitter.stage(COMMAND, stage, "running")

        if status == "failed" or failure:
            emitter.stage(COMMAND, stage or "unknown", "failed", failure=failure)
            raise _failure_error(stage, failure)

        outcome = _terminal(payload, wait=wait)
        if outcome is not None:
            return _report_outcome(emitter, outcome, state)

        if _monotonic() - started >= deadline:
            return _report_outcome(emitter, Outcome(EXIT_WAIT_TIMEOUT, "timeout"), state)

        _sleep(interval)
        polls += 1
        interval = next_interval(interval, polls)


def _absorb(payload: dict[str, Any], state: dict[str, Any]) -> None:
    # ``entry_url`` is absorbed here as of the F055 write-back: it used to exist
    # only on the POST response, where a first deploy is still a draft and the
    # value was almost always null exactly when it mattered. Now every poll
    # carries it, so `--wait` can print a real address on success.
    for key in ("stage", "app_state", "pending_reason", "approval", "entry_url"):
        if payload.get(key) is not None:
            state[key] = payload[key]
    if payload.get("app_id"):
        state["app_id"] = payload["app_id"]


def _terminal(payload: dict[str, Any], *, wait: bool) -> Outcome | None:
    approval = payload.get("approval") or {}
    approval_status = str(approval.get("status") or "").lower()

    # Checked before anything else and in both modes: these two never reach a
    # decision, so continuing to poll can only burn the timeout.
    if approval_status in APPROVAL_TERMINALS:
        return Outcome(APPROVAL_TERMINALS[approval_status], approval_status)

    status = payload.get("status")
    if not wait:
        if status == "waiting_approval":
            return Outcome(EXIT_OK, "waiting_approval")
        if status == "succeeded":
            return Outcome(EXIT_OK, "online")
        return None

    stage = payload.get("stage")
    if stage == "pending_online" or payload.get("pending_reason") in PENDING_REASONS:
        return Outcome(EXIT_PENDING_ONLINE, "pending_online")
    if stage == "online" or payload.get("app_state") == ONLINE_APP_STATE or status == "succeeded":
        return Outcome(EXIT_OK, "online")
    return None


def _failure_error(stage: str | None, failure: Any) -> CliError:
    raw = failure if isinstance(failure, dict) else {}
    code = raw.get("code")
    message = str(raw.get("message") or "")
    if isinstance(code, int):
        err = error_from_platform(code, message, details=raw.get("details"), hints=raw.get("hints"))
    else:
        err = CliError(
            f"发布在阶段 {stage or '未知'} 失败：{message}",
            exit_code=EXIT_UNKNOWN_CODE,
            next_step="按平台给出的信息处置；若无法判断，请带上发布单标识联系平台支持。",
            details=raw.get("details"),
            hints=raw.get("hints"),
        )
    if raw:
        # The server's five-tuple, byte for byte. `as_failure()` would rebuild a
        # near-identical dict, and "near-identical" is exactly what an agent
        # cannot rely on.
        err.server_failure = raw  # type: ignore[attr-defined]
    return err


def _report_outcome(emitter: Emitter, outcome: Outcome, state: dict[str, Any]) -> int:
    approval = state.get("approval") or {}
    instance_id = approval.get("instance_id") or "(平台未返回标识)"

    if outcome.kind == "waiting_approval":
        emitter.info(f"审批单已生成：{instance_id}。审批是人工动作，可能跨天。")
        emitter.info("跟踪方式：")
        for path in TRACKING_PATHS:
            emitter.info(f"  - {path}")
    elif outcome.kind == "online":
        emitter.info("发布通过并已上线。")
        if state.get("entry_url"):
            emitter.info(f"入口地址：{state['entry_url']}")
        else:
            emitter.info(f"入口地址请在 {DETAIL_PAGE} 获取。")
    elif outcome.kind == "rejected":
        # Full text, never truncated: the reason is the entire instruction for
        # what to change before resubmitting.
        emitter.error(f"审批被驳回。驳回理由：{approval.get('reject_reason') or '(平台未返回理由)'}")
    elif outcome.kind == "withdrawn":
        emitter.error(f"审批单已被撤回（撤回操作在 {DETAIL_PAGE}）。")
    elif outcome.kind == "pending_online":
        emitter.error(f"应用处于待上线状态，成因：{state.get('pending_reason')}。")
        emitter.error(f"可由应用归属人在 {DETAIL_PAGE} 手动上线，或等待资源释放后重试。")
    elif outcome.kind == "cancelled":
        emitter.error("目标应用已被删除，该审批单已取消——这一单永远不会有结论。")
        emitter.error("下一步: 重新执行 deploy 创建新应用（先删掉 .bisheng/app.json 里的过期标识）。")
    elif outcome.kind == "exception":
        emitter.error("平台未能解析出审批人，该审批单已置为异常——这一单永远不会有结论。")
        emitter.error("下一步: 联系平台管理员处理审批异常；改代码或重新发布都不会让它继续。")
    elif outcome.kind == "timeout":
        emitter.error(f"等待超时（--wait-timeout）。这不是失败：审批单 {instance_id} 仍在流转。")
        for path in TRACKING_PATHS:
            emitter.error(f"  - {path}")

    emitter.result(COMMAND, ok=outcome.exit_code == EXIT_OK, exit_code=outcome.exit_code, data=state)
    return outcome.exit_code
