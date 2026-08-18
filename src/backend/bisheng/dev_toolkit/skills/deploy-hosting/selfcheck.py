#!/usr/bin/env python3
"""部署纳管技能 —— 连通自检。

在开发者自己的机器上跑,确认「能部署」的前置条件都就绪:已登录平台、平台可达、凭据有效。
缺配置时给出**一句能照着做的原因**,而不是一串堆栈。脚本只用标准库,不含任何真实密钥
(凭据从本机 ~/.bisheng/credentials.json 读,不在这里硬编码)。

用法:
    python selfcheck.py

退出码:0 = 一切就绪;非 0 = 有一条前置条件没满足(原因见输出)。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

CREDENTIALS = Path.home() / ".bisheng" / "credentials.json"
WHOAMI_PATH = "/api/v2/auth/whoami"  # 平台唯一免鉴权域的身份查询端点,login 也用它校验密钥


def fail(reason: str, next_step: str) -> None:
    """打印可读原因 + 下一步,并以非零码退出。绝不抛堆栈。"""
    print(f"✗ 没通过:{reason}")
    print(f"  下一步:{next_step}")
    raise SystemExit(1)


def load_current_profile() -> dict:
    if not CREDENTIALS.exists():
        fail("本机还没有平台凭据(未登录)。", "先执行 bisheng login <平台地址> --api-key bs-sak-…")
    try:
        store = json.loads(CREDENTIALS.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        fail(f"凭据文件读不了或格式坏了:{exc}", f"检查或删除 {CREDENTIALS} 后重新 bisheng login。")
    current = store.get("current")
    profile = (store.get("profiles") or {}).get(current) if current else None
    if not profile or not profile.get("base_url") or not profile.get("api_key"):
        fail("凭据里没有可用的当前平台。", "重新执行 bisheng login <平台地址>。")
    return profile


def main() -> None:
    profile = load_current_profile()
    base_url = profile["base_url"].rstrip("/")
    api_key = profile["api_key"]

    print(f"· 目标平台:{base_url}")
    req = urllib.request.Request(
        base_url + WHOAMI_PATH,
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            fail("平台不认这把密钥(可能已被吊销或过期)。", "找管理员重新签发一把服务账号密钥,再 bisheng login。")
        fail(f"平台返回 HTTP {exc.code}。", "确认平台地址正确、开放 API 能力已启用。")
    except urllib.error.URLError as exc:
        fail(f"连不上平台:{exc.reason}", "确认平台地址可达、在内网/VPN 里、没有代理拦截。")
    except TimeoutError:
        fail("连接平台超时。", "确认平台地址可达、网络通畅。")

    data = payload.get("data") if isinstance(payload, dict) else None
    owner = (data or {}).get("resource_owner") if isinstance(data, dict) else None
    owner_name = owner.get("name") if isinstance(owner, dict) else None
    print("✓ 已登录且平台可达,密钥有效。" + (f" 资源归属人:{owner_name}" if owner_name else ""))
    print("  可以 bisheng deploy 了。部署前请对照 SKILL.md §5 的自检清单再过一遍。")


if __name__ == "__main__":
    main()
