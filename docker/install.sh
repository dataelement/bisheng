#!/usr/bin/env bash
# Copy the template, optionally configure Gateway, then let Compose deploy.
set -euo pipefail
umask 077
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"
source "${SCRIPT_DIR}/lib/install-env.sh"
die() { printf '部署停止：%s\n' "$*" >&2; exit 1; }

GATEWAY_CHOICE=""; LICENSE_FILE=""; PUBLIC_URL=""; PREPARE_ONLY=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --gateway) GATEWAY_CHOICE=true; shift ;;
    --no-gateway) GATEWAY_CHOICE=false; shift ;;
    --prepare-only) PREPARE_ONLY=true; shift ;;
    --license-file|--public-url)
      [[ $# -ge 2 && -n "$2" ]] || die "$1 需要参数"
      if [[ "$1" = --license-file ]]; then LICENSE_FILE="$2"; else PUBLIC_URL="$2"; fi
      shift 2 ;;
    -h|--help)
      printf '%s\n' '用法：bash docker/install.sh [--gateway | --no-gateway] [--prepare-only]' \
        '首次无参数部署不启用 Gateway；已有 .env 按原配置继续。' \
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
compose config --quiet
if [[ "$PREPARE_ONLY" = true ]]; then printf '配置已生成并通过 Compose 校验。\n'; exit 0; fi
# Authenticate with the public defaults; existing deployments may override them.
registry_user="$(env_get "$ENV_FILE" CR_REGISTRY_USERNAME)"
registry_password="$(env_get "$ENV_FILE" CR_REGISTRY_PASSWORD)"
printf '%s\n' "${registry_password:-dataelem}" | \
  docker login cr.dataelem.com --username "${registry_user:-docker}" --password-stdin \
  || die "CR 镜像源登录失败，请检查网络或 .env 中的 CR_REGISTRY_USERNAME / CR_REGISTRY_PASSWORD"
unset registry_password
# Pull first so missing images stop deployment before existing services change.
compose pull || die "镜像拉取失败；请检查网络、镜像权限或 .env 中的 *_IMAGE 地址。不会自动构建。"
case ",$(env_get "$ENV_FILE" COMPOSE_PROFILES)," in
  *,gateway,*) compose up -d gateway ;;
esac
compose up -d
printf '已执行启动；请使用 Compose ps / logs 确认服务就绪，Gateway 授权结果查看 gateway 日志。\n'
