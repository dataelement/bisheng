#!/usr/bin/env bash
# Option C helpers: plaintext native mounts; no Go credential-runtime delivery.

credential_runtime_hash() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | awk '{print $1}'
  else die '缺少SHA256校验命令，尚未修改账号'; fi
}

# Discover a Compose service before .env activation. The chart requires
# BISHENG_CREDENTIALS_DIR and related paths, so `compose ps` cannot run yet.
credential_compose_service_ids() {
  local service=$1 project
  project=$(env_get "$ENV_FILE" COMPOSE_PROJECT_NAME)
  project=${project:-$(basename "$SCRIPT_DIR")}
  docker ps -q --filter "label=com.docker.compose.project=$project" \
    --filter "label=com.docker.compose.service=$service"
}

credential_runtime_prepare() {
  # Option C: no Go binary extraction. Kept as a no-op for callers that still invoke it.
  credential_runtime_binary="${credential_runtime_binary:-}"
  credential_role_key_dir="${credential_role_key_dir:-}"
  [[ -f "${SCRIPT_DIR}/lib/credential-runtime.sh" ]] || die '部署文件不完整'
}

credential_runtime_seed_bundle() {
  local missing role attempt source_image source_path container source_var status temporary_container
  missing=$(credential_tool artifact info --field seeds --bundle "$BUNDLE" --key-file "$KEY_FILE") || die '无法识别内存配置准备状态'
  while IFS= read -r role; do
    [[ -n $role ]] || continue
    attempt=$(mktemp -d "$credential_store/revisions/seed.XXXXXX") || die '无法准备加密配置目录'
    if [[ $role = redis ]]; then
      if [[ -n ${credential_sealed_migration_session:-} ]]; then
        container=$(credential_compose_service_ids redis) || die '无法核实旧Redis配置归属'
        [[ -n $container ]] || die '旧版迁移需要运行中的Redis以保留真实配置，账号未修改'
        [[ $container != *$'\n'* ]] || die '旧Redis配置归属不唯一，账号未修改'
        local redis_network
        redis_network=$(env_get "$ENV_FILE" BISHENG_NETWORK_NAME)
        docker exec "$container" cat /etc/redis.conf \
          | bash "$SCRIPT_DIR/credentials.sh" --image "$image" --network "${redis_network:-bisheng-network}" artifact seed --role redis --preserve-redis-acl \
            --bundle "$BUNDLE" --out-dir "$attempt/bundle" --key-file "$KEY_FILE" --env-file "$ENV_FILE" >/dev/null \
          || die '旧Redis配置无法导入，账号未修改'
      else
        [[ -r "$volume/redis/redis.conf" ]] || die '无法读取现有Redis基础配置，账号未修改'
        credential_tool artifact seed --role redis --bundle "$BUNDLE" --out-dir "$attempt/bundle" --key-file "$KEY_FILE" < "$volume/redis/redis.conf" >/dev/null \
          || die 'Redis配置准备失败，保留现场后重试'
      fi
    else
      case "$role" in
        elasticsearch) source_var=ELASTICSEARCH_IMAGE; source_path=/opt/bitnami/elasticsearch/config ;;
        milvus) source_var=MILVUS_IMAGE; source_path=/milvus/configs ;;
        *) die '未知原生配置角色' ;;
      esac
      source_image=$(env_get "$ENV_FILE" "$source_var")
      [[ -n $source_image ]] || die '缺少配套中间件镜像，账号未修改'
      docker image inspect "$source_image" >/dev/null 2>&1 || docker pull "$source_image" || die '中间件镜像不可用，账号未修改'
      container=$(credential_compose_service_ids "$role") || die '无法核实本部署的原生配置来源'
      [[ -z $container || $container != *$'\n'* ]] || die '本部署的原生配置来源不唯一，账号未修改'
      temporary_container=false
      if [[ -z $container ]]; then
        [[ -z ${credential_sealed_migration_session:-} ]] || die '旧版文件迁移要求原中间件仍在运行，以保留实际配置；尚未修改账号'
        container=$(docker create --network none --entrypoint /nonexistent "$source_image") || die '无法读取配套镜像模板'
        temporary_container=true
      fi
      if docker cp -L "$container:$source_path" - \
        | credential_tool artifact seed --role "$role" --bundle "$BUNDLE" --out-dir "$attempt/bundle" --key-file "$KEY_FILE" >/dev/null; then status=0
      else status=$?; fi
      if [[ $temporary_container = true ]]; then docker rm "$container" >/dev/null || die '模板读取临时容器清理失败'; fi
      [[ $status = 0 ]] || die '中间件模板准备失败，保留配置和密钥后重试'
    fi
    BUNDLE="$attempt/bundle"
  done <<< "$missing"
  credential_runtime_publish_bundle
}

