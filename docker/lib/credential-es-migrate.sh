#!/usr/bin/env bash
# The existing installer owns every prompt and native ES lifecycle operation.

credential_es_tool() {
  local network=none
  case "$1" in
    es-discover|es-freeze|es-observe|es-verify|es-persist)
      network=$(env_get "$ENV_FILE" BISHENG_NETWORK_NAME)
      network=${network:-bisheng-network}
      ;;
  esac
  bash "$SCRIPT_DIR/credentials.sh" --image "$image" --network "$network" artifact "$@" --key-file "$KEY_FILE"
}

credential_es_select() {
  local configured state answer folder previous_inputs
  credential_es_mode=existing
  credential_es_inputs=''
  configured=$(credential_es_tool es-info --bundle "$BUNDLE" --env-file "$ENV_FILE") || die '无法读取原ES配置'
  state=$(credential_es_tool es-discover --bundle "$BUNDLE" --env-file "$ENV_FILE") || die 'ES服务端安全状态未知；尚未修改账号，请核对网络和服务状态'
  if [[ $configured = configured && $state = AUTHENTICATED ]]; then return 0; fi
  case "$state" in
    DISABLED)
      printf '检测到原ES未开启认证；开启时保留现有索引和数据卷。\n'
      [[ -t 0 ]] || die '无认证ES升级需要在原命令中选择是否启用认证；非交互部署尚未作出选择'
      while true; do
        IFS= read -r -p '是否为Elasticsearch开启认证并设置密码？[y/N]：' answer || die 'ES认证选择已取消'
        case "$answer" in y|Y|yes) credential_es_mode=enable; break ;; ''|n|N|no) credential_es_mode=retain; break ;; *) printf '请输入y或n。\n' ;; esac
      done
      ;;
    AUTH_REQUIRED)
      credential_es_mode=recover
      printf 'ES服务端要求认证，但后端缺少凭据。请输入现用elastic密码；不会重置未知账号。\n'
      ;;
    *) die 'ES状态与现有配置不一致；请保留现场，不会猜测管理账号' ;;
  esac
  credential_es_already_selected=true
  [[ $credential_es_mode != retain ]] || return 0
  folder=$(mktemp -d "$credential_store/es-inputs.XXXXXX") || die '无法准备ES加密输入'
  credential_es_tool context --out "$folder/.artifact-context.json" --deployment-id "$(credential_deployment_identity)" >/dev/null || die '无法准备ES输入身份'
  previous_inputs=${credential_inputs:-}
  credential_inputs=$folder
  credential_prompt_secret elasticsearch Elasticsearch "$folder/elasticsearch.password" password_file
  credential_inputs=$previous_inputs
  printf 'version: 1\nelasticsearch:\n  password_file: elasticsearch.password\n' > "$folder/inputs.yaml"
  credential_es_inputs="$folder/inputs.yaml"
}

credential_es_write_override() {
  credential_es_override="$credential_sealed_migration_session/es-recreate.json"
  # First pass has no sealed runtime yet; return quietly so capture can run.
  if ! compgen -G "$credential_sealed_migration_session/es-runtime-"*.sealed >/dev/null; then
    return 1
  fi
  credential_es_tool es-export --session-dir "$credential_sealed_migration_session" > "$credential_es_override.tmp" || return 1
  mv "$credential_es_override.tmp" "$credential_es_override"
}

credential_es_preserve_runtime() {
  local container
  container=$(compose ps -q elasticsearch) || die '无法核实当前ES运行配置'
  [[ -n $container ]] || return 0
  [[ $container != *$'\n'* ]] || die 'ES归属不唯一，不覆盖已有配置'
  credential_es_override="$credential_store/es-current.json"
  docker inspect "$container" | credential_es_tool es-compile-current --bundle "$BUNDLE" \
    --secret-gid "$secret_gid" --env-file "$ENV_FILE" \
    > "$credential_es_override.tmp" || die '原ES挂载配置无法安全继承，未重建服务'
  mv "$credential_es_override.tmp" "$credential_es_override"
}

credential_es_ready() {
  local attempt process observation
  for attempt in {1..90}; do
    process=$(docker exec "$credential_es_container" cat /proc/1/comm 2>/dev/null) || process=''
    if [[ $process = java ]]; then
      observation=$(credential_es_tool es-observe --session-dir "$credential_sealed_migration_session" --env-file "$ENV_FILE") || return 1
      case "$observation" in READY|KEEP|DENIED) printf '%s' "$observation"; return 0 ;; esac
    fi
    sleep 2
  done
  return 1
}

