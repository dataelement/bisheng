#!/usr/bin/env bash
# Copy the template, optionally configure Gateway, then let Compose deploy.
set +x
set -euo pipefail
umask 077
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"
source "${SCRIPT_DIR}/lib/install-env.sh"
source "${SCRIPT_DIR}/lib/credential-install.sh"
source "${SCRIPT_DIR}/lib/credential-migrate.sh"
die() { printf '部署停止：%s\n' "$*" >&2; exit 1; }

BUNDLE=""; KEY_FILE=""; REVISION=""
GATEWAY_CHOICE=""; LICENSE_FILE=""; PUBLIC_URL=""; PREPARE_ONLY=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --bundle|--key-file|--revision)
      [[ $# -ge 2 ]] || die '凭据路径参数缺失'
      case "$1" in --bundle) BUNDLE=$2 ;; --key-file) KEY_FILE=$2 ;; --revision) REVISION=$2 ;; esac
      shift 2 ;;
    --gateway) GATEWAY_CHOICE=true; shift ;;
    --no-gateway) GATEWAY_CHOICE=false; shift ;;
    --prepare-only) PREPARE_ONLY=true; shift ;;
    --license-file|--public-url)
      [[ $# -ge 2 && -n "$2" ]] || die "$1 需要参数"
      if [[ "$1" = --license-file ]]; then LICENSE_FILE="$2"; else PUBLIC_URL="$2"; fi
      shift 2 ;;
    -h|--help)
      printf '%s\n' '用法：bash docker/install.sh [--gateway | --no-gateway] [--prepare-only]' \
        '首次运行会引导填写密码；后续自动复用现有配置、密码及密钥。' \
        'Gateway 必须提供 license 文件路径：--license-file <文件> --public-url <平台地址>'
      exit 0 ;;
    *) die "未知参数：$1" ;;
  esac
done
if docker compose version >/dev/null 2>&1; then COMPOSE=(docker compose);
elif command -v docker-compose >/dev/null 2>&1; then COMPOSE=(docker-compose);
else die "请安装 Docker Compose（推荐 V2，也支持 docker-compose 命令入口）"; fi
# An existing .env is never replaced or merged automatically.
[[ -f "$ENV_FILE" ]] || cp "${SCRIPT_DIR}/.env.example" "$ENV_FILE"
chmod 600 "$ENV_FILE"
compose() { "${COMPOSE[@]}" --env-file "$ENV_FILE" -f "${SCRIPT_DIR}/docker-compose.yml" "$@"; }
credential_initialize_store
profiles="$(env_get "$ENV_FILE" COMPOSE_PROFILES)"
if [[ -n "$LICENSE_FILE" ]]; then
  [[ "$GATEWAY_CHOICE" != false ]] || die "--license-file 不能与 --no-gateway 同时使用"
  GATEWAY_CHOICE=true
fi
if [[ -z "$GATEWAY_CHOICE" ]]; then
  case ",$profiles," in *,gateway,*) GATEWAY_CHOICE=true ;; esac
fi
if [[ "$GATEWAY_CHOICE" = true ]]; then
  LICENSE_FILE="${LICENSE_FILE:-$(env_get "$ENV_FILE" BISHENG_GATEWAY_LICENSE_FILE)}"
  if [[ -z "$LICENSE_FILE" && -t 0 ]]; then
    read -r -p 'Gateway license 文件路径（留空则不启用）：' LICENSE_FILE
  fi
  if [[ -z "$LICENSE_FILE" ]]; then
    printf '未提供 license 文件路径，跳过 Gateway。\n'
    GATEWAY_CHOICE=false
    PUBLIC_URL=""
  else
    [[ -f "$LICENSE_FILE" && -r "$LICENSE_FILE" ]] || die "license 文件不存在或不可读：$LICENSE_FILE"
  fi
