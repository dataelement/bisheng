"""Run disposable business probes without exposing SDK or HTTP diagnostics."""

import argparse
import contextlib
import io
import json
import os
import runpy
import secrets
import sys
import traceback
from pathlib import Path


def main():
    owner = os.environ.get("BISHENG_ROTATION_EXPECTED_OWNER", "")
    marker = Path("/app/data/.credential-acceptance-owner")
    if (
        os.environ.get("BISHENG_ROTATION_BUSINESS_DISPOSABLE") != "true"
        or owner not in {"rotation-acceptance-166", "rotation-acceptance-166-sealed-v2"}
        or not marker.is_file() or marker.read_text().strip() != owner
    ):
        raise SystemExit("explicit disposable fixture ownership required")
    parser = argparse.ArgumentParser()
    parser.add_argument("probe", choices=["business", "data", "worker"])
    parser.add_argument("mode", choices=["seed", "verify"])
    args = parser.parse_args()
    root = Path("/app/data/credential-acceptance")
    root.mkdir(mode=0o700, exist_ok=True)
    script = Path(__file__).parent / (args.probe + "_probe.py")
    os.environ["MODE"] = args.mode
    target_mode = "create" if args.probe == "business" and args.mode == "seed" else args.mode
    sys.argv = [str(script), target_mode]
    output = io.StringIO()
    try:
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            runpy.run_path(str(script), run_name="__main__")
    except BaseException as error:
        result = {
            "status": "failed", "probe": args.probe, "mode": args.mode,
            "error_type": type(error).__name__,
            "frames": [{"file": Path(f.filename).name, "line": f.lineno, "function": f.name}
                       for f in traceback.extract_tb(error.__traceback__)[-6:]],
        }
        try:
            from bisheng.core.config.credential_artifacts import write_confidential

            diagnostic = root / ("probe-error-" + secrets.token_hex(8) + ".sealed")
            write_confidential(diagnostic, (traceback.format_exc() + "\n" + output.getvalue()).encode(), deployment=owner)
            result["encrypted_diagnostic"] = diagnostic.name
        except Exception:
            # Never substitute a plaintext file when diagnostic encryption fails.
            result["diagnostic_status"] = "encryption_failed_no_plaintext_written"
        print(json.dumps(result))
        return 1
    print(json.dumps({"status": "passed", "probe": args.probe, "mode": args.mode}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
