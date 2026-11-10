#!/usr/bin/env python3
"""Push the WeCom (企业微信) address book into bisheng **without** the commercial Gateway.

This is the no-Gateway alternative to the Gateway's ``WechatScheduled`` job. It
pulls departments + members through the existing :class:`WeComProvider` (Redis
token cache, distributed token lock, rate-limit back-off and errcode bucketing
are already implemented there) and posts one payload to the same HMAC-signed
endpoint the Gateway uses::

    POST /api/v1/internal/sso/gateway-wecom-org-sync

That endpoint upserts/archives departments, upserts members, disables
``source=wecom`` users missing from the authoritative snapshot, and writes one
``org_sync_log`` row (watch it under 系统管理 → 组织同步 in the platform).

Signing contract (same as the Gateway)::

    X-Signature: hex_lower( SHA256( METHOD + "\\n" + PATH + "\\n" + raw_body ) )
    secret     = sso_sync.gateway_hmac_secret   (backend config.yaml)

An empty secret is rejected by the backend (fail-closed), so it must be set.

Run from ``src/backend/`` (or ``/app`` inside the backend container), with the
backend ``config.yaml`` present. **Dry-run is the default** — ``--apply`` is
required to write, because a full snapshot archives absent departments and
disables absent users::

    python scripts/wecom_org_sync.py --dry-run           # fetch + report only
    python scripts/wecom_org_sync.py --apply             # push, config from org_sync_config
    WECOM_CORP_ID=... WECOM_CORP_SECRET=... WECOM_AGENT_ID=... \\
        python scripts/wecom_org_sync.py --apply

Docker deployment (script already ships in the backend image)::

    docker compose exec -T backend python scripts/wecom_org_sync.py --dry-run

Credentials: ``--corpid``/``--corpsecret``/``--agent-id`` or their
``WECOM_*`` env vars first; otherwise the active ``org_sync_config`` row with
``provider='wecom'`` (create it with ``POST /api/v1/org-sync/configs``).

Scheduling: run it daily/weekly from cron or a systemd timer, e.g.::

    15 2 * * * cd /opt/bisheng/src/backend && config=config.yaml \\
        .venv/bin/python scripts/wecom_org_sync.py --apply >> /var/log/bisheng-wecom-sync.log 2>&1

Exit codes: ``0`` success, ``1`` partial (some members/departments failed),
``3`` missing credentials or HMAC secret, ``4`` transport/API failure.

This script intentionally does **not** call ``initialize_app_context``: it only
needs the lazily-created database context and Redis (``get_redis_client``
registers ``RedisManager`` on demand, and ``WeComProvider`` degrades to a
no-cache token if Redis is unreachable). Initialising the full context would
make the script hard-fail on MinIO/Elasticsearch being down, which the sync
itself does not depend on.

Department leaders: WeCom's ``is_leader_in_dept`` (aligned with ``department``)
is carried through and sent as ``department_admin_external_ids``. The backend
reconciles only grants whose ``grant_source='sso'``; admin-console (manual)
grants are never touched. A leader removed upstream loses the app's grant on
the next run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections.abc import Sequence
from typing import Any

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

import httpx  # noqa: E402
from loguru import logger  # noqa: E402

from bisheng.common.errcode.base import BaseErrorCode  # noqa: E402
from bisheng.common.services.config_service import settings  # noqa: E402
from bisheng.common.utils.hmac_signature import compute_hmac_signature  # noqa: E402
from bisheng.core.context.manager import close_app_context  # noqa: E402
from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.org_sync.domain.models.org_sync import (  # noqa: E402
    OrgSyncConfigDao,
    decrypt_auth_config,
)
from bisheng.org_sync.domain.providers.wecom import WeComProvider  # noqa: E402
from bisheng.org_sync.domain.services.wecom_payload import (  # noqa: E402
    build_department_items,
    build_member_items,
    build_payload,
)
from bisheng.sso_sync.domain.constants import WECOM_SOURCE  # noqa: E402

SYNC_PATH = "/api/v1/internal/sso/gateway-wecom-org-sync"
# Re-exported under the script's historical name; tests import it from here.
SOURCE = WECOM_SOURCE


# ---------------------------------------------------------------------------
# Pure helpers (kept free of I/O so they can be unit-tested)
# ---------------------------------------------------------------------------
def chunked(items: Sequence[Any], size: int) -> list[list[Any]]:
    """Split ``items`` into chunks of ``size``; ``size <= 0`` means one chunk."""
    if size <= 0:
        return [list(items)]
    return [list(items[i : i + size]) for i in range(0, len(items), size)]


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------
async def resolve_auth(args: argparse.Namespace) -> tuple[dict, int | None]:
    """Resolve WeCom credentials from CLI/env, falling back to org_sync_config."""
    corpid = args.corpid or os.getenv("WECOM_CORP_ID")
    corpsecret = args.corpsecret or os.getenv("WECOM_CORP_SECRET")
    agent_id = args.agent_id or os.getenv("WECOM_AGENT_ID")
    if corpid and corpsecret and agent_id:
        auth: dict[str, Any] = {
            "corpid": corpid,
            "corpsecret": corpsecret,
            "agent_id": agent_id,
        }
        allow = args.allow_dept_ids
        if allow:
            auth["allow_dept_ids"] = [int(x) for x in allow]
        return auth, None

    # Scripts run outside the FastAPI request lifecycle, so the global tenant
    # filter has no active scope; bypass it and filter by tenant_id explicitly.
    with bypass_tenant_filter():
        configs = await OrgSyncConfigDao.aget_list(tenant_id=args.tenant_id, status="active")
    chosen = next((c for c in configs if c.provider == "wecom"), None)
    if chosen is None:
        raise ConfigError(
            "no WeCom credentials: pass --corpid/--corpsecret/--agent-id "
            "(or WECOM_CORP_ID/WECOM_CORP_SECRET/WECOM_AGENT_ID), or create an "
            f"active org_sync_config with provider='wecom' for tenant {args.tenant_id}"
        )
    auth = decrypt_auth_config(chosen.auth_config)
    auth["_config_id"] = chosen.id
    logger.info("using org_sync_config id={} ({})", chosen.id, chosen.config_name)
    return auth, chosen.id


def resolve_secret(raw: str | None) -> str:
    secret = raw or os.getenv("BISHENG_GATEWAY_HMAC_SECRET") or settings.sso_sync.gateway_hmac_secret
    if not secret:
        raise ConfigError(
            "no HMAC secret: set sso_sync.gateway_hmac_secret in config.yaml, or pass "
            "--secret / BISHENG_GATEWAY_HMAC_SECRET (the backend rejects unsigned "
            "pushes with 19301 when its own secret is empty)"
        )
    return secret


class ConfigError(RuntimeError):
    """Missing WeCom credentials or HMAC secret."""


class PushError(RuntimeError):
    """The backend rejected a signed payload (HTTP or business status)."""


async def push_payload(
    base_url: str,
    secret: str,
    header_name: str,
    payload: dict,
    *,
    timeout: float,
) -> dict:
    """Sign and POST one payload; return the ``data`` block of the response."""
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    signature = compute_hmac_signature("POST", SYNC_PATH, raw, secret)
    headers = {"Content-Type": "application/json", header_name: signature}
    url = base_url.rstrip("/") + SYNC_PATH
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, content=raw, headers=headers)
    try:
        body = response.json()
    except ValueError:
        body = {"status_code": response.status_code, "status_message": response.text[:500]}
    if response.status_code >= 400 or body.get("status_code", 200) != 200:
        raise PushError(
            f"push failed: http={response.status_code} "
            f"status_code={body.get('status_code')} message={body.get('status_message')}"
        )
    return body.get("data") or {}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("BISHENG_INTERNAL_URL", "http://127.0.0.1:7860"),
        help="bisheng backend base URL (default: env BISHENG_INTERNAL_URL or http://127.0.0.1:7860)",
    )
    parser.add_argument(
        "--secret",
        help="HMAC secret; defaults to env BISHENG_GATEWAY_HMAC_SECRET, then config.yaml",
    )
    parser.add_argument("--corpid", help="WeCom CorpId (or env WECOM_CORP_ID)")
    parser.add_argument("--corpsecret", help="WeCom app Secret (or env WECOM_CORP_SECRET)")
    parser.add_argument("--agent-id", help="WeCom AgentId (or env WECOM_AGENT_ID)")
    parser.add_argument(
        "--allow-dept-ids",
        nargs="+",
        help="WeCom root department ids to sync (default: [1], i.e. the whole company)",
    )
    parser.add_argument(
        "--tenant-id",
        type=int,
        default=1,
        help="Tenant used to look up org_sync_config when credentials are not given (default: 1)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=0,
        help="Members per request (default 0 = single request). When set, leading batches "
        "are incremental and the last one repeats the full roster with full_snapshot=true.",
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Never send full_snapshot=true: upsert only. Absent departments/users are NOT "
        "archived or disabled (default is a full authoritative sync).",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Actually push to bisheng. Without it the script only fetches and reports (dry-run).",
    )
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Explicit dry-run (same as omitting --apply).",
    )
    parser.add_argument("--timeout", type=float, default=600.0, help="HTTP timeout seconds (default 600)")
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> int:
    auth, _config_id = await resolve_auth(args)
    secret = resolve_secret(args.secret)

    logger.info("fetching WeCom departments and members ...")
    provider = WeComProvider(auth)
    departments = await provider.fetch_departments()
    members = await provider.fetch_members()
    logger.info("fetched {} departments, {} members", len(departments), len(members))

    ts = int(time.time())
    department_items = build_department_items(departments)
    member_items = build_member_items(members, ts)

    if not args.apply:
        preview = build_payload(
            department_items, member_items, ts, full_snapshot=True, trigger_type="scheduled"
        )
        size = len(json.dumps(preview, ensure_ascii=False).encode("utf-8"))
        print(
            json.dumps(
                {
                    "mode": "dry-run",
                    "target": args.base_url.rstrip("/") + SYNC_PATH,
                    "departments": len(department_items),
                    "members": len(member_items),
                    "disabled_members": sum(1 for m in member_items if m["account_disabled"]),
                    "payload_bytes": size,
                    "sample_department": department_items[:1],
                    "sample_member": member_items[:1],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    chunks = chunked(member_items, args.batch_size)
    header_name = settings.sso_sync.signature_header
    totals = {"member_ok": 0, "member_fail": 0, "dept_updated": 0, "dept_archived": 0, "absent_disabled": 0}
    failures: list[dict] = []

    for index, chunk in enumerate(chunks, start=1):
        last = index == len(chunks)
        # Contract: only the authoritative (last) envelope reconciles absences,
        # and it must carry the complete member roster, not just its own chunk.
        batch_members = member_items if (last and len(chunks) > 1) else chunk
        payload = build_payload(
            department_items,
            batch_members,
            ts,
            full_snapshot=last and not args.incremental,
            # Cron/script runs are logged distinctly from Gateway pushes.
            trigger_type="scheduled",
        )
        logger.info(
            "push batch {}/{}: {} members, full_snapshot={}",
            index,
            len(chunks),
            len(batch_members),
            payload["departments"]["full_snapshot"],
        )
        data = await push_payload(args.base_url, secret, header_name, payload, timeout=args.timeout)

        dept = data.get("department_result") or {}
        totals["dept_updated"] += int(dept.get("applied_upsert") or 0)
        totals["dept_archived"] += int(dept.get("applied_remove") or 0)
        totals["member_ok"] += int(data.get("member_sync_ok") or 0)
        totals["member_fail"] += int(data.get("member_sync_fail") or 0)
        totals["absent_disabled"] += int(data.get("absent_wecom_users_disabled") or 0)
        failures.extend(data.get("member_errors") or [])
        for err in dept.get("errors") or []:
            failures.append({"scope": "department", **err})

    print(
        json.dumps(
            {
                "mode": "incremental" if args.incremental else "full-snapshot",
                "departments": len(department_items),
                "members": len(member_items),
                "batches": len(chunks),
                **totals,
                "member_errors": failures[:50],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if (totals["member_fail"] or failures) else 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)

    async def _main() -> int:
        try:
            return await _run(args)
        finally:
            await close_app_context()

    try:
        return asyncio.run(_main())
    except ConfigError as exc:
        logger.error("{}", exc)
        return 3
    except PushError as exc:
        logger.error("{}", exc)
        return 4
    except httpx.HTTPError as exc:
        logger.error("HTTP request failed (WeCom API or bisheng backend): {}", exc)
        return 4
    except BaseErrorCode as exc:
        # The instance message (not the class-level Msg) carries the WeCom
        # errcode/errmsg; the two most common setup failures get an explicit hint.
        message = str(getattr(exc, "message", exc))
        hint = ""
        if "60020" in message:
            hint = " — 该出口 IP 未加入企业微信「应用 → 企业可信IP」"
        elif "60011" in message:
            hint = " — 应用「通讯录可见范围」未覆盖要同步的部门"
        logger.error("WeCom error [{}]: {}{}", getattr(exc, "code", "?"), message, hint)
        return 4


if __name__ == "__main__":
    sys.exit(main())
