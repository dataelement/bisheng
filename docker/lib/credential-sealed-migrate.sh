#!/usr/bin/env bash
# Same-account native file conversion. Actual middleware passwords never change.
credential_sealed_migration_tool() {
  if [[ $1 = migrate-prepare ]]; then
    local network
    network=$(env_get "$ENV_FILE" BISHENG_NETWORK_NAME)
    bash "$SCRIPT_DIR/credentials.sh" --image "$image" --network "${network:-bisheng-network}" artifact "$@" --key-file "$KEY_FILE"
    return
  fi
  credential_tool artifact "$@" --key-file "$KEY_FILE"
}

credential_sealed_environment_cleanup() {
  local session
  session=$(mktemp -d "$credential_store/environment-cleanup.XXXXXX") || die '无法准备环境别名加密备份'
  credential_sealed_migration_tool sanitize-env --bundle "$BUNDLE" --env-file "$ENV_FILE" --session-dir "$session" \
    || die '环境密码别名清理预检失败；配套备份保留，尚未切换服务'
  # No credential aliases means no backup/context was needed.
  if [[ ! -f $session/.artifact-context.json ]]; then rmdir "$session"; fi
}

credential_sealed_migration_prepare() {
  local version session phase
  credential_sealed_migration_session=''
  credential_sealed_cleanup_only=false
  credential_sealed_migration_completed=false
  if [[ -f $credential_store/sealed-migration.active ]]; then
    IFS= read -r session < "$credential_store/sealed-migration.active"
    [[ $session = "$credential_store/migrations/"* && -d $session && ! -L $session ]] || die '加密文件迁移恢复标记异常，保留全部文件'
    phase=$(credential_sealed_migration_tool migrate-info --session-dir "$session" --field phase) || die '加密文件迁移签名验证失败'
    if [[ $phase = COMPLETE ]]; then
      credential_sealed_cleanup_only=true
    else
      credential_migration_consent
    fi
    BUNDLE=$(credential_sealed_migration_tool migrate-info --session-dir "$session" --field bundle) || die '迁移目标读取失败'
    credential_sealed_migration_session=$session
    local resumed_es
    resumed_es=$(credential_sealed_migration_tool migrate-info --session-dir "$session" --field es-mode) || die 'ES恢复状态读取失败'
    [[ $resumed_es = none ]] || credential_es_already_selected=true
    REVISION=''
    return
  fi
  version=$(credential_sealed_migration_tool info --bundle "$BUNDLE" --field version) || die '无法识别原凭据文件版本'
  local es_options=()
  if [[ $version = 2 ]]; then
    # New installs have no live source. A retained no-auth v2 deployment may
    # later opt in through the same installer instead of an unsupported RPC.
    [[ ${credential_fresh_install:-false} != true ]] || return 0
    if command -v credential_es_select >/dev/null 2>&1; then
      local configured
      configured=$(credential_es_tool es-info --bundle "$BUNDLE" --env-file "$ENV_FILE") || die 'ES配置读取失败'
      [[ $configured = missing ]] || return 0
      credential_es_select
      if [[ $credential_es_mode = retain && -f $BUNDLE/deployment-policy.json ]]; then return 0; fi
      es_options+=(--es-mode "$credential_es_mode")
      [[ -z ${credential_es_inputs:-} ]] || es_options+=(--inputs "$credential_es_inputs")
    else return 0; fi
  elif [[ $version != 1 ]]; then die '不支持的原凭据版本'; fi
  credential_migration_consent
  mkdir -p "$credential_store/migrations"
  chmod 700 "$credential_store/migrations"
  session="$credential_store/migrations/$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')"
  case "$BUNDLE/" in "$credential_store/"*) ;; *) es_options+=(--allow-external-source) ;; esac
  if [[ $version = 1 ]] && command -v credential_es_select >/dev/null 2>&1; then
    credential_es_select
    es_options+=(--es-mode "$credential_es_mode")
    [[ -z ${credential_es_inputs:-} ]] || es_options+=(--inputs "$credential_es_inputs")
  fi
  credential_sealed_migration_tool migrate-prepare --bundle "$BUNDLE" --policy-root "$credential_store" \
    --out-dir "$session" --env-file "$ENV_FILE" ${es_options[@]+"${es_options[@]}"} >/dev/null || die '原文件转换预检失败，账号未改变，保留原配置后重试'
  printf '%s\n' "$session" > "$credential_store/sealed-migration.active.tmp"
  mv "$credential_store/sealed-migration.active.tmp" "$credential_store/sealed-migration.active"
  credential_sealed_migration_session=$session
  BUNDLE="$session/bundle"
  REVISION=''
}

