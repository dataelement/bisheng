#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

old_version="3.1.0-beta2"
new_version="3.1.0-alpha1"
old_pattern=${old_version//./\\.}
normalized_version=${new_version/-alpha/a}
normalized_version=${normalized_version/-beta/b}

# Only current product metadata and deployment defaults. Historical migrations,
# feature documents, independent packages and middleware versions keep their IDs.
files=(
  docker/.env.example
  docker/bisheng-sandbox/Dockerfile
  docker/README.md
  docker/helm/README.md
  docker/helm/bisheng/README.md
  docker/helm/bisheng/Chart.yaml
  docker/helm/bisheng/values.yaml
  docker/helm/bisheng-sandbox/Chart.yaml
  docker/helm/bisheng-sandbox/values.yaml
  deploy/kubernetes/app-runtime/Chart.yaml
  src/backend/pyproject.toml
  src/backend/bisheng/__init__.py
  src/runtime-manager/pyproject.toml
  src/runtime-manager/runtime_manager/__init__.py
  src/runtime-manager/runtime_manager/image_catalog.py
  src/app-proxy/pyproject.toml
  src/app-proxy/app_proxy/__init__.py
  src/frontend/platform/package.json
  src/frontend/client/package.json
  scripts/tests/test_helm_package.py
)
for file in "${files[@]}"; do
  # Preserve historical feature paths and statements about when a change shipped.
  sed -i.bak -e "/features\\//b" -e "/${old_pattern} 起/b" -e "s/${old_pattern}/${new_version}/g" "$file"
done

# The toolkit advertises the platform release separately from the CLI/SDK wheels.
BISHENG_RELEASE_VERSION="$new_version" python3 - <<'PY'
import json
import os
from pathlib import Path

manifest_file = Path("src/backend/bisheng/dev_toolkit/artifacts/manifest.json")
manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
manifest["platform"]["version"] = os.environ["BISHENG_RELEASE_VERSION"]
manifest_file.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
PY

# uv.lock normalizes prereleases to PEP 440. Update only each local package,
# leaving every third-party dependency version and hash unchanged.
for entry in \
  backend:src/backend/uv.lock \
  bisheng-runtime-manager:src/runtime-manager/uv.lock \
  bisheng-app-proxy:src/app-proxy/uv.lock; do
  package=${entry%%:*}
  file=${entry#*:}
  sed -i.bak "/^name = \"${package}\"\$/ {
    n
    s/^version = .*/version = \"${normalized_version}\"/
  }" "$file"
done