credential_es_anonymous_reachable() {
  local network=$1
  # Host Python is not used; probe through the same backend image/network as install.
  docker run --rm --network "$network" --entrypoint python "$image" -c \
    'import urllib.request,sys
try:
  with urllib.request.urlopen("http://elasticsearch:9200/", timeout=5) as response:
    sys.exit(0 if 200 <= getattr(response, "status", 200) < 300 else 1)
except Exception:
  sys.exit(1)'
}

credential_es_preflight() {
  local mode source network component
  mode=$(credential_sealed_migration_tool migrate-info --session-dir "$credential_sealed_migration_session" --field es-mode) || die '无法核实ES预检范围'
  [[ $mode != none ]] || return 0
  source=$(credential_sealed_migration_tool migrate-info --session-dir "$credential_sealed_migration_session" --field source) || die '原配置读取失败'
  # A resumed security enable may already reject the original anonymous client.
  local phase
  phase=$(credential_sealed_migration_tool migrate-info --session-dir "$credential_sealed_migration_session" --field es-phase) || die 'ES阶段读取失败'
  [[ $phase = PREPARED ]] || return 0
  network=$(env_get "$ENV_FILE" BISHENG_NETWORK_NAME)
  network=${network:-bisheng-network}
  if [[ $mode = recover ]]; then source=$BUNDLE; fi
  # enable/retain start from (or keep) an unauthenticated ES. Security
  # authenticate() is unavailable until enable completes, and published images
  # may still probe that way — check passworded peers separately, ES anonymously.
  if [[ $mode = enable || $mode = retain ]]; then
    for component in mysql redis minio milvus; do
      bash "$SCRIPT_DIR/credentials.sh" --image "$image" --network "$network" check \
        --bundle "$source" --key-file "$KEY_FILE" --env-file "$ENV_FILE" --online --component "$component" \
        || die '原中间件连接预检失败；请确认中间件仍在运行且应用网络可达'
    done
    credential_es_anonymous_reachable "$network" \
      || die '原ES无认证连通预检失败；请确认ES仍在运行且应用网络可达，尚未执行设密'
    return 0
  fi
  bash "$SCRIPT_DIR/credentials.sh" --image "$image" --network "$network" check \
    --bundle "$source" --key-file "$KEY_FILE" --env-file "$ENV_FILE" --online \
    || die '原中间件连接预检失败；请确认认证配置与应用网络可达'
}

