#!/usr/bin/env python3
"""平台能力接线技能 —— 连通自检。

确认「接线能用」的前置条件:已登录平台、平台可达、凭据有效;若是在 `bisheng dev`(或托管环境)
起的进程里跑,再确认应用数据库的注入变量可用。装了平台 SDK 时还会把三件套各探一次:
SDK 版本是否在平台支持区间、身份注入读得到、检索与附件各调一次。
缺配置时给出**一句能照着做的原因**,而不是堆栈。

脚本只用标准库(SDK 是可选的),不含任何真实密钥(凭据从本机 ~/.bisheng/credentials.json 读)。

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
VERSIONS_PATH = "/api/v1/dev-toolkit/versions"  # 平台声明的安装件版本与 SDK 兼容下限
SDK_INDEX_PATH = "/api/v1/dev-toolkit/simple/"  # 平台自己的 pip 简单索引


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


def platform_base(profile: dict) -> str:
    """应用进程里以注入的平台地址为准;普通 shell 里退回 login 的那个。"""
    return (os.environ.get("BISHENG_PLATFORM_API_BASE") or profile["base_url"]).rstrip("/")


def _get_json(url: str, headers: dict | None = None) -> tuple[int, dict]:
    """GET 一个 JSON,返回 (状态码, 载荷)。连不上时状态码为 0。"""
    req = urllib.request.Request(url, headers={"Accept": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        return exc.code, {}
    except (urllib.error.URLError, TimeoutError, ValueError):
        return 0, {}


def _version_tuple(text: str) -> tuple[int, int, int]:
    """ "0.10.0" > "0.9.9" —— 逐段取整数比,不做字符串比较。"""
    parts = (text or "0").split(".")[:3]
    numbers = []
    for part in parts:
        digits = "".join(ch for ch in part if ch.isdigit())
        numbers.append(int(digits) if digits else 0)
    while len(numbers) < 3:
        numbers.append(0)
    return tuple(numbers)  # type: ignore[return-value]


def check_sdk_installed(base_url: str) -> str | None:
    """SDK 装了没。没装不算致命 —— 读头接线同样合法,只是三件套这几步跳过。"""
    try:
        import bisheng_sdk
    except ImportError:
        print("· 未安装平台 SDK(bisheng_sdk),跳过三件套检查。")
        print(f"  想装:pip install --extra-index-url {base_url}{SDK_INDEX_PATH} bisheng-sdk")
        return None
    print(f"✓ 平台 SDK 已安装:bisheng-sdk {bisheng_sdk.__version__}")
    return bisheng_sdk.__version__


def check_sdk_compatible(base_url: str, sdk_version: str) -> None:
    """平台声明的兼容下限 vs 本机 SDK 版本 —— 不兼容时两个版本都打出来。"""
    status, payload = _get_json(base_url + VERSIONS_PATH)
    if status == 0:
        fail("连不上平台的版本信息端点。", "确认平台地址可达、在内网/VPN 里、没有代理拦截。")
    if status == 404:
        fail(
            "这个平台没有安装件分发端点(开放能力层未部署,或平台版本太老)。",
            "请管理员确认平台已启用开放能力层并升级到支持 SDK 的版本。",
        )
    sdk = (payload.get("data") or {}).get("sdk") if isinstance(payload, dict) else None
    if not sdk or not sdk.get("min_compatible"):
        fail(
            "这个平台没有发布 SDK 安装件(版本信息里 sdk 为空)。",
            "请管理员在发布时执行 scripts/pack_sdk_wheel.sh 并提交产物。",
        )
    minimum = sdk["min_compatible"]
    if _version_tuple(minimum) > _version_tuple(sdk_version):
        fail(
            f"本机 SDK {sdk_version} 低于该平台支持的最低版本 {minimum}。",
            f"从当前平台重新取:pip install -U --extra-index-url {base_url}{SDK_INDEX_PATH} bisheng-sdk",
        )
    print(f"✓ SDK 版本兼容:本机 {sdk_version} ≥ 平台要求的 {minimum}")


def check_sdk_auth() -> dict:
    """经本地入口打一次应用的 /__whoami,拿回它收到的注入头并解析。"""
    from bisheng_sdk import auth, errors

    app_port = os.environ.get("BISHENG_APP_PORT") or os.environ.get("PORT")
    if not os.environ.get("BISHENG_APP_ID") or not app_port:
        fail(
            "当前不在 bisheng dev(或托管)起的应用进程里,拿不到注入身份。",
            "在项目根执行 bisheng dev,再用它打印的本地入口地址访问应用;身份检查要在应用进程内做。",
        )
    status, headers = _get_json(f"http://127.0.0.1:{app_port}/__whoami")
    if status != 200 or not headers:
        fail(
            "应用没有回显注入头(没有 /__whoami 端点,或应用没起来)。",
            "照 example-sdk/main.py 加一个 /__whoami 端点,或先确认应用已启动。",
        )
    try:
        identity = auth.from_headers(headers)
    except errors.PlatformIdentityMissingError:
        fail(
            "这次请求里没有平台注入的身份头(直连了应用端口,没走入口代理)。",
            "访问 bisheng dev 打印的本地入口地址,而不是应用自己的端口。",
        )
    print(f"✓ auth 可用:当前身份 {identity.user_name or identity.user_id}({identity.subject_kind})")
    return headers


def check_sdk_retrieve(headers: dict) -> None:
    """以刚拿到的访问者凭据检索一次。每类失败翻成一句话。"""
    from bisheng_sdk import auth, errors, retrieve

    with auth.bind(headers):
        try:
            retrieve.search("selfcheck", top_k=1)
        except errors.VisitorCredentialMissingError:
            fail(
                "这次请求里没有访问者凭据(入口没有注入 X-BiSheng-Access-Token)。",
                "线上请管理员确认 app_runtime.obo_secret 已配置;本地确认走的是 bisheng dev 的入口地址。",
            )
        except errors.VisitorCredentialRejectedError:
            fail(
                "平台拒绝了应用侧的访问凭据。**本轮平台尚未受理这类凭据**(本地是 dev 自签句柄、"
                "线上是入口签发的短时令牌),不是你的密钥有问题,换密钥没有用。",
                "接线照写即可;要确认平台侧是否已就绪,问管理员统一检索门面是否已部署。",
            )
        except errors.ScopeMissingError:
            fail("这把密钥没有知识库读取能力位。", "请管理员给该服务账号的密钥勾上 knowledge:read 后重试。")
        except errors.BishengSdkError as exc:
            fail(f"检索没通过:{exc.message}", exc.next_step)
    print("✓ retrieve 可用:以当前访问者的身份检索成功")


def check_sdk_storage() -> None:
    """往附件空间写一个探针文件再删掉。"""
    from bisheng_sdk import errors, storage

    probe = "_selfcheck/probe.txt"
    try:
        storage.put(probe, b"selfcheck")
        storage.stat(probe)
        storage.delete(probe)
    except errors.StorageHandleMissingError:
        fail(
            "没有附件存储句柄。**本轮 bisheng dev 还不会注入本地附件目录**,线上则是没注入或已下线。",
            "本地临时自造一个再起应用:export BISHENG_APP_STORAGE_DIR=<项目>/.bisheng/attachments;线上请报平台故障。",
        )
    except errors.BishengSdkError as exc:
        fail(f"附件存取没通过:{exc.message}", exc.next_step)
    print("✓ storage 可用:附件写入、读元信息、删除各一次")


def main() -> None:
    profile = load_current_profile()
    check_platform(profile)
    check_app_db()

    base_url = platform_base(profile)
    sdk_version = check_sdk_installed(base_url)
    if sdk_version is None:
        print("  没装 SDK 也可以按 SKILL.md 读头接线;装上后再跑一次本脚本会多检查三件套。")
        raise SystemExit(1)

    check_sdk_compatible(base_url, sdk_version)
    headers = check_sdk_auth()
    check_sdk_retrieve(headers)
    check_sdk_storage()
    print("  可以按 SKILL.md 接线了。写完对照 §7 的自检清单再过一遍。")


if __name__ == "__main__":
    main()
