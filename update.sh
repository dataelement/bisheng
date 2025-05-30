#! /bin/bash

old_version="1.2.0"
new_version="1.3.0"
sed -i.bak "s/$old_version/$new_version/g" ./docker/docker-compose.yml
sed -i.bak "s/$old_version/$new_version/g" ./src/backend/pyproject.toml
sed -i.bak "s/$old_version/$new_version/g" ./src/backend/bisheng/__init__.py
