# 仅启动 Docker 中间件（不启 bisheng-backend / worker / frontend 容器）
# 在仓库根目录执行:  powershell -File docker/local-dev/start-middleware.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$dockerDir = Join-Path $root "docker"
Set-Location $dockerDir

Write-Host "Stopping bisheng app containers if present..."
docker stop bisheng-backend bisheng-backend-worker bisheng-frontend 2>$null

Write-Host "Starting middleware (mysql -> openfga -> redis -> es -> milvus stack)..."
docker compose -f docker-compose.yml -p bisheng up -d mysql openfga-migrate openfga redis elasticsearch etcd minio milvus

Write-Host "Initializing bisheng_gateway schema (idempotent)..."
$sqlPath = Join-Path $PSScriptRoot "init-gateway-db.sql"
# PowerShell 管道会损坏 UTF-8/中文注释，用 docker cp 再执行
docker cp $sqlPath bisheng-mysql:/tmp/init-gateway-db.sql
docker exec bisheng-mysql sh -c "mysql -uroot -p1234 < /tmp/init-gateway-db.sql"

Write-Host "Done. MySQL :3306, Redis :6379, OpenFGA :8080, ES :9200, MinIO :9100, Milvus :19530"
