# 在 bisheng 仓库根目录执行：本机 bisheng API + 开启 SSO（BISHENG_PRO）
$ErrorActionPreference = "Stop"
$backend = Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) "src\backend"
Set-Location $backend
$env:config = "config.yaml"
$env:BISHENG_PRO = "true"
$env:BS_SSO_SYNC__GATEWAY_HMAC_SECRET = "bisheng-local-hmac-20260422"
& ".\.venv\Scripts\python.exe" -m uvicorn bisheng.main:app --host 0.0.0.0 --port 7860 --workers 1 --no-access-log
