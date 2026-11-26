#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

old_version="3.1.0-beta1"
new_version="3.1.0-beta2"
old_pattern=${old_version//./\\.}

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
  sed -i.bak "s/${old_pattern}/${new_version}/g" "$file"
done

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
    s/^version = .*/version = \"${new_version/-beta/b}\"/
  }" "$file"
done
