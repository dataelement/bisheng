#! /bin/bash

which tar

tar --exclude='__pycache__' --exclude='node_modules' --exclude='src/backend/venv' --exclude='src/backend/poetry.toml' --exclude='src/backend/venv' -czf bisheng.tar.gz .drone.yml .gitignore docker/bisheng/config/config.yaml docker/bisheng/entrypoint.sh docker/docker-compose.yml src/backend src/frontend