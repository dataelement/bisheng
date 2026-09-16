#!/usr/bin/env python3
"""平台能力接线技能 —— 连通自检。

确认「接线能用」的前置条件:已登录平台、平台可达、凭据有效;若是在 `bisheng dev`(或托管环境)
起的进程里跑,再确认应用数据库的注入变量可用。缺配置时给出**一句能照着做的原因**,而不是堆栈。
脚本只用标准库,不含任何真实密钥(凭据从本机 ~/.bisheng/credentials.json 读)。

用法:
    python selfcheck.py

退出码:0 = 一切就绪;非 0 = 有一条前置条件没满足(原因见输出)。
"""

from __future__ import annotations

import json
import os
import sqlite3
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


def check_platform(profile: dict) -> None:
    base_url = profile["base_url"].rstrip("/")
    print(f"· 目标平台:{base_url}")
    req = urllib.request.Request(
        base_url + WHOAMI_PATH,
        headers={"Authorization": f"Bearer {profile['api_key']}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            fail(
                "平台不认这把密钥(已被吊销/过期,或所属服务账号已被停用)。",
                "先请管理员确认该服务账号仍启用,再重新签发一把密钥,然后 bisheng login。",
            )
        fail(f"平台返回 HTTP {exc.code}。", "确认平台地址正确、开放 API 能力已启用。")
    except urllib.error.URLError as exc:
        fail(f"连不上平台:{exc.reason}", "确认平台地址可达、在内网/VPN 里、没有代理拦截。")
    except TimeoutError:
        fail("连接平台超时。", "确认平台地址可达、网络通畅。")

    data = payload.get("data") if isinstance(payload, dict) else None
    name = (data or {}).get("actor_name") if isinstance(data, dict) else None
    print(f"✓ 已登录且平台可达,密钥有效。bisheng dev 注入的身份将是:{name or '(未命名)'}")


def check_app_db() -> None:
    """只在注入了变量的进程里(bisheng dev / 托管)检查;在普通 shell 里跑就说明并跳过。"""
    db_path = os.environ.get("BISHENG_APP_DB_PATH")
    db_url = os.environ.get("BISHENG_APP_DB_URL")
    if not db_path and not db_url:
        print(
            "· 未检测到 BISHENG_APP_DB_PATH / BISHENG_APP_DB_URL:当前不在 bisheng dev 或托管环境的进程里,跳过库检查。"
        )
        print("  (这两个变量只注入给应用进程;要检查它们,在应用里调用本脚本的 check_app_db()。)")
        return
    if not db_path:
        fail("只有 BISHENG_APP_DB_URL 没有 BISHENG_APP_DB_PATH,注入不完整。", "重启 bisheng dev;线上请报平台故障。")
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE IF NOT EXISTS _selfcheck (ok INTEGER)")
        conn.execute("DROP TABLE _selfcheck")
        conn.commit()
        conn.close()
    except sqlite3.Error as exc:
        fail(
            f"应用数据库 {db_path} 无法读写:{exc}",
            "本地:删除 <项目>/.bisheng/dev/ 后重启 bisheng dev;线上:报平台故障。",
        )
    print(f"✓ 应用数据库可读写:{db_path}")


def main() -> None:
    profile = load_current_profile()
    check_platform(profile)
    check_app_db()
    print("  可以按 SKILL.md 接线了。写完对照 §5 的自检清单再过一遍。")


if __name__ == "__main__":
    main()
