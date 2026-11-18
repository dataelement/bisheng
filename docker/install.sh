#!/usr/bin/env bash
# Copy the template, configure optional services, then let Compose deploy.
set +x
set -euo pipefail
umask 077
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"
source "${SCRIPT_DIR}/lib/install-env.sh"
source "${SCRIPT_DIR}/lib/sandbox-security.sh"
source "${SCRIPT_DIR}/lib/credential-install.sh"
source "${SCRIPT_DIR}/lib/credential-migrate.sh"
source "${SCRIPT_DIR}/lib/credential-rotate.sh"
source "${SCRIPT_DIR}/lib/credential-runtime.sh"
source "${SCRIPT_DIR}/lib/credential-sealed-migrate.sh"
source "${SCRIPT_DIR}/lib/credential-es-migrate.sh"
die() { printf '此次部署脚本执行失败：%s\n' "$*" >&2; exit 1; }
deploy_succeed() {
  [[ -z ${1:-} ]] || printf '%s\n' "$1"
  printf '此次部署脚本执行成功。\n'
  exit 0
}
trap 'printf "此次部署脚本执行失败：命令未成功完成（退出码 %s）。\n" "$?" >&2' ERR

BUNDLE=""; KEY_FILE=""; REVISION=""
credential_key_explicit=false
GATEWAY_CHOICE=""; FT_CHOICE=""; LICENSE_FILE=""; PUBLIC_URL=""; PREPARE_ONLY=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --bundle|--key-file|--revision)
      [[ $# -ge 2 ]] || die '凭据路径参数缺失'
      case "$1" in --bundle) BUNDLE=$2 ;; --key-file) KEY_FILE=$2; credential_key_explicit=true ;; --revision) REVISION=$2 ;; esac
      shift 2 ;;
    --gateway) GATEWAY_CHOICE=true; shift ;;
    --no-gateway) GATEWAY_CHOICE=false; shift ;;
    --ft) FT_CHOICE=true; shift ;;
    --no-ft) FT_CHOICE=false; shift ;;
    --prepare-only) PREPARE_ONLY=true; shift ;;
    --license-file|--public-url)
      [[ $# -ge 2 && -n "$2" ]] || die "$1 需要参数"
      if [[ "$1" = --license-file ]]; then LICENSE_FILE="$2"; else PUBLIC_URL="$2"; fi
      shift 2 ;;
    -h|--help)
      printf '%s\n' '用法：bash docker/install.sh [--gateway | --no-gateway] [--ft | --no-ft] [--prepare-only]' \
        '首次运行引导填写密码；重新部署逐项选择是否改密，回车保留。首次无参数部署不启用 Gateway 和 FT。' \
        'FT 需要 NVIDIA GPU 和 NVIDIA Container Toolkit；--no-ft 不停止已运行容器。' \
        'Gateway 必须提供 license 文件路径：--license-file <文件> --public-url <平台地址>'
      exit 0 ;;
    *) die "未知参数：$1" ;;
  esac
done
if docker compose version >/dev/null 2>&1; then COMPOSE=(docker compose);
elif command -v docker-compose >/dev/null 2>&1; then COMPOSE=(docker-compose);
else die "请安装 Docker Compose（推荐 V2，也支持 docker-compose 命令入口）"; fi
if [[ $PREPARE_ONLY != true ]] && ! docker info --format '{{.ServerVersion}}' >/dev/null 2>&1; then
  die '当前账号无法访问Docker服务；请确认服务已启动并由管理员一次性授予Docker访问权限，再执行原命令'
fi
if [[ $PREPARE_ONLY != true ]]; then
  docker_mode=$(docker info --format '{{range .SecurityOptions}}{{if eq . "name=rootless"}}rootless{{end}}{{end}}') || die '无法核实Docker权限模式，未准备新凭据'
  [[ $docker_mode != rootless ]] || die '当前rootless Docker的密钥映射尚未通过验收；未准备新凭据或修改账号，请使用已验证的标准Docker环境'
fi
# Host-owned runner firewall is a mandatory deployment precondition. No secrets
# or application state are changed before this check succeeds.
if [[ $PREPARE_ONLY != true ]]; then
  bash "${SCRIPT_DIR}/lib/runner-egress.sh" verify
fi
# An existing .env is never replaced or merged automatically.
[[ -f "$ENV_FILE" ]] || cp "${SCRIPT_DIR}/.env.example" "$ENV_FILE"
chmod 600 "$ENV_FILE"
sandbox_initialize_token
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
  die '当前加密文件版本尚未完成Gateway许可镜像的内存凭据适配验收；未修改账号，请使用已验证的标准部署模式'
