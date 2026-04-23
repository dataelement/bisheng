#Requires -Version 5.1
<#
.SYNOPSIS
  在 Docker 容器 bisheng-mysql 中对库 bisheng 执行 reset-org-to-superadmin.sql。

.PARAMETER Container
  MySQL 容器名，默认 bisheng-mysql。

.PARAMETER Password
  root 密码，默认 1234（与本地 docker-compose 一致）。
#>
param(
  [string] $Container = "bisheng-mysql",
  [string] $Password = "1234"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$sql = Join-Path $PSScriptRoot "reset-org-to-superadmin.sql"

if (-not (Test-Path $sql)) {
  Write-Error "Missing SQL file: $sql"
}

Write-Host "Running reset on container '$Container' database bisheng ..." -ForegroundColor Cyan
Get-Content -LiteralPath $sql -Encoding UTF8 | docker exec -i $Container mysql -uroot "-p$Password" bisheng

if ($LASTEXITCODE -ne 0) {
  Write-Error "mysql exited with code $LASTEXITCODE"
}

Write-Host "Done. Check kept_user_id / remaining_users in mysql output above." -ForegroundColor Green
