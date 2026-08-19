"""Static checks for the app-factory runtime layer under docker-compose (F054).

Reads the resolved compose document on stdin (``docker compose config
--format json``) and cross-checks it against the two standalone packages'
``config.py``. Driven by ``verify-app-runtime-compose.sh``; kept as a separate
file rather than a heredoc so it stays lintable and diffable.

The one thing worth restating here: both processes are *fail-closed but
still healthy*. A typo'd variable name is indistinguishable from an unset one,
and an unset one leaves the process pointing at ``127.0.0.1`` with an empty
HMAC secret. Nothing in a runtime health check can see that — which is why the
gate has to be a static one.

Env read points are extracted from the AST rather than by importing, so this
never executes deployment code and does not care about ``sys.path``.

Exit code = number of failed assertions (0 = all good), capped at 120 so it
stays a valid process exit status.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

GREEN = "\033[0;32m"
RED = "\033[0;31m"
BOLD = "\033[1m"
RESET = "\033[0m"

#: service name → path of the module that owns its environment contract.
SERVICES = {
    "app-proxy": ("src/app-proxy/app_proxy/config.py", "APP_PROXY_"),
    "runtime-manager": ("src/runtime-manager/runtime_manager/config.py", "RTM_"),
}

#: The application network. ``runtime_manager.config.DEFAULT_NETWORK`` and the
#: raw Docker API ``NetworkMode`` both use this literal name, so compose must
#: pin ``name:`` — otherwise compose prefixes it with the project name and every
#: container create fails with "network not found".
APP_NETWORK = "bisheng-apps"

#: Both runtime-layer services must keep the implicit network too: nginx
#: resolves ``app-proxy`` and backend resolves ``runtime-manager`` by service
#: name, and declaring any ``networks:`` on a service drops it off ``default``.
DEFAULT_NETWORK = "default"


class Report:
    def __init__(self) -> None:
        self.failures = 0

    def ok(self, message: str) -> None:
        print(f"  {GREEN}✓{RESET} {message}")

    def bad(self, message: str) -> None:
        print(f"  {RED}✗{RESET} {message}")
        self.failures += 1

    def check(self, condition: bool, ok_message: str, bad_message: str) -> bool:
        if condition:
            self.ok(ok_message)
        else:
            self.bad(bad_message)
        return condition


def env_read_points(module: Path) -> set[str]:
    """Every environment variable name this module actually reads.

    Matches the ``_env_str`` / ``_env_int`` / ``_env_bool`` / ``_env_float`` /
    ``_env_path`` helpers plus the raw ``os.getenv`` / ``os.environ.get`` forms,
    taking the first positional argument when it is a literal string.
    """
    tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        func = node.func
        if isinstance(func, ast.Name):
            matched = func.id.startswith("_env") or func.id == "getenv"
        elif isinstance(func, ast.Attribute):
            matched = func.attr in {"getenv", "get"}
        else:
            matched = False
        if not matched:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            names.add(first.value)
    return names


def module_constant_tuple(module: Path, name: str) -> tuple[str, ...]:
    """Read a module-level ``NAME: tuple = ("A", "B")`` without importing."""
    tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
    for node in tree.body:
        targets: list[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        elif isinstance(node, ast.Assign):
            targets, value = list(node.targets), node.value
        if value is None:
            continue
        if not any(isinstance(t, ast.Name) and t.id == name for t in targets):
            continue
        if isinstance(value, (ast.Tuple, ast.List)):
            return tuple(
                element.value
                for element in value.elts
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            )
    return ()


def check_env_contract(report: Report, repo_root: Path, doc: dict) -> None:
    for service, (rel_path, prefix) in SERVICES.items():
        module = repo_root / rel_path
        if not module.is_file():
            report.bad(f"{service}: 找不到 {rel_path}")
            continue
        spec = doc.get("services", {}).get(service)
        if spec is None:
            report.bad(f"{service}: compose 里没有这个 service")
            continue

        declared = {k for k in (spec.get("environment") or {}) if k.startswith(prefix)}
        read = {n for n in env_read_points(module) if n.startswith(prefix)}

        # ① 正向：compose 写的每个变量都必须有人读。
        unread = sorted(declared - read)
        report.check(
            not unread,
            f"{service}: {len(declared)} 个 {prefix}* 变量全部能在 {rel_path} 找到读取点",
            f"{service}: compose 声明了没人读的变量 {unread} —— 进程会静默用默认值 "
            f"（{rel_path} 顶部的契约表是唯一真相）",
        )

        # ② 反向：config.py 标注为必填的变量，compose 必须给。
        required = set(module_constant_tuple(module, "REQUIRED_ENV"))
        required |= set(module_constant_tuple(module, "CONTAINERISED_REQUIRED_ENV"))
        if not required:
            report.bad(f"{service}: {rel_path} 没有 REQUIRED_ENV，反向校验失效")
            continue
        missing = sorted(required - declared)
        report.check(
            not missing,
            f"{service}: {len(required)} 个必填变量 compose 全部给了",
            f"{service}: compose 缺少必填变量 {missing}",
        )


def check_networks(report: Report, doc: dict) -> None:
    networks = doc.get("networks") or {}
    entry = networks.get(APP_NETWORK)
    report.check(
        entry is not None,
        f"顶级 networks: 声明了 {APP_NETWORK}",
        f"顶级 networks: 缺少 {APP_NETWORK} —— runtime-manager 只读不建这张网"
        f"（docker_backend.py「网络由部署方创建」），每次 deploy 会 404 network not found",
    )
    if entry is not None:
        actual = entry.get("name")
        report.check(
            actual == APP_NETWORK,
            f"{APP_NETWORK} 的实名固定为 {actual}（未被项目名前缀污染）",
            f"{APP_NETWORK} 实名是 {actual!r}，应为 {APP_NETWORK!r}："
            f"应用容器走裸 Docker API 建，NetworkMode 用的是真名，对不上就连不上",
        )

    for service in SERVICES:
        spec = doc.get("services", {}).get(service)
        if spec is None:
            continue
        attached = set((spec.get("networks") or {}).keys())
        report.check(
            APP_NETWORK in attached,
            f"{service} 接在 {APP_NETWORK} 上",
            f"{service} 没接 {APP_NETWORK}：探活 / 反代都要直连应用容器的 bridge IP",
        )
        report.check(
            DEFAULT_NETWORK in attached,
            f"{service} 仍在 {DEFAULT_NETWORK} 上（服务名解析可用）",
            f"{service} 掉出了 {DEFAULT_NETWORK}：写了 networks: 就不再自动接 default，"
            f"nginx→app-proxy / backend→runtime-manager 的服务名会解析不了",
        )


def check_data_root_mapping(report: Report, doc: dict) -> None:
    """RTM_DATA_ROOT（容器内）与 RTM_HOST_DATA_ROOT（宿主）必须指同一份数据。

    HostConfig.Binds 由**宿主 dockerd** 解释。只给容器内路径的话，宿主会在同名
    路径下凭空建一个空目录：应用起得来、探活过得去、SQLite 落在别处。
    """
    spec = doc.get("services", {}).get("runtime-manager")
    if spec is None:
        return
    env = spec.get("environment") or {}
    in_container = env.get("RTM_DATA_ROOT")
    on_host = env.get("RTM_HOST_DATA_ROOT")
    if not report.check(
        bool(on_host),
        "runtime-manager 给了 RTM_HOST_DATA_ROOT",
        "runtime-manager 缺 RTM_HOST_DATA_ROOT：容器化的 manager 交给 dockerd 的 bind "
        "会是容器内路径，数据落在宿主的同名空目录里",
    ):
        return
    report.check(
        on_host.startswith("/"),
        f"RTM_HOST_DATA_ROOT={on_host} 是绝对路径",
        f"RTM_HOST_DATA_ROOT={on_host} 不是绝对路径，dockerd 会拒绝所有 bind",
    )

    sources = [
        v.get("source") for v in (spec.get("volumes") or []) if isinstance(v, dict) and v.get("target") == in_container
    ]
    report.check(
        on_host in sources,
        f"RTM_HOST_DATA_ROOT 与挂到 {in_container} 的宿主源一致（{on_host}）",
        f"RTM_HOST_DATA_ROOT={on_host} 与挂到 {in_container} 的宿主源 {sources} 对不上 —— "
        f"两者必须写成同一个表达式，否则改一处就分叉",
    )


def main() -> int:
    repo_root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    doc = json.load(sys.stdin)

    report = Report()
    check_env_contract(report, repo_root, doc)
    print(f"{BOLD}[4/4] 托管应用网络与数据根映射{RESET}")
    check_networks(report, doc)
    check_data_root_mapping(report, doc)
    return min(report.failures, 120)


if __name__ == "__main__":
    sys.exit(main())
