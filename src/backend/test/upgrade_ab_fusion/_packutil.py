from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
PACK = REPO / "scripts" / "upgrade-ab-fusion"


def ensure_pack_path() -> Path:
    pack = str(PACK)
    if pack not in sys.path:
        sys.path.insert(0, pack)
    return PACK