elif [[ -n "$LICENSE_FILE" || -n "$PUBLIC_URL" ]]; then
  die 'Gateway参数需要--gateway；当前加密文件版本尚不支持此模式'
fi
if [[ -n "$GATEWAY_CHOICE" ]]; then
  env_set "$ENV_FILE" COMPOSE_PROFILES "$(set_gateway_profile "$profiles" "$GATEWAY_CHOICE")"
  env_set "$ENV_FILE" BISHENG_PRO "$GATEWAY_CHOICE"
  if [[ "$GATEWAY_CHOICE" = false ]]; then
    volume="$(env_get "$ENV_FILE" DOCKER_VOLUME_DIRECTORY)"; volume="${volume:-.}"
    env_set "$ENV_FILE" BISHENG_NGINX_CONF_DIR "${volume%/}/nginx/conf.d"
  fi
fi
if [[ -n "$FT_CHOICE" ]]; then
  profiles="$(env_get "$ENV_FILE" COMPOSE_PROFILES)"
  env_set "$ENV_FILE" COMPOSE_PROFILES "$(set_optional_profile "$profiles" "$FT_CHOICE" ft)"
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
  pending="$(credential_store_path)/pending"
  mkdir -p "$pending" || die '无法准备 Compose 结构检查目录'
  # Compose stats env_file during config. This placeholder is not a credential.
  if [[ ! -f $pending/openfga.env ]]; then
    printf 'OPENFGA_DATASTORE_ENGINE=mysql\nOPENFGA_DATASTORE_URI=mysql://placeholder\n' > "$pending/openfga.env"
  fi
  BISHENG_CREDENTIALS_DIR="$pending" \
  BISHENG_SECRET_KEYS_FILE="$(credential_store_path)/pending-keys.json" \
  BISHENG_CREDENTIAL_REVISION=00000000000000000000000000000000 \
  BISHENG_SECRET_FILE_GID="$(id -g)" \
  BISHENG_ES_REST_TLS="$rest_tls" \
  BISHENG_ES_SKIP_TRANSPORT_TLS="$skip_transport_tls" \
  compose config --quiet
  deploy_succeed '部署参数已准备；正式运行原命令时将自动引导密码并检查凭据，尚未启动服务。'
