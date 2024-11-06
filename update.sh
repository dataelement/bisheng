#! /bin/bash

old_version="0.3.6.dev1"
new_version="0.3.7.dev1"
sed -i '' "s/$old_version/$new_version/g" ./docker/docker-compose.yml
sed -i ''  "s/$old_version/$new_version/g" ./src/backend/pyproject.toml
sed -i ''  "s/$old_version/$new_version/g" ./src/backend/bisheng/__init__.py
