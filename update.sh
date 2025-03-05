#! /bin/bash

old_version="0.4.1.2"
new_version="1.0.0"
sed -i "s/$old_version/$new_version/g" ./docker/docker-compose.yml
sed -i "s/$old_version/$new_version/g" ./src/backend/pyproject.toml
sed -i "s/$old_version/$new_version/g" ./src/backend/bisheng/__init__.py