credential_es_run() {
  local mode phase container observation answer log retry=()
  mode=$(credential_sealed_migration_tool migrate-info --session-dir "$credential_sealed_migration_session" --field es-mode) || die '无法核实ES升级状态'
  [[ $mode != none ]] || return 0
  credential_es_already_selected=true
  phase=$(credential_sealed_migration_tool migrate-info --session-dir "$credential_sealed_migration_session" --field es-phase) || die '无法核实ES升级阶段'
  if [[ $phase != PREPARED && $phase != FROZEN ]]; then
    [[ -t 0 ]] || die 'ES升级中断，请在交互终端重新执行原命令恢复'
    IFS= read -r -p 'ES恢复方式：1继续原计划，2配对回退到原认证配置［回车选1］：' answer || die '恢复选择已取消'
    case "$answer" in
      2)
        [[ $mode = enable ]] || die '原服务已认证或选择保留，不允许通过此流程关闭认证'
        IFS= read -r -p '配对回退将恢复原无认证状态；确认维护窗口有效并同意该状态，输入yes：' answer || die '回退取消'
        [[ $answer = yes ]] || die '未确认回退，原计划保留'
        credential_es_tool es-rollback --session-dir "$credential_sealed_migration_session" >/dev/null || die '配对回退准备失败，保留加密状态'
        BUNDLE=$(credential_sealed_migration_tool migrate-info --session-dir "$credential_sealed_migration_session" --field bundle) || die '无法读取回退配置'
        REVISION=$(credential_revision "$BUNDLE")
        : # Option C: plaintext native mounts; no derived role keyrings.
        credential_sealed_migration_tool migrate-verify --session-dir "$credential_sealed_migration_session" --bundle "$BUNDLE" --env-file "$ENV_FILE" >/dev/null || die '回退配置校验失败'
        local rollback_env="$credential_store/rollback-activation.env.tmp"
        cp "$ENV_FILE" "$rollback_env"
        env_set "$rollback_env" BISHENG_CREDENTIALS_DIR "$BUNDLE"
        env_set "$rollback_env" BISHENG_CREDENTIAL_REVISION "$REVISION"
        env_set "$rollback_env" BISHENG_ES_SECURITY_ENABLED false
        mv "$rollback_env" "$ENV_FILE"
        mode=retain
        ;;
      ''|1) ;;
      *) die '请输入1或2后重新执行原命令' ;;
    esac
  fi
  credential_es_tool es-freeze --session-dir "$credential_sealed_migration_session" --env-file "$ENV_FILE" || die 'ES原索引与认证状态预检失败；服务端未追加设密'
  if ! credential_es_write_override; then
    container=$(compose ps -q elasticsearch) || die '无法核实原ES容器'
    [[ -n $container && $container != *$'\n'* ]] || die '原ES容器归属不唯一'
    docker inspect "$container" | credential_es_tool es-capture --session-dir "$credential_sealed_migration_session" \
      --secret-gid "$secret_gid" --env-file "$ENV_FILE" \
      || die 'ES实际挂载与配置捕获失败，尚未开启认证'
    credential_es_write_override || die 'ES恢复配置导出失败'
  fi
  "${COMPOSE[@]}" -p "$(env_get "$ENV_FILE" COMPOSE_PROJECT_NAME)" -f "$credential_es_override" config --quiet || die 'ES迁移配置校验失败'
  "${COMPOSE[@]}" -p "$(env_get "$ENV_FILE" COMPOSE_PROJECT_NAME)" -f "$credential_es_override" up -d --no-deps elasticsearch || die 'ES配置切换失败；保留数据与加密状态后重跑原命令'
  credential_es_container=$(compose ps -q elasticsearch) || die '无法找到切换后的ES'
  observation=$(credential_es_ready) || die 'ES尚未就绪；应用保持暂停，重跑原命令恢复'
  if [[ $mode = enable ]]; then
    phase=$(credential_sealed_migration_tool migrate-info --session-dir "$credential_sealed_migration_session" --field es-phase) || die 'ES设密状态读取失败'
    if [[ $phase = PASSWORD_SET || $phase = VERIFIED ]]; then
      [[ $observation = READY ]] || die '已确认的ES目标身份不可用，保留现场，不重复覆盖账号'
    else
    if [[ $phase = PASSWORD_INTENT ]]; then
      IFS= read -r -p '上次ES设密结果不确定，是否重新设置为已保存的同一目标密码？输入yes：' answer || die '未确认重试'
      [[ $answer = yes ]] || die '未确认设密重试，原计划保留'
      retry=(--retry)
    fi
    credential_es_tool es-intent --session-dir "$credential_sealed_migration_session" ${retry[@]+"${retry[@]}"} || die 'ES设密意图未持久化，不执行账号写入'
    if [[ $observation = DENIED ]]; then
    log="$credential_sealed_migration_session/es-reset-$(od -An -N8 -tx1 /dev/urandom | tr -d ' \n').sealed"
    if ! docker exec --user 0:0 "$credential_es_container" bash -c '
      set +x; ulimit -c 0
      source /opt/bitnami/scripts/libos.sh
      IFS= read -r password < /run/secrets/elasticsearch.password || [[ -n $password ]]
      printf "%s\n%s\n" "$password" "$password" | (exec_as_user elasticsearch /opt/bitnami/elasticsearch/bin/elasticsearch-reset-password --username elastic --interactive --batch)
    ' 2>&1 | credential_es_tool seal-stream --out "$log" >/dev/null; then
      die 'ES设密返回异常；诊断已加密，应用保持暂停，重跑原命令核实结果'
    fi
    fi
    credential_es_tool es-persist --session-dir "$credential_sealed_migration_session" --env-file "$ENV_FILE" || die 'ES原生密码持久化结果不确定；保留计划后通过原命令核实恢复'
    fi
  fi
  credential_es_tool es-verify --session-dir "$credential_sealed_migration_session" --env-file "$ENV_FILE" || die 'ES认证或原索引验证未通过；应用保持暂停，可在原命令续跑或配对回退'
}