credential_runtime_publish_bundle() {
  local destination revision
  revision=$(credential_revision "$BUNDLE")
  [[ $revision =~ ^[0-9a-f]{32}$ ]] || die '完整配置版本无效'
  destination="$credential_store/revisions/$revision"
  if [[ $BUNDLE != "$destination" ]]; then
    credential_tool artifact publish --bundle "$BUNDLE" --destination "$destination" --key-file "$KEY_FILE" >/dev/null \
      || die '完整配置发布失败，保留现有版本后重试'
    BUNDLE=$destination
  fi
}

# Locked openfga images load datastore via env_file; keep openfga.env in sync
# with openfga.yaml (SSOT) for bundles prepared before this pairing existed.
credential_ensure_openfga_env() {
  local yaml=$BUNDLE/openfga.yaml env_file=$BUNDLE/openfga.env engine uri
  [[ -f $yaml ]] || return 0
  [[ -f $env_file ]] && return 0
  engine=$(awk '/^[[:space:]]*engine:/{sub(/^[^:]+:[[:space:]]*/,""); gsub(/[[:space:]]+$/,""); print; exit}' "$yaml")
  uri=$(awk '/^[[:space:]]*uri:/{sub(/^[^:]+:[[:space:]]*/,""); gsub(/[[:space:]]+$/,""); print; exit}' "$yaml")
  [[ -n $engine && -n $uri ]] || die 'openfga.yaml 缺少 datastore.engine/uri，无法生成 openfga.env'
  printf 'OPENFGA_DATASTORE_ENGINE=%s\nOPENFGA_DATASTORE_URI=%s\n' "$engine" "$uri" > "$env_file.tmp"
  chmod 640 "$env_file.tmp"
  chgrp "$secret_gid" "$env_file.tmp" 2>/dev/null || true
  mv "$env_file.tmp" "$env_file"
}

credential_runtime_permissions() {
  local group member
  member=false
  for group in $(id -G); do [[ $group != "$secret_gid" ]] || member=true; done
  [[ $member = true ]] || die '部署账号不属于已配置的凭据读取组；请由管理员一次性移交目录或调整部署组，账号未修改'
  [[ -O $KEY_FILE ]] || die '现有密钥不属于部署账号，不能自动调整；请由管理员一次性移交可读的配套密钥，账号未修改'
  chgrp "$secret_gid" "$KEY_FILE" || die '不能设置必要的密钥读取组'
  chmod 640 "$KEY_FILE" || die '不能设置密钥最小读取权限'
  credential_ensure_openfga_env
}

credential_wait_apps() {
  local attempt service container state ready
  for attempt in {1..120}; do
    ready=true
    for service in backend backend_worker frontend; do
      container=$(compose ps --all -q "$service") || die '无法核实应用容器状态，请保留凭据目录后重试原命令'
      [[ -n $container && $container != *$'\n'* ]] || die "应用容器未创建或归属不唯一：$service"
      state=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container") || die "无法读取应用状态：$service"
      case "$state" in
        healthy|running) ;;
        unhealthy|exited|dead) die "应用尚未就绪：$service；现用凭据已保留，修复后重试原命令" ;;
        *) ready=false ;;
      esac
    done
    [[ $ready != true ]] || return 0
    sleep 3
  done
  die '应用启动等待超时；现用凭据已保留，修复后重新执行原命令'
}

credential_start_native() {
  local ready attempt service container state executable network
  credential_ensure_openfga_env
  if [[ -z ${credential_es_override:-} ]] && command -v credential_es_preserve_runtime >/dev/null 2>&1; then
    credential_es_preserve_runtime
  fi
  if [[ -n ${credential_es_override:-} ]]; then
    # A Compose merge would add default ES ports/mounts absent from the old service.
    "${COMPOSE[@]}" -p "$(env_get "$ENV_FILE" COMPOSE_PROJECT_NAME)" -f "$credential_es_override" up -d --no-deps elasticsearch
    compose up -d mysql-init openfga redis etcd minio milvus
  else
    compose up -d mysql-init openfga redis elasticsearch etcd minio milvus
  fi
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
      if [[ $service = elasticsearch && $state = healthy ]]; then
        # Bitnami's temporary setup JVM must exit before accepting readiness.
        executable=$(docker exec "$container" cat /proc/1/comm) || die '无法确认ES启动阶段'
        [[ $executable = java ]] || ready=false
      fi
    done
    [[ $ready = true ]] && break
    sleep 3
  done
  [[ $ready = true ]] || die '中间件启动等待超时；应用尚未启动'
  credential_check_online
}

credential_check_online() {
  local network
  network=$(env_get "$ENV_FILE" BISHENG_NETWORK_NAME)
  bash "$SCRIPT_DIR/credentials.sh" --image "$image" --network "${network:-bisheng-network}" check --bundle "$BUNDLE" --key-file "$KEY_FILE" --env-file "$ENV_FILE" --online ${credential_online_enforce:+--enforce} || die '中间件新连接检查失败；未启动应用。核对真实账号状态后重试'
}
