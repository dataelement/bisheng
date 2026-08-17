"""`bisheng login` — prove the key works, then store it.

The command validates nothing itself. `GET /api/v2/auth/whoami` is the one
endpoint under `/api/v2` that requires no scope at all, which is exactly what
AC-06 asks for: logging in must succeed for a valid key even when no permission
has been ticked yet, so that "the key is wrong" and "the key lacks a scope" stay
two different diagnoses.

Order is load-bearing in two places.

**The probe runs before the key is sent.** If the open-capability layer is not
deployed, the run ends at the probe with exit 8 and the credential never leaves
the machine. `whoami` itself is always registered server-side (F049 keeps the
service-account module on unconditionally), so this is the only place the
"unusable in this environment" verdict can be produced.

**The delegate check runs before the write.** A delegate-only key is refused, and
refused *without* leaving a credential file behind — a stored key that every
later command rejects is worse than no key at all.
"""

from __future__ import annotations

import getpass
import os
import sys
from collections.abc import Callable
from typing import Any, TextIO

from bisheng_cli import credentials
from bisheng_cli.errors import EXIT_OK, EXIT_USAGE, CliError, delegate_refusal
from bisheng_cli.http import PlatformClient, probe
from bisheng_cli.output import Emitter

COMMAND = "login"
WHOAMI_PATH = "/api/v2/auth/whoami"
API_KEY_ENV = "BISHENG_API_KEY"
DELEGATE_SCOPE = "delegate"

_PROMPT = "请输入服务账号密钥（输入不回显）: "


def resolve_api_key(
    args: Any,
    *,
    stdin: TextIO | None = None,
    prompt: Callable[[str], str] | None = None,
) -> str:
    """`--api-key` > `BISHENG_API_KEY` > `--api-key-stdin` > hidden TTY input.

    The flag comes first because an explicit argument should always win, and last
    because it is the one that lands in shell history — the other three exist so
    that it does not have to be used.

    Nothing here invents a key. With no source and nobody to ask, the command
    refuses (exit 2); guessing produces an anonymous request whose 26001 sends
    the user looking at the platform instead of at their own invocation.
    """
    flag = getattr(args, "api_key", None)
    if flag and flag.strip():
        return flag.strip()

    env_value = os.environ.get(API_KEY_ENV)
    if env_value and env_value.strip():
        return env_value.strip()

    stream = stdin if stdin is not None else sys.stdin

    if getattr(args, "api_key_stdin", False):
        value = (stream.read() if stream is not None else "").strip()
        if value:
            return value
        raise CliError(
            "--api-key-stdin 没有从标准输入读到任何内容",
            exit_code=EXIT_USAGE,
            next_step="把密钥通过管道送入，例如 echo $KEY | bisheng login <平台地址> --api-key-stdin。",
        )

    if stream is not None and bool(getattr(stream, "isatty", lambda: False)()):
        value = (prompt or getpass.getpass)(_PROMPT).strip()
        if value:
            return value

    raise CliError(
        "没有提供服务账号密钥",
        exit_code=EXIT_USAGE,
        next_step=f"用 --api-key、环境变量 {API_KEY_ENV} 或 --api-key-stdin 提供密钥（非交互环境下必须用后两者之一）。",
    )


def run(args: Any, emitter: Emitter) -> int:
    base_url = credentials.normalise_base_url(args.base_url)
    api_key = resolve_api_key(args)

    client = PlatformClient(
        base_url,
        api_key=api_key,
        trust_env=not getattr(args, "no_proxy", False),
        timeout=getattr(args, "timeout", None),
        emitter=emitter,
    )
    with client:
        probe(client)
        whoami = client.get_json(WHOAMI_PATH) or {}

    scopes = whoami.get("scopes") or []
    if DELEGATE_SCOPE in scopes:
        raise delegate_refusal()

    account = whoami.get("service_account") or {}
    owner = whoami.get("resource_owner")
    credentials.save_profile(
        base_url,
        {
            "base_url": base_url,
            "api_key": api_key,
            "key_mask": whoami.get("key_mask"),
            "tenant_id": whoami.get("tenant_id"),
            "service_account": account or None,
            "resource_owner": owner,
            "expires_at": whoami.get("expires_at"),
        },
        warn=emitter.warn,
    )

    _report(emitter, base_url, whoami, account, owner)
    emitter.result(
        COMMAND,
        ok=True,
        exit_code=EXIT_OK,
        data={
            "base_url": base_url,
            "service_account": account or None,
            "resource_owner": owner,
            "tenant_id": whoami.get("tenant_id"),
            "key_mask": whoami.get("key_mask"),
            "expires_at": whoami.get("expires_at"),
        },
    )
    return EXIT_OK


def _report(emitter: Emitter, base_url: str, whoami: dict[str, Any], account: dict[str, Any], owner: Any) -> None:
    emitter.info(f"登录成功：{base_url}")
    emitter.info(f"  服务账号: {account.get('name') or '(未命名)'}")
    if isinstance(owner, dict) and owner:
        emitter.info(f"  资源归属人: {owner.get('user_name') or owner.get('user_id')}")
    else:
        # Degraded until F049 adds `resource_owner` to WhoamiResponse (design
        # D14). Printing the pointer beats omitting the line: this account owns
        # every app the key will publish, and picking the wrong one is the exact
        # mistake the issuing form warns about.
        emitter.info("  资源归属人: 平台当前版本未返回该字段，请在服务账号详情页确认")
    emitter.info(f"  租户: {whoami.get('tenant_id')}")
    emitter.info(f"  密钥: {whoami.get('key_mask') or '(平台未返回掩码)'}")
    emitter.info(f"  到期时间: {whoami.get('expires_at') or '未设置'}")
    emitter.info(f"  凭据已写入 {credentials.credentials_path()}（仅当前用户可读写）")
