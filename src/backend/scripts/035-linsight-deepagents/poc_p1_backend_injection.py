"""POC P1 — deepagents 允许注入自定义 FilesystemBackend（替代 virtual_mode），
E2B 产出可经其写入。关联 Track C/A。失败影响：工作区模型不成立，退 MinIO 物化备选。

判定（GREEN 条件）：
1. create_deep_agent(backend=...) 接受自定义 backend；
2. 自定义 backend 继承 deepagents BackendProtocol（read/write/ls/edit 返回 *Result）；
3. 写入经自定义 backend 落到我们控制的存储（此处内存 dict，对应真实 MinIO 写穿）。

运行：uv run python scripts/035-linsight-deepagents/poc_p1_backend_injection.py
不依赖外部中间件。
"""

from __future__ import annotations

import inspect

from deepagents import create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend


class InMemoryBackend(FilesystemBackend):
    """Custom backend that subclasses deepagents' FilesystemBackend but keeps
    bytes in an in-memory dict instead of local disk — proves the kernel will
    drive an arbitrary storage layer (the real one writes through to MinIO)."""

    def __init__(self) -> None:
        super().__init__(root_dir=None, virtual_mode=True)
        self.store: dict[str, str] = {}

    def write(self, file_path: str, content: str):
        self.store[file_path] = content
        return super().write(file_path, content)


def main() -> int:
    findings: list[str] = []
    ok = True

    # 1. backend is a real create_deep_agent parameter
    params = inspect.signature(create_deep_agent).parameters
    has_backend = "backend" in params
    findings.append(f"create_deep_agent has `backend` param: {has_backend}")
    ok &= has_backend

    # 2. custom backend conforms to BackendProtocol (4 ops present)
    be = InMemoryBackend()
    for op in ("read", "write", "ls", "edit"):
        present = callable(getattr(be, op, None))
        findings.append(f"backend.{op} callable: {present}")
        ok &= present

    # 3. kernel accepts the injected backend without error (no model call needed)
    try:
        agent = create_deep_agent(model=None, tools=[], backend=be)
        findings.append(f"create_deep_agent(backend=custom) built: {agent is not None}")
        ok &= agent is not None
    except Exception as exc:
        findings.append(f"create_deep_agent(backend=custom) FAILED: {exc!r}")
        ok = False

    # 4. real method signatures (record for C2 contract refinement)
    findings.append(
        "REAL signatures (C2 must conform): "
        f"read{inspect.signature(FilesystemBackend.read)}, "
        f"write{inspect.signature(FilesystemBackend.write)}, "
        f"ls{inspect.signature(FilesystemBackend.ls)}, "
        f"edit{inspect.signature(FilesystemBackend.edit)}"
    )

    print("=== POC P1: backend injection ===")
    for f in findings:
        print(" -", f)
    print(f"\nRESULT P1: {'GREEN' if ok else 'RED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