fi
if [[ "$GATEWAY_CHOICE" = true ]]; then
  LICENSE_FILE="$(cd "$(dirname "$LICENSE_FILE")" && pwd)/$(basename "$LICENSE_FILE")"
  license="$(cat "$LICENSE_FILE")"
  [[ "$license" =~ [^[:space:]] ]] || die "license 文件不能为空"
  env_set "$ENV_FILE" BISHENG_GATEWAY_LICENSE_FILE "$LICENSE_FILE"
  PUBLIC_URL="${PUBLIC_URL:-$(env_get "$ENV_FILE" BISHENG_PUBLIC_URL)}"
  if [[ -z "$PUBLIC_URL" && -t 0 ]]; then read -r -p '平台对外地址（如 http://服务器IP:3001）：' PUBLIC_URL; fi
  [[ "$PUBLIC_URL" =~ ^https?://[^/?#@[:space:]]+/?$ ]] || die "请填写不带路径的平台 http(s) 地址"
  for key in BISHENG_GATEWAY_HMAC_SECRET BISHENG_GATEWAY_DB_PASSWORD; do
    if [[ -z "$(env_get "$ENV_FILE" "$key")" ]]; then
      env_set "$ENV_FILE" "$key" "$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')"
    fi
  done
  volume="$(env_get "$ENV_FILE" DOCKER_VOLUME_DIRECTORY)"; volume="${volume:-.}"
  case "$volume" in /*) ;; *) volume="${SCRIPT_DIR}/${volume}" ;; esac
  mkdir -p "${SCRIPT_DIR}/.generated/nginx"
  target="$(mktemp -d "${SCRIPT_DIR}/.generated/nginx/gateway.XXXXXX")"
  cp -R "${volume}/nginx/conf.d/." "$target/"
  awk '
    /^[[:space:]]*location[[:space:]]/ { api = index($0, "^(/workspace)?/api") > 0 }
    api { sub(/proxy_pass http:\/\/backend_server;/, "proxy_pass http://gateway:8080;") }
    { print }
  ' "${volume}/nginx/conf.d/default.conf" > "${target}/default.conf"
  sed 's|proxy_pass http://backend:7860;|proxy_pass http://gateway:8080;|g' \
    "${volume}/nginx/conf.d/websocket.conf" > "${target}/websocket.conf"
  env_set "$ENV_FILE" BISHENG_GATEWAY_LICENSE "$license"
  env_set "$ENV_FILE" BISHENG_PUBLIC_URL "${PUBLIC_URL%/}"
  env_set "$ENV_FILE" BISHENG_NGINX_CONF_DIR "$target"
elif [[ -n "$LICENSE_FILE" || -n "$PUBLIC_URL" ]]; then die "Gateway 参数需要同时使用 --gateway";
fi
if [[ -n "$GATEWAY_CHOICE" ]]; then
  env_set "$ENV_FILE" COMPOSE_PROFILES "$(set_gateway_profile "$profiles" "$GATEWAY_CHOICE")"
  env_set "$ENV_FILE" BISHENG_PRO "$GATEWAY_CHOICE"
  if [[ "$GATEWAY_CHOICE" = false ]]; then
    volume="$(env_get "$ENV_FILE" DOCKER_VOLUME_DIRECTORY)"; volume="${volume:-.}"
    env_set "$ENV_FILE" BISHENG_NGINX_CONF_DIR "${volume%/}/nginx/conf.d"
  fi
fi
# Existing advanced path options stay compatible; normal deployment needs none.
BUNDLE=${BUNDLE:-$(env_get "$ENV_FILE" BISHENG_CREDENTIALS_DIR)}
KEY_FILE=${KEY_FILE:-$(env_get "$ENV_FILE" BISHENG_SECRET_KEYS_FILE)}
REVISION=${REVISION:-$(env_get "$ENV_FILE" BISHENG_CREDENTIAL_REVISION)}
volume=$(env_get "$ENV_FILE" DOCKER_VOLUME_DIRECTORY); volume=${volume:-.}
case "$volume" in /*) ;; *) volume="$SCRIPT_DIR/$volume" ;; esac
volume=$(cd "$volume" && pwd)
# Preserve the original prepare-only contract: no image/password requirement,
# no network or service changes. Placeholders validate Compose structure only.
if [[ $PREPARE_ONLY = true && -z $BUNDLE ]]; then
  rest_tls=$(env_get "$ENV_FILE" BISHENG_ES_REST_TLS); rest_tls=${rest_tls:-false}
  skip_transport_tls=$(env_get "$ENV_FILE" BISHENG_ES_SKIP_TRANSPORT_TLS); skip_transport_tls=${skip_transport_tls:-yes}
  BISHENG_CREDENTIALS_DIR="$SCRIPT_DIR/.generated/credential-security/pending" \
  BISHENG_SECRET_KEYS_FILE="$SCRIPT_DIR/.generated/credential-security/pending-keys.json" \
  BISHENG_CREDENTIAL_REVISION=00000000000000000000000000000000 \
  BISHENG_SECRET_FILE_GID="$(id -g)" \
  BISHENG_ES_REST_TLS="$rest_tls" \
  BISHENG_ES_SKIP_TRANSPORT_TLS="$skip_transport_tls" \
  compose config --quiet
  printf '部署参数已准备；正式运行原命令时将自动引导密码并检查凭据，尚未启动服务。\n'
  exit 0
fi
image=$(env_get "$ENV_FILE" BISHENG_BACKEND_IMAGE)
image=${image:-$(env_get "$SCRIPT_DIR/.env.example" BISHENG_BACKEND_IMAGE)}
if [[ "$PREPARE_ONLY" != true ]]; then
# Authenticate with the public defaults; existing deployments may override them.
registry_user="$(env_get "$ENV_FILE" CR_REGISTRY_USERNAME)"
registry_password="$(env_get "$ENV_FILE" CR_REGISTRY_PASSWORD)"
printf '%s\n' "${registry_password:-dataelem}" | \
  docker login cr.dataelem.com --username "${registry_user:-docker}" --password-stdin \
  || die "CR 镜像源登录失败，请检查网络或 .env 中的 CR_REGISTRY_USERNAME / CR_REGISTRY_PASSWORD"
unset registry_password
  docker pull "$image" || die "后端工具镜像拉取失败；尚未启动服务"
  while ! credential_tool --help >/dev/null 2>&1; do
    [[ -t 0 ]] || die '当前后端镜像不支持凭据安装工具；请使用本版本配套镜像，或在交互终端重新执行原命令按提示选择镜像'
    IFS= read -r -p '当前后端镜像不支持凭据工具，请输入本版本配套后端镜像地址：' image || die '镜像选择已取消'
    [[ -n $image ]] || die '镜像地址不能为空，现有数据未改变'
    docker pull "$image" || die '配套后端镜像拉取失败，现有数据未改变'
  done
  env_set "$ENV_FILE" BISHENG_BACKEND_IMAGE "$image"
fi
for setting in BISHENG_ES_REST_TLS BISHENG_ES_SKIP_TRANSPORT_TLS; do
  if [[ -z "$(env_get "$ENV_FILE" "$setting")" ]]; then
    # These only render the standard chart; adoption never recreates native ES.
    case "$setting" in BISHENG_ES_REST_TLS) value=false ;; *) value=yes ;; esac
    env_set "$ENV_FILE" "$setting" "$value"
  fi
done
credential_setup
# Native daemons drop root privileges. Only the explicitly mounted bundle
# files get group-read; key file stays private. The host directory remains 0700.
# Choose a dedicated deployment group on shared hosts.
secret_gid=$(env_get "$ENV_FILE" BISHENG_SECRET_FILE_GID)
secret_gid=${secret_gid:-$(id -g)}
[[ $secret_gid =~ ^[0-9]+$ ]] || die 'BISHENG_SECRET_FILE_GID 必须是数字'
find "$BUNDLE" -maxdepth 1 -type f -exec chgrp "$secret_gid" {} + -exec chmod 640 {} +
# Commit the paired paths and revision together. An interruption must not leave
# a new bundle pointing at the previous key or revision in the active .env.
activation="$credential_store/activation.env.tmp"
cp "$ENV_FILE" "$activation"
env_set "$activation" BISHENG_SECRET_FILE_GID "$secret_gid"
env_set "$activation" BISHENG_CREDENTIALS_DIR "$BUNDLE"
env_set "$activation" BISHENG_SECRET_KEYS_FILE "$KEY_FILE"
env_set "$activation" BISHENG_CREDENTIAL_REVISION "$REVISION"
mv "$activation" "$ENV_FILE"
compose config --quiet
if [[ "$PREPARE_ONLY" = true ]]; then printf '配置已生成并通过 Compose 校验。\n'; exit 0; fi
# Pull first so missing images stop deployment before existing services change.
compose pull || die "镜像拉取失败；请检查网络、镜像权限或 .env 中的 *_IMAGE 地址。不会自动构建。"
if [[ $credential_adopt = true ]]; then
  credential_migrate_database
  # All native identities and their original mounts stay unchanged during key
  # adoption. Recreating them with fresh authentication would be a password change.
  compose up -d --no-deps --force-recreate backend backend_worker
  if docker container inspect bisheng-gateway >/dev/null 2>&1; then
    docker start bisheng-gateway >/dev/null || die '恢复原网关容器失败，请保留现用原生配置'
  fi
  compose up -d --no-deps frontend
  credential_lock_release
  printf '密钥外置迁移与应用启动已执行，原密码/认证状态保留；请验证组织同步、沙箱及业务，待治理密码不表示已完成改密。\n'
  exit 0
fi
# Existing volumes retain their real credentials. Changing initialization files
# does not rotate accounts; the read-only new-connection check must pass first.
compose up -d mysql-init openfga redis elasticsearch etcd minio milvus
# Wait for native liveness without repeatedly trying a wrong password. This
# also supports the legacy docker-compose command, which has no --wait flag.
ready=false
for attempt in {1..60}; do
  ready=true
  for service in mysql redis elasticsearch etcd minio milvus; do
    container=$(compose ps -q "$service")
    [[ -n $container ]] || die "中间件容器未创建：$service"
    state=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container")
    case "$state" in
      healthy|running) ;;
      unhealthy|exited|dead) die "中间件尚未就绪：$service；请检查脱敏日志" ;;
      *) ready=false ;;
    esac
  done
  [[ $ready = true ]] && break
  sleep 3
done
[[ $ready = true ]] || die '中间件启动等待超时；应用尚未启动'
network=$(env_get "$ENV_FILE" BISHENG_NETWORK_NAME)
bash "$SCRIPT_DIR/credentials.sh" --image "$image" --network "${network:-bisheng-network}" check --bundle "$BUNDLE" --key-file "$KEY_FILE" --env-file "$ENV_FILE" --online --enforce || die '中间件新连接检查失败；未启动应用。核对真实账号状态后重试'
compose up -d --no-deps --force-recreate backend backend_worker
compose up -d
credential_lock_release
printf '已执行启动；部署凭据已保存，后续继续使用原命令即可。请使用 Compose ps / logs 确认业务就绪。\n'
