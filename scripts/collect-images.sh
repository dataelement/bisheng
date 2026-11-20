#!/usr/bin/env bash
# 按默认 app-runtime 安装表写出本次架构要拉取的镜像。
# 每行三列：ENV_NAME service ref
# 版本镜像保留 v 前缀；arm64 只给五个毕昇服务镜像和 socket proxy 加架构后缀。
set -euo pipefail

ARCH=""
VERSION=""
ENV_FILE="docker/.env.example"

log() { printf '[collect-images] %s\n' "$*" >&2; }
die() { printf '[collect-images][ERROR] %s\n' "$*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --arch) ARCH="${2:?}"; shift 2 ;;
    --version) VERSION="${2:?}"; shift 2 ;;
    --env-example) ENV_FILE="${2:?}"; shift 2 ;;
    -h|--help)
      printf '%s\n' "用法：$0 --arch amd64|arm64 --version v3.1.0 [--env-example docker/.env.example]"
      exit 0 ;;
    *) die "未知参数：$1" ;;
  esac
done

[[ "$ARCH" =~ ^(amd64|arm64)$ ]] || die "--arch 只能是 amd64 或 arm64"
[[ "$VERSION" =~ ^v[0-9] ]] || die "--version 必须是带 v 的 tag，例如 v3.1.0"
[[ -f "$ENV_FILE" ]] || die "找不到 .env.example：$ENV_FILE"

env_value() {
  awk -F= -v key="$1" '
    /^[[:space:]]*#/ { next }
    $1 == key { sub(/^[^=]*=/, ""); print; exit }
  ' "$ENV_FILE"
}

emit() { printf '%s %s %s\n' "$1" "$2" "$3"; }

suffix=""
[[ "$ARCH" == arm64 ]] && suffix="-arm64"
registry="cr.dataelem.com/dataelement"
emit BISHENG_BACKEND_IMAGE backend "${registry}/bisheng-backend:${VERSION}${suffix}"
emit BISHENG_FRONTEND_IMAGE frontend "${registry}/bisheng-frontend:${VERSION}${suffix}"
emit BISHENG_SANDBOX_IMAGE code-runner-1 "${registry}/bisheng-sandbox:${VERSION}${suffix}"
emit BISHENG_RUNTIME_MANAGER_IMAGE runtime-manager "${registry}/bisheng-runtime-manager:${VERSION}${suffix}"
emit BISHENG_APP_PROXY_IMAGE app-proxy "${registry}/bisheng-app-proxy:${VERSION}${suffix}"

if [[ "$ARCH" == arm64 ]]; then
  socket="$(awk '
    /DOCKER_SOCKET_PROXY_IMAGE to / {
      for (i = 1; i <= NF; i++) if ($i ~ /^cr\./) { gsub(/[.;,]$/, "", $i); print $i; exit }
    }
  ' "$ENV_FILE")"
  [[ -n "$socket" ]] || die "${ENV_FILE} 没有注明 ARM 的 DOCKER_SOCKET_PROXY_IMAGE"
else
  socket="$(env_value DOCKER_SOCKET_PROXY_IMAGE)"
  [[ -n "$socket" ]] || die "${ENV_FILE} 缺少 DOCKER_SOCKET_PROXY_IMAGE"
fi
emit DOCKER_SOCKET_PROXY_IMAGE docker-socket-proxy "$socket"

for pair in \
  MYSQL_IMAGE:mysql \
  OPENFGA_IMAGE:openfga \
  REDIS_IMAGE:redis \
  ELASTICSEARCH_IMAGE:elasticsearch \
  ETCD_IMAGE:etcd \
  MINIO_IMAGE:minio \
  MILVUS_IMAGE:milvus
do
  key="${pair%%:*}"
  service="${pair#*:}"
  ref="$(env_value "$key")"
  [[ -n "$ref" ]] || die "${ENV_FILE} 缺少 ${key}"
  emit "$key" "$service" "$ref"
done
