from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
PACK = REPO / "scripts" / "upgrade-ab-fusion"
P4 = PACK / "p4"
P5 = PACK / "p5"
LIB = PACK / "lib"


def load_module(name: str, path: Path):
    """按文件路径加载脚本模块 (含连字符文件名)。"""
    lib = str(LIB)
    if lib not in sys.path:
        sys.path.insert(0, lib)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod
