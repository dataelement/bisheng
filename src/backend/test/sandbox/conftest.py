"""Put ``src/sandbox-runner`` on sys.path so backend pytest can import it.

The runner is an independent package (must not ``import bisheng``).
"""

from __future__ import annotations

import sys
from pathlib import Path

_TEST_DIR = str(Path(__file__).resolve().parent)
if _TEST_DIR not in sys.path:
    sys.path.insert(0, _TEST_DIR)

_RUNNER_ROOT = Path(__file__).resolve().parents[3] / "sandbox-runner"
_root = str(_RUNNER_ROOT)
if _root not in sys.path:
    sys.path.insert(0, _root)
