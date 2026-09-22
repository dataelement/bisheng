#! /bin/bash

old_version="3.0.0-beta1"
new_version="3.0.0-beta2"
sed -i.bak "s/$old_version/$new_version/g" ./docker/docker-compose.yml
sed -i.bak "s/$old_version/$new_version/g" ./src/backend/pyproject.toml
# uv.lock stores prerelease versions in normalized PEP 440 form.
sed -i.bak '/^name = "backend"$/ {
n
s/^version = .*/version = "'"${new_version/-beta/b}"'"/
}' ./src/backend/uv.lock
sed -i.bak "s/$old_version/$new_version/g" ./src/backend/bisheng/__init__.py
sed -i.bak "s/$old_version/$new_version/g" ./src/frontend/platform/package.json
sed -i.bak "s/$old_version/$new_version/g" ./src/frontend/client/package.json
