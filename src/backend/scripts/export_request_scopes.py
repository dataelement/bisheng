"""Generate frontend policy metadata from the application's actual declared routes."""

import argparse
import json
import re
import sys
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))


def gateway_routes(root):
    rows = []
    for path in sorted((root / "src/main/java/com/dataelem/gateway/controller").glob("*.java")):
        text = path.read_text()
        before_class, methods = re.split(r"public (?:final )?class ", text, maxsplit=1)
        prefixes = re.findall(r'@RequestMapping\("([^"\n]+)"\)', before_class)
        if len(prefixes) != 1:
            raise ValueError(f"Gateway scope generator requires one literal class mapping: {path.name}")
        declarations = re.findall(r"RequestBoundary\(.*?Kind\.(\w+)\)", before_class)
        if not declarations:
            raise ValueError(f"Gateway controller scope unregistered: {path.name}")
        kind = declarations[-1].lower()
        mappings = list(re.finditer(r'@(Get|Post|Put|Delete|Patch|Request)Mapping\("([^"\n]+)"\)', methods))
        if len(mappings) != len(re.findall(r"@(?:Get|Post|Put|Delete|Patch|Request|Head|Options)Mapping\b", methods)):
            raise ValueError(f"Unsupported Gateway method mapping; extend the generator: {path.name}")
        for match in mappings:  # mapping shapes above are deliberately validated
            tail = methods[match.end() :].split("public ", 1)[0]
            override = re.findall(r"RequestBoundary\(.*?Kind\.(\w+)\)", tail)
            declared = override[-1].lower() if override else kind
            verbs = (
                [match[1].upper()]
                if match[1] != "Request"
                else ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]
            )
            rows.extend(
                {"method": verb, "path": prefixes[0] + match[2], "scope": declared, "variant": None} for verb in verbs
            )
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=_BACKEND_ROOT.parent / "frontend/packages/api-client/src/requestScopeRoutes.json"
    )
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--gateway-root", type=Path)
    args = parser.parse_args()
    from bisheng.main import app

    rows = [
        {key: row[key] for key in ("method", "path", "scope", "variant")} for row in app.state.request_scope_inventory
    ]
    body = json.dumps(rows, ensure_ascii=False, separators=(",", ":")) + "\n"
    if args.check:
        if not args.output.exists() or args.output.read_text() != body:
            raise SystemExit("Request scope metadata is stale; regenerate from this backend revision")
    else:
        args.output.write_text(body)
    if args.gateway_root:
        gateway = gateway_routes(args.gateway_root)
        target = args.output.with_name("gatewayRequestScopeRoutes.json")
        content = json.dumps(gateway, separators=(",", ":")) + "\n"
        if args.check:
            if not target.exists() or target.read_text() != content:
                raise SystemExit("Gateway scope metadata is stale")
        else:
            target.write_text(content)
        print(f"Validated {len(gateway)} gateway route methods")
    print(f"Validated {len(rows)} declared route methods")


if __name__ == "__main__":
    main()