credential_sealed_migration_verify() {
  [[ -n ${credential_sealed_migration_session:-} ]] || return 0
  local phase
  phase=$(credential_sealed_migration_tool migrate-info --session-dir "$credential_sealed_migration_session" --field phase) || die '迁移状态验证失败'
  if [[ $phase = SEALED || $phase = VERIFIED ]]; then
    credential_sealed_migration_tool migrate-verify --session-dir "$credential_sealed_migration_session" \
      --bundle "$BUNDLE" --env-file "$ENV_FILE" >/dev/null || die '转换核验或策略写入失败，未切换服务；保留迁移材料后重试'
  fi
}

credential_sealed_migration_run() {
  [[ -n ${credential_sealed_migration_session:-} ]] || return 0
  local ids id phase
  credential_online_enforce=''
  if [[ ${credential_sealed_cleanup_only:-false} = true ]]; then
    credential_check_online
  else
    credential_migration_consent
    if command -v credential_es_preflight >/dev/null 2>&1; then credential_es_preflight; fi
    credential_stop_legacy_apps
    if command -v credential_es_run >/dev/null 2>&1; then credential_es_run; fi
    if command -v credential_migrate_database >/dev/null 2>&1; then
      local source_mode
      source_mode=$(credential_sealed_migration_tool migrate-info --session-dir "$credential_sealed_migration_session" --field source-mode) || die '无法核实旧密钥迁移范围'
      if [[ $source_mode = adopt-key ]]; then credential_migrate_database; fi
    fi
    printf '正在切换原生加密配置，未选中改密的账号保持原密码。\n'
    credential_start_native
    compose up -d --no-deps --force-recreate backend backend_worker frontend || die '应用切换失败；旧文件和加密备份均已保留，重新执行原命令恢复'
  fi
  credential_wait_apps
  # Another deployment or a standalone maintenance tool may share the old path.
  # Inspect bind sources only; never read other containers' secret environments.
  ids=$(docker ps --all -q) || die '无法核实已停止容器的旧文件引用，拒绝清理'
  [[ -n $ids ]] || die '缺少本项目消费者证据，拒绝清理'
  {
    while IFS= read -r id; do
      docker inspect --format '{{range .Mounts}}{{if eq .Type "bind"}}{{println .Source}}{{end}}{{end}}' "$id" || exit 1
    done <<< "$ids"
  } | credential_sealed_migration_tool migrate-bindings --session-dir "$credential_sealed_migration_session" \
    || die '仍有容器引用原明文文件；未清理任何旧文件，请保留迁移目录后重试'
  phase=$(credential_sealed_migration_tool migrate-info --session-dir "$credential_sealed_migration_session" --field phase) || die '清理前状态验证失败'
  if [[ $phase != COMPLETE ]]; then
    credential_sealed_migration_tool migrate-mark --session-dir "$credential_sealed_migration_session" --phase CONSUMERS_SWITCHED \
      || die '消费者切换状态保存失败，旧文件保留'
  fi
  credential_sealed_migration_tool migrate-clean --session-dir "$credential_sealed_migration_session" --policy-root "$credential_store" \
    || die '旧文件清理校验失败，加密备份保留，重新执行原命令继续'
  rm "$credential_store/sealed-migration.active"
  if [[ ${credential_sealed_cleanup_only:-false} != true ]]; then credential_sealed_migration_completed=true; fi
  printf '原生文件转换完成，配套恢复备份已加密保存。\n'
}
