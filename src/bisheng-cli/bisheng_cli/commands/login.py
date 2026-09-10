"""`bisheng login` — prove the key works, then store it.

The command validates nothing itself. `GET /api/v2/auth/whoami` is the one
endpoint under `/api/v2` that requires no scope at all, which is exactly what
AC-06 asks for: logging in must succeed for a valid key even when no permission
has been ticked yet, so that "the key is wrong" and "the key lacks a scope" stay
two different diagnoses.

Order is load-bearing in two places.

**The probe runs before the key is sent.** If the open-capability layer is not
deployed, the run ends at the probe with exit 8 and the credential never leaves
the machine. `whoami` itself is always registered server-side (`open_api/api/router.py`
mounts the auth router unconditionally), so this is the only place the
"unusable in this environment" verdict can be produced.

**The delegate check runs before the write.** A delegate-only key is refused, and
refused *without* leaving a credential file behind — a stored key that every
later command rejects is worse than no key at all.

That check is the second line of defence, not the first. A key carrying
`delegate` does not get as far as reading its own scopes: `whoami` requires no
scope, so the platform's entrance gate waves it through and the delegation
resolver then rejects the call with `26016` (INV-31 / 伴生 PRD §4.2.4). The CLI
translates that code into the same refusal (`errors.py`), so `login` still ends
with "委托专用，另签一把" and no credential file. The scope check below survives
for the case the code path cannot cover: a platform that answers `whoami`
successfully for such a key.
"""

from __future__ import annotations

import getpass
import os
import sys
from collections.abc import Callable
from typing import Any, TextIO

from bisheng_cli import credentials
from bisheng_cli.commands import skills
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

    credentials.save_profile(
        base_url,
        {
            "base_url": base_url,
            "api_key": api_key,
            "key_mask": whoami.get("key_mask"),
            "tenant_id": whoami.get("tenant_id"),
            # Stored under the server's own field names. The previous spelling
            # (`service_account: {id, name}`) was F049's shape and no longer
            # exists on the wire; translating back into it here would put a
            # personal token's holder under a key that says "service account".
            "actor_kind": whoami.get("actor_kind"),
            "actor_id": whoami.get("actor_id"),
            "actor_name": whoami.get("actor_name"),
            "resource_owner": whoami.get("resource_owner"),
            "expires_at": whoami.get("expires_at"),
        },
        warn=emitter.warn,
    )

    _report(emitter, base_url, whoami)

    # AC-08: pull the developer skill packs now so a first-time developer never
    # has to know `skills sync` exists. This login already succeeded — a sync
    # failure downgrades to a warning inside run_after_login and never touches
    # the exit code or the result event below.
    skills.run_after_login(credentials.Profile(base_url=base_url, api_key=api_key), args, emitter)

    emitter.result(
        COMMAND,
        ok=True,
        exit_code=EXIT_OK,
        data={
            "base_url": base_url,
            "actor_kind": whoami.get("actor_kind"),
            "actor_id": whoami.get("actor_id"),
            "actor_name": whoami.get("actor_name"),
            "resource_owner": whoami.get("resource_owner"),
            "tenant_id": whoami.get("tenant_id"),
            "key_mask": whoami.get("key_mask"),
            "expires_at": whoami.get("expires_at"),
        },
    )
    return EXIT_OK


def _report(emitter: Emitter, base_url: str, whoami: dict[str, Any]) -> None:
    emitter.info(f"登录成功：{base_url}")

    # `actor_kind` / `actor_name` replace F049's `service_account: {id, name}`.
    # The kind is printed rather than assumed: a `bs-pat-` personal token
    # authenticates the same way and answers `natural_person`, and labelling its
    # holder "服务账号" would name the wrong subject.
    if whoami.get("actor_kind") == "natural_person":
        emitter.info(f"  登录主体: {whoami.get('actor_name') or '(未命名)'}（个人访问令牌）")
    else:
        emitter.info(f"  服务账号: {whoami.get('actor_name') or '(未命名)'}")

    owner_user_id = resource_owner_user_id(whoami)
    if owner_user_id is not None:
        # The server sends `resource_owner: {user_id}` and nothing else — the
        # name F049 used to include is gone from the contract, so there is no
        # honest way to print one. The id is what the platform actually knows,
        # and the pointer says where to turn it into a person.
        emitter.info(f"  资源归属人: 用户 #{owner_user_id}（姓名请在服务账号详情页核对）")
    else:
        # Not a display problem: a key with no resource owner cannot publish at
        # all — the first deploy is refused with 16205 rather than creating an
        # application owned by nobody. Saying so at login turns that into a
        # fixable sentence now instead of a rejection ten minutes later.
        emitter.info("  资源归属人: 平台未返回 —— 这把密钥还不能 deploy，请管理员在服务账号详情页指定归属人")

    # Printed only when the platform sends it. A single-tenant install has one
    # (Root) tenant, so the id is a constant the developer can do nothing with,
    # and "租户" is a word that deployment shape is supposed to never show. The
    # platform decides — the CLI cannot read the multi_tenant switch.
    if whoami.get("tenant_id") is not None:
        emitter.info(f"  租户: {whoami.get('tenant_id')}")
    emitter.info(f"  密钥: {whoami.get('key_mask') or '(平台未返回掩码)'}")
    emitter.info(f"  到期时间: {whoami.get('expires_at') or '未设置'}")
    emitter.info(f"  凭据已写入 {credentials.credentials_path()}（仅当前用户可读写）")


def resource_owner_user_id(whoami: dict[str, Any]) -> int | None:
    """`resource_owner.user_id`, or None when the platform sends no owner.

    Kept in one place because the shape moved once already: F049 sent
    ``{user_id, user_name}``, beta2's ``WhoamiResourceOwner`` carries ``user_id``
    alone (and the whole object is null for a credential without an owner).
    """
    owner = whoami.get("resource_owner")
    if isinstance(owner, dict) and owner.get("user_id") is not None:
        return owner.get("user_id")
    return None
