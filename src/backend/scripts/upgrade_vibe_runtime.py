#!/usr/bin/env python3
"""Scoped API upgrade. Dry-run by default; no direct Engine or database access.

cd src/backend && python scripts/upgrade_vibe_runtime.py --help
The caller's ordinary platform identity must already have the existing app-operation permission.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path

_BACKEND_ROOT = str(Path(__file__).resolve().parents[1])
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)


def validate_inventory(document):
    if document.get("schema_version") != 1 or not document.get("node_id") or not document.get("engine_id"):
        raise ValueError("invalid inventory header")
    seen = set()
    for item in document["applications"]:
        if item["app_id"] in seen:
            raise ValueError("duplicate app")
        seen.add(item["app_id"])
        labels = item.get("labels", {})
        if labels.get("bisheng.app.id") != item["app_id"] or labels.get("bisheng.version.id") != item["version_id"]:
            raise ValueError("inventory scope mismatch")
        if not item["image_id"].startswith("sha256:"):
            raise ValueError("immutable local image ID required")
    return document


def api(base, path, body):
    token = os.environ.get("BISHENG_MANAGEMENT_TOKEN", "")
    if not token:
        raise ValueError("set the authorized platform session in BISHENG_MANAGEMENT_TOKEN")
    request = urllib.request.Request(
        base.rstrip("/") + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Cookie": "access_token_cookie=" + token},
        method="POST",
    )

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise ValueError("upgrade_redirect_refused")

    with urllib.request.build_opener(NoRedirect()).open(request, timeout=120) as response:
        document = json.load(response)
    if document.get("status_code") not in {0, 200}:
        raise RuntimeError("upgrade refused: " + str(document.get("status_message", "unknown")))
    return document["data"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--acknowledge-maintenance", action="store_true")
    parser.add_argument("--expected-inventory-sha256")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    raw = Path(args.inventory).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if args.apply and (not args.acknowledge_maintenance or args.expected_inventory_sha256 != digest):
        parser.error("apply requires maintenance acknowledgement and the reviewed inventory hash")
    inventory = validate_inventory(json.loads(raw))
    results = []
    for item in inventory["applications"]:
        body = {
            **item,
            "node_id": inventory["node_id"],
            "engine_id": inventory["engine_id"],
            "apply": args.apply,
            "acknowledge_maintenance": args.acknowledge_maintenance,
        }
        results.append(api(args.base_url, f"/api/v1/apps/{item['app_id']}/runtime/upgrade", body))
    Path(args.report).write_text(
        json.dumps({"inventory_sha256": digest, "applied": args.apply, "results": results}, indent=2) + "\n"
    )
    print(json.dumps({"inventory_sha256": digest, "applications": len(results), "applied": args.apply}))


if __name__ == "__main__":
    main()