fi
image=$(env_get "$ENV_FILE" BISHENG_BACKEND_IMAGE)
image=${image:-$(env_get "$SCRIPT_DIR/.env.example" BISHENG_BACKEND_IMAGE)}
if [[ $PREPARE_ONLY = true ]]; then
  [[ $BUNDLE = /* && -d $BUNDLE && $KEY_FILE = /* && -f $KEY_FILE ]] || die '预检查需要可读的现用配置包和配套密钥'
  credential_tool check --bundle "$BUNDLE" --key-file "$KEY_FILE" --env-file "$ENV_FILE" \
    || die '预检查失败，现有配置和账号未修改'
  BISHENG_CREDENTIALS_DIR="$BUNDLE" BISHENG_SECRET_KEYS_FILE="$KEY_FILE" \
    BISHENG_CREDENTIAL_REVISION="${REVISION:-$(credential_revision "$BUNDLE")}" \
    BISHENG_SECRET_FILE_GID="$(id -g)" \
    BISHENG_ES_REST_TLS=false BISHENG_ES_SKIP_TRANSPORT_TLS=yes compose config --quiet
  deploy_succeed '现用配置与Compose预检查通过，未准备新密码、调整密钥权限或启动服务。'
fi
if [[ "$PREPARE_ONLY" != true ]]; then
  credential_image_pull_policy=$(env_get "$ENV_FILE" BISHENG_IMAGE_PULL_POLICY)
  credential_image_pull_policy=${credential_image_pull_policy:-always}
  case "$credential_image_pull_policy" in always|missing|never) ;; *) die '镜像拉取策略仅支持always、missing或never' ;; esac
  credential_pull_image "$image" || die '后端工具镜像不可用；尚未启动服务'
  while ! credential_tool --help >/dev/null 2>&1 || [[ $(credential_tool artifact capabilities 2>/dev/null) != plaintext-native-v1 ]]; do
    [[ -t 0 ]] || die '当前后端镜像不支持凭据安装工具；请使用本版本配套镜像，或在交互终端重新执行原命令按提示选择镜像'
    IFS= read -r -p '当前后端镜像不支持凭据工具，请输入本版本配套后端镜像地址：' image || die '镜像选择已取消'
    [[ -n $image ]] || die '镜像地址不能为空，现有数据未改变'
    credential_pull_image "$image" || die '配套后端镜像不可用，现有数据未改变'
  done
  env_set "$ENV_FILE" BISHENG_BACKEND_IMAGE "$image"
  credential_runtime_prepare
fi
# Option C placeholders for legacy ES helper argv (ignored by plaintext apply_runtime).
credential_runtime_binary="${credential_runtime_binary:-}"
credential_role_key_dir="${credential_role_key_dir:-}"
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
credential_runtime_permissions
credential_sealed_environment_cleanup
credential_es_defer_rotation=false
if [[ $PREPARE_ONLY != true ]]; then
  if [[ -n ${credential_sealed_migration_session:-} ]] && [[ $(credential_sealed_migration_tool migrate-info --session-dir "$credential_sealed_migration_session" --field es-mode) != none ]]; then
    credential_es_defer_rotation=true
    printf '本次先完成ES认证与凭据迁移，再继续逐项选择其他组件是否改密。\n'
  else credential_rotation_select; fi
fi
find "$BUNDLE" -maxdepth 1 -type f -exec chgrp "$secret_gid" {} + -exec chmod 640 {} +
if [[ -d $BUNDLE/es-config ]]; then find "$BUNDLE/es-config" -type f -exec chgrp "$secret_gid" {} + -exec chmod 640 {} +; fi
if [[ -d $BUNDLE/milvus-config ]]; then find "$BUNDLE/milvus-config" -type f -exec chgrp "$secret_gid" {} + -exec chmod 640 {} +; fi
# Commit the paired paths and revision together. An interruption must not leave
# a new bundle pointing at the previous key or revision in the active .env.
activation="$credential_store/activation.env.tmp"
cp "$ENV_FILE" "$activation"
env_set "$activation" BISHENG_SECRET_FILE_GID "$secret_gid"
env_set "$activation" BISHENG_CREDENTIALS_DIR "$BUNDLE"
env_set "$activation" BISHENG_SECRET_KEYS_FILE "$KEY_FILE"
env_set "$activation" BISHENG_CREDENTIAL_REVISION "$REVISION"
es_security=$(credential_tool artifact info --bundle "$BUNDLE" --field es-security --key-file "$KEY_FILE") || die '无法核实ES认证模式'
env_set "$activation" BISHENG_ES_SECURITY_ENABLED "$es_security"
mv "$activation" "$ENV_FILE"
compose config --quiet
if [[ "$PREPARE_ONLY" = true ]]; then deploy_succeed '配置已生成并通过 Compose 校验。'; fi
# Pull first so missing images stop deployment before existing services change.
if [[ $credential_image_pull_policy = always ]]; then
  credential_registry_login
  compose pull || die '镜像拉取失败，尚未修改账号'
else
  image_list=$(compose config --images) || die '镜像清单读取失败'
  [[ -n $image_list ]] || die '镜像清单为空，未启动服务'
  while IFS= read -r native_image; do
    [[ -z $native_image ]] || credential_pull_image "$native_image" || die '配套镜像不可用，未修改账号'
  done <<< "$image_list"
fi
credential_sealed_migration_run
if [[ $credential_es_defer_rotation = true ]]; then credential_rotation_select; fi
if [[ -n ${credential_rotation_manifest:-}${credential_rotation_session:-} ]]; then
  if [[ $credential_adopt = true ]]; then credential_migrate_database; fi
  credential_rotation_run || die '改密编排没有完成，保留计划后重试原命令'
  credential_lock_release
  deploy_succeed '选中密码已更新并验证；未选组件保持原配置。'
fi
if [[ ${credential_sealed_migration_completed:-false} = true ]]; then
  credential_lock_release
  deploy_succeed '加密文件迁移与服务恢复已完成，密码保持不变；后续继续执行原部署命令。'
fi
if [[ $credential_adopt = true || ${credential_preserve_native:-false} = true ]]; then
  if [[ $credential_adopt = true ]]; then credential_migrate_database; fi
  # All native identities and their original mounts stay unchanged during key
  # adoption. Recreating them with fresh authentication would be a password change.
  compose up -d --no-deps --force-recreate backend backend_worker
  compose up -d --no-deps frontend
  credential_lock_release
  deploy_succeed '密钥外置迁移与应用启动已执行，原密码/认证状态保留；请验证组织同步、沙箱及业务，待治理密码不表示已完成改密。'
fi
# Existing volumes retain their real credentials. Changing initialization files
# does not rotate accounts; the read-only new-connection check must pass first.
credential_online_enforce=true
if [[ -f $BUNDLE/deployment-policy.json ]]; then credential_online_enforce=''; fi
credential_start_native
compose up -d --no-deps --force-recreate backend backend_worker
compose up -d
credential_wait_apps
credential_lock_release
deploy_succeed '已执行启动；部署凭据已保存，后续继续使用原命令即可。请使用 Compose ps / logs 确认业务就绪。'
