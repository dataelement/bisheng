#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT/docker"

echo "Stopping bisheng app containers if present..."
docker stop bisheng-backend bisheng-backend-worker bisheng-frontend 2>/dev/null || true

echo "Starting middleware..."
docker compose -f docker-compose.yml -p bisheng up -d mysql openfga-migrate openfga redis elasticsearch etcd minio milvus

echo "Initializing bisheng_gateway schema (idempotent)..."
docker exec -i bisheng-mysql mysql -uroot -p1234 < "$ROOT/docker/local-dev/init-gateway-db.sql"

echo "Done."
