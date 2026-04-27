# 一键：Docker 中间件 + bisheng API (BISHENG_PRO) + Celery worker + Gateway（各开新窗口）
# 在 bisheng 仓库根目录执行: powershell -ExecutionPolicy Bypass -File docker/local-dev/start-full-stack.ps1
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
$mvnBin = "$env:USERPROFILE\tools\apache-maven-3.9.9\bin"
if (Test-Path $mvnBin) { $env:Path = "$mvnBin;$env:Path" }

$backend = Join-Path $repoRoot "src\backend"
$gateway = Join-Path (Split-Path $repoRoot -Parent) "bisheng-gateway"
if (-not (Test-Path (Join-Path $gateway "pom.xml"))) {
    $gateway = Join-Path $repoRoot "..\bisheng-gateway"
}
# Common Windows layout: %USERPROFILE%\Desktop\gateway\bisheng-gateway
$gwDesktop = Join-Path $env:USERPROFILE "Desktop\gateway\bisheng-gateway"
if (-not (Test-Path (Join-Path $gateway "pom.xml")) -and (Test-Path (Join-Path $gwDesktop "pom.xml"))) {
    $gateway = $gwDesktop
}

$javaExe = "java"
try { $javaExe = (Get-Command java -ErrorAction Stop).Source } catch { }

Write-Host "==> Middleware"
& "$PSScriptRoot\start-middleware.ps1"

if (Test-Path (Join-Path $gateway "pom.xml")) {
    Write-Host "==> Maven package gateway"
    Push-Location $gateway
    mvn -q -DskipTests package
    Pop-Location
}

$py = Join-Path $backend ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Error "Missing $py — run: cd src/backend ; uv sync"
}

# 子进程继承当前会话环境（避免 Start-Process -Command 长字符串在部分环境下 ArgumentList 校验失败）
$env:config = "config.yaml"
$env:BISHENG_PRO = "true"
$env:BS_SSO_SYNC__GATEWAY_HMAC_SECRET = "bisheng-local-hmac-20260422"

Write-Host "==> Start bisheng API (new window)"
Start-Process -FilePath $py -WorkingDirectory $backend -ArgumentList @(
  "-m", "uvicorn", "bisheng.main:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1", "--no-access-log"
) -WindowStyle Normal

Start-Sleep -Seconds 10

$celeryNode = "dev@{0}" -f $env:COMPUTERNAME
Write-Host "==> Start Celery worker (new window)"
Start-Process -FilePath $py -WorkingDirectory $backend -ArgumentList @(
  "-m", "celery", "-A", "bisheng.worker.main", "worker", "-l", "info", "-c", "4", "-P", "threads",
  "-Q", "knowledge_celery,workflow_celery,celery", "-n", $celeryNode
) -WindowStyle Normal

Start-Sleep -Seconds 3

$jar = Join-Path $gateway "target\gateway-0.0.1-SNAPSHOT.jar"
if (Test-Path $jar) {
    Write-Host "==> Start Gateway (new window)"
    Start-Process -FilePath $javaExe -WorkingDirectory $gateway -ArgumentList @(
      "-jar", ".\target\gateway-0.0.1-SNAPSHOT.jar", "--spring.profiles.active=local", "--server.port=8180"
    ) -WindowStyle Normal
} else {
    Write-Warning "Gateway jar not found: $jar"
}

Start-Sleep -Seconds 15

Write-Host "==> HMAC smoke (via Gateway :8180)"
& $py (Join-Path $repoRoot "scripts\dev\gateway_hmac_org_sync_smoke.py") --base http://127.0.0.1:8180

Write-Host ""
Write-Host "bisheng: http://127.0.0.1:7860/health"
Write-Host "Gateway: http://127.0.0.1:8180/api/oauth2/list"
Write-Host "企业微信部门树 -> bisheng (F014): GET http://127.0.0.1:8180/api/group/test"
Write-Host "自定义 JSON -> bisheng: POST http://127.0.0.1:8180/api/group/sso-departments-raw"
Write-Host "Python 自签: & '$py' '$repoRoot\scripts\dev\gateway_hmac_org_sync_smoke.py' --base http://127.0.0.1:8180"
