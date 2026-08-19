#! /bin/bash

old_version="2.6.0-fix"
new_version="2.6.0-fix2"
sed -i.bak "s/$old_version/$new_version/g" ./docker/docker-compose.yml
sed -i.bak "s/$old_version/$new_version/g" ./src/backend/pyproject.toml
sed -i.bak "s/$old_version/$new_version/g" ./src/backend/bisheng/__init__.py
