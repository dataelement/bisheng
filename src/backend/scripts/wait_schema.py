#!/usr/bin/env python3
"""Read-only deployment startup wait, no migration or initialization marker."""

import asyncio
import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parents[1])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.standard_helm_bootstrap import arguments, wait_ready  # noqa: E402

if __name__ == "__main__":
    args = arguments()
    if not 1 <= args.timeout <= 3600:
        raise SystemExit("Startup timeout must be between 1 and 3600 seconds")
    asyncio.run(wait_ready(runtime=args.runtime, catalog=args.catalog, timeout=args.timeout))
