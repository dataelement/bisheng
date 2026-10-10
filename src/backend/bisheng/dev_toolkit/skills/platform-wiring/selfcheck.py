#!/usr/bin/env python3
"""平台能力接线技能 —— 连通自检。

确认「接线能用」的前置条件:已登录平台、平台可达、凭据有效;若是在 `bisheng dev`(或托管环境)
起的进程里跑,再确认应用数据库的注入变量可用。装了平台 SDK 时还会把三件套各探一次:
SDK 版本是否在平台支持区间、身份注入读得到、检索与附件各调一次。
缺配置时给出**一句能照着做的原因**,而不是堆栈。

脚本只用标准库(SDK 是可选的),不含任何真实密钥(凭据从本机 ~/.bisheng/credentials.json 读)。

用法:
    python selfcheck.py                      # 在项目根跑(有 bisheng-app.yaml)
    python selfcheck.py http://127.0.0.1:8080/apps/my-app/   # 把 bisheng dev 打印的本地入口地址传进来(最稳)

检索、附件两步读的是**本脚本自己进程里的** BISHENG_APP_TOKEN / BISHENG_APP_STORAGE_DIR,
不是应用进程的。从另一个终端跑时这两个变量不存在:检索一步必然报缺应用运行期凭据,
附件一步要先在这个终端 export BISHENG_APP_STORAGE_DIR 才能过。

退出码:0 = 一切就绪(当前环境跑不了的步骤会明确说"跳过",不算失败);
       非 0 = 有一条前置条件没满足(原因见输出)。
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path

CREDENTIALS = Path.home() / ".bisheng" / "credentials.json"
WHOAMI_PATH = "/api/v2/auth/whoami"  # 平台唯一免鉴权域的身份查询端点,login 也用它校验密钥
VERSIONS_PATH = "/api/v1/dev-toolkit/versions"  # 平台声明的安装件版本与 SDK 兼容下限
SDK_INDEX_PATH = "/api/v1/dev-toolkit/simple/"  # 平台自己的 pip 简单索引

#: 本脚本自己的可选覆盖(**不是**平台注入的契约变量):`bisheng dev` 打印的本地入口地址。
DEV_ENTRY_ENV = "BISHENG_DEV_ENTRY_URL"


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


def _manifest_values(start: Path) -> dict[str, str]:
    """最近的 bisheng-app.yaml 里顶层的 `port:` 和 `slug:`。

    只认顶层的 `key: 值` 行,不引 YAML 库(本脚本零依赖)。
    """
    for directory in [start, *start.parents][:4]:
        manifest = directory / "bisheng-app.yaml"
        if not manifest.is_file():
            continue
        try:
            lines = manifest.read_text(encoding="utf-8").splitlines()
        except OSError:
            return {}
        values: dict[str, str] = {}
        for line in lines:
            matched = re.match(r"^(port|slug):\s*([A-Za-z0-9-]+)\s*(?:#.*)?$", line)
            if matched:
                values.setdefault(matched.group(1), matched.group(2))
        values["_dir"] = str(directory)
        return values
    return {}


def _dev_slug(values: dict[str, str]) -> str:
    """和 `bisheng dev` 同序:清单的 slug → `.bisheng/app.json` 里平台分配的 slug → `dev`。

    app.json 按平台地址分条记录;只有一条带 slug 时取它,多条时无法判断当前平台,退到 `dev`
    以外就会猜错,所以此时要把 dev 打印的地址作为参数传进来。
    """
    if values.get("slug"):
        return values["slug"]
    try:
        store = json.loads((Path(values.get("_dir", ".")) / ".bisheng" / "app.json").read_text(encoding="utf-8"))
        slugs = {entry.get("slug") for entry in (store.get("apps") or {}).values() if entry.get("slug")}
    except (OSError, ValueError, AttributeError):
        slugs = set()
    return slugs.pop() if len(slugs) == 1 else "dev"


def dev_entry_url(argv_url: str | None = None) -> str | None:
    """本地入口地址 —— **不是** `BISHENG_APP_PORT`。

    `bisheng dev` 起两个监听:**迷你代理**(本地入口,注入 `X-BiSheng-*` 身份头)和
    应用进程本身。`PORT` / `BISHENG_APP_PORT` 给的是**后者**,直连它的请求一个注入头
    都没有 —— 那正是本脚本要替开发者验的坑,拿它当探测地址等于自己跳进去。
    迷你代理和线上一样把应用挂在 `/apps/<slug>/` 下,前缀外的请求一律 404。

    按这个顺序找:命令行参数 → `BISHENG_DEV_ENTRY_URL` → 最近的 `bisheng-app.yaml`
    的 `port`(`bisheng dev` 不带 `--port` 时的默认入口端口)。都没有就返回 None,
    上层跳过这几步而不是判失败。最后一种按 `bisheng dev` 的规则补上 `/apps/<slug>`
    前缀;`bisheng dev` 带了 `--port`,或项目登记过多个平台时推不准,
    把它打印的完整地址作为参数传进来。
    """
    for candidate in (argv_url, os.environ.get(DEV_ENTRY_ENV)):
        text = (candidate or "").strip().rstrip("/")
        if text:
            return text if "://" in text else f"http://{text}"
    values = _manifest_values(Path.cwd())
    port = values.get("port")
    if not (port and port.isdigit()):
        return None
    return f"http://127.0.0.1:{port}/apps/{_dev_slug(values)}"


def check_sdk_auth(entry_url: str | None) -> dict | None:
    """经**本地入口**打一次应用的 /__whoami,拿回它收到的注入头并解析。

    返回注入头;当前环境没有可探测的入口时返回 None(跳过,不是失败)——
    与 `check_app_db` 在普通 shell 里的处理方式一致。
    """
    if not entry_url:
        print("· 没找到本地入口地址,跳过身份 / 检索 / 附件三步。")
        print("  想检查它们:在项目根(有 bisheng-app.yaml)执行 bisheng dev,")
        print("  再跑 python selfcheck.py <它打印的本地入口地址>。")
        return None

    from bisheng_sdk import auth, errors

    status, headers = _get_json(f"{entry_url}/__whoami")
    if status == 0:
        print(f"· 连不上本地入口 {entry_url},跳过身份 / 检索 / 附件三步。")
        print("  先在项目根执行 bisheng dev;用了 --port 的话把它打印的地址作为参数传给本脚本。")
        return None
    if status == 404:
        fail(
            f"{entry_url}/__whoami 返回 404:地址可能少了 /apps/<slug> 前缀或 slug 不对,也可能应用没有 /__whoami 端点。",
            "把 bisheng dev 打印的本地入口地址原样作为参数传给本脚本;仍是 404 就照 example-sdk/main.py 加一个 /__whoami 端点。",
        )
    if status != 200 or not headers:
        fail(
            f"{entry_url} 能连上,但没拿到注入头的回显(应用没有 /__whoami 端点,或它没返回 JSON)。",
            "照 example-sdk/main.py 加一个 /__whoami 端点后重试。",
        )
    try:
        identity = auth.from_headers(headers)
    except errors.PlatformIdentityMissingError:
        fail(
            f"{entry_url} 没有注入身份头 —— 多半指到了应用**自己**的端口"
            "(PORT / BISHENG_APP_PORT),而不是 bisheng dev 的本地入口。",
            "改用 bisheng dev 打印的本地入口地址(两个端口不是同一个)。",
        )
    print(f"✓ auth 可用:当前身份 {identity.user_name or identity.user_id}({identity.subject_kind})")
    return headers


def check_sdk_retrieve(headers: dict) -> None:
    """以刚拿到的访问者凭据检索一次。每类失败翻成一句话。"""
    from bisheng_sdk import auth, errors, retrieve

    with auth.bind(headers):
        try:
            retrieve.search("selfcheck", top_k=1)
        except errors.AppCredentialMissingError:
            # SDK 从**本脚本自己的**环境读 BISHENG_APP_TOKEN。本轮 bisheng dev 不注入它,
            # 而且就算注入了,也只注入给应用进程,不会出现在另开终端跑的本脚本里。
            fail(
                "本脚本进程里没有应用运行期凭据(BISHENG_APP_TOKEN)。本轮 bisheng dev 不注入它,"
                "另开终端跑本脚本时也读不到应用进程的变量;线上由平台在拉起容器前注入。",
                "本地:接线照写即可,检索的真实行为发布后用真实账号验;线上:重新上线应用,仍缺就报平台故障。",
            )
        except errors.VisitorCredentialMissingError:
            fail(
                "这次请求里没有访问者凭据(入口没有注入 X-BiSheng-Access-Token)。",
                "线上请管理员确认 app_runtime.obo_secret 已配置;本地确认走的是 bisheng dev 的入口地址。",
            )
        except errors.VisitorCredentialRejectedError:
            fail(
                "平台拒绝了这枚访问者凭据:已过期、被伪造,或签给了另一个应用。",
                "让用户刷新重进;检索的真实行为发布后用真实账号验。",
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
            "本脚本进程里没有附件存储句柄。SDK 从本脚本自己的环境读 BISHENG_APP_STORAGE_DIR,"
            "本轮 bisheng dev 也不注入它;线上则是没注入或已下线。",
            "本地:在跑本脚本的终端里 export BISHENG_APP_STORAGE_DIR=<项目>/.bisheng/attachments 后重跑"
            "(应用要用,在启动 bisheng dev 的终端里也 export 一次);线上请报平台故障。",
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
    headers = check_sdk_auth(dev_entry_url(sys.argv[1] if len(sys.argv) > 1 else None))
    # 三件套一起跳过:检索要上一步拿到的访问者头;没有入口就没有头。
    # 检索、附件读的是本脚本自己的环境变量(见模块 docstring)。跳过不是失败(见模块 docstring 的退出码)。
    if headers is not None:
        check_sdk_retrieve(headers)
        check_sdk_storage()
    print("  可以按 SKILL.md 接线了。写完对照 §7 的自检清单再过一遍。")


if __name__ == "__main__":
    main()
