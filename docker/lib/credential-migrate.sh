#!/usr/bin/env bash
# Legacy adoption stays in the original installer. It never rotates native passwords.
credential_migration_consent() {
  local answer=${BISHENG_ALLOW_CREDENTIAL_MIGRATION:-}
  if [[ -f "$credential_store/migration/authorized" ]]; then return; fi
  if [[ $answer != yes ]]; then
    [[ -t 0 ]] || die '检测到已有中间件数据，请在交互终端重新执行原命令，按引导迁移现有身份；不会按新装覆盖'
    printf '检测到旧部署，将保持中间件实际密码不变，外置密钥并迁移组织同步/沙箱密文。\n'
    IFS= read -r -p '请确认维护窗口和其他节点已停写，允许暂停本机应用并执行密文迁移（输入yes继续）：' answer || die '维护确认已取消'
  fi
  [[ $answer = yes ]] || die '未确认维护，现有部署未改变'
  mkdir -p "$credential_store/migration"
  chmod 700 "$credential_store/migration"
  printf 'authorized\n' > "$credential_store/migration/authorized"
}

credential_stop_legacy_apps() {
  local name
  for name in bisheng-frontend bisheng-gateway bisheng-backend-worker bisheng-backend; do
    if docker container inspect "$name" >/dev/null 2>&1; then
      docker stop "$name" >/dev/null || die '暂停旧应用失败，尚未提交数据库迁移，请核对现有服务'
    fi
  done
}

credential_prepare_legacy() {
  local directory="$credential_store/migration" backup_source attempt
  credential_migration_consent
  printf '正在读取现用配置和旧密钥，秘密内容不会显示在终端。\n'
  if [[ ! -s $directory/source.yaml ]]; then
    if ! docker cp bisheng-backend:/app/bisheng/config.yaml "$directory/source.yaml" >/dev/null 2>&1; then
      backup_source="$volume/bisheng/config/config.yaml"
      if [[ -t 0 ]]; then
        IFS= read -r -p "请输入现用业务配置完整路径（回车使用 $backup_source）：" answer || die '配置恢复已取消'
        backup_source=${answer:-$backup_source}
      fi
      [[ $backup_source = /* && -f $backup_source ]] || die '现用业务配置不可读；请从备份恢复后重新执行原命令'
      cp "$backup_source" "$directory/source.yaml"
    fi
    chmod 600 "$directory/source.yaml"
  fi
  if [[ ! -s $directory/runtime-env.json ]]; then
    if ! docker inspect --format '{{json .Config.Env}}' bisheng-backend > "$directory/runtime-env.json" 2> "$directory/read-runtime.log"; then
      [[ -t 0 ]] || die '无法读取现有后端的环境来源；请在交互终端重新执行原命令并提供环境快照备份，不会猜测旧密码'
      IFS= read -r -p '请输入原后端环境快照JSON备份文件的完整路径：' backup_source || die '环境来源恢复已取消'
      [[ $backup_source = /* && -f $backup_source ]] || die '环境快照备份不可读，旧部署数据未改变'
      cp "$backup_source" "$directory/runtime-env.json"
    fi
    chmod 600 "$directory/runtime-env.json" "$directory/read-runtime.log"
  fi
  if [[ ! -s $directory/retiring.json ]]; then
    # Only a confirmed, trusted existing container is queried. No source/Git
    # fallback or fixed key is bundled with the new release.
    if ! docker exec bisheng-backend python -c 'import json; from bisheng.core.config.settings import secret_key; print(json.dumps({"version":1,"keys":[secret_key]}))' \
      > "$directory/retiring.json" 2> "$directory/read-key.log"; then
      rm -f "$directory/retiring.json"
    fi
    if [[ ! -s $directory/retiring.json ]]; then
      [[ -t 0 ]] || die '无法取得旧密钥，请在交互终端重新执行原命令并按引导提供备份；不能用新密钥代替'
      IFS= read -r -p '请输入旧密钥备份JSON文件的完整路径：' backup_source || die '旧密钥恢复已取消'
      [[ $backup_source = /* && -f $backup_source ]] || die '旧密钥备份不可读，数据未改变'
      cp "$backup_source" "$directory/retiring.json"
    fi
    chmod 600 "$directory/retiring.json" "$directory/read-key.log"
  fi
  if ! credential_tool validate-keyring --key-file "$directory/retiring.json"; then
    [[ -t 0 ]] || die '旧密钥文件验证失败；请在交互终端重新执行原命令并提供有效备份'
    IFS= read -r -p '旧密钥不可用，请输入有效备份JSON文件完整路径：' backup_source || die '恢复已取消'
    [[ $backup_source = /* && -f $backup_source ]] || die '旧密钥备份不可读'
    cp "$backup_source" "$directory/retiring.json"
    chmod 600 "$directory/retiring.json"
    credential_tool validate-keyring --key-file "$directory/retiring.json" || die '备份密钥仍无效，数据未改变'
  fi
  if [[ ! -f $credential_store/keys/primary.json ]]; then
    credential_tool keygen --out "$credential_store/keys/primary.json" || die '新密钥准备失败，旧部署数据未改变'
  fi
  KEY_FILE="$credential_store/keys/transition.json"
  if [[ ! -f $KEY_FILE ]]; then
    credential_tool join-keyrings --primary-file "$credential_store/keys/primary.json" \
      --retiring-file "$directory/retiring.json" --out "$KEY_FILE" || die '旧密钥验证失败，请核对备份；不会生成备用默认密钥'
  fi
  attempt=$(mktemp -d "$credential_store/revisions/adopt.XXXXXX")
  BUNDLE="$attempt/bundle"
  credential_tool prepare --mode adopt-key --config "$directory/source.yaml" \
    --runtime-env-file "$directory/runtime-env.json" --env-file "$ENV_FILE" \
    --deployment-root "$volume" --key-file "$KEY_FILE" --out-dir "$BUNDLE" \
    || die '现用配置迁移预检失败，已保留原资料，修复后重新执行原命令继续'
  credential_adopt=true
}

credential_migrate_database() {
  local directory="$credential_store/migration" backup="$credential_store/migration-backup"
  credential_migration_consent
  [[ -f $directory/complete ]] && return
  mkdir -p "$backup"
  chmod 700 "$backup"
  credential_stop_legacy_apps
  printf '正在备份并迁移数据库密文；中间件实际密码保持不变。\n'
  if [[ -f $backup/run/plan.json ]]; then
    compose run --rm --no-deps -v "$backup:/maintenance" --entrypoint python backend \
      scripts/rewrap_credentials.py --all-tenants --resume /maintenance/run --apply \
      || die '密文迁移尚未完成，业务保持停止；修复原因后重新执行原命令会自动续跑原计划'
  else
    compose run --rm --no-deps -v "$backup:/maintenance" --entrypoint python backend \
      scripts/rewrap_credentials.py --all-tenants --backup-dir /maintenance/run \
      || die '数据库密文预检失败，业务保持停止；修复后重新执行原命令'
    compose run --rm --no-deps -v "$backup:/maintenance" --entrypoint python backend \
      scripts/rewrap_credentials.py --all-tenants --backup-dir /maintenance/run --apply \
      || die '数据库迁移尚未完成；原备份已保留，重新执行原命令将自动识别并续跑'
  fi
  compose run --rm --no-deps -v "$backup:/maintenance" --entrypoint python backend \
    scripts/rewrap_credentials.py --all-tenants --verify-primary-only \
    || die '新密钥独立复检失败，业务保持停止，请保留过渡密钥后重试'
  printf 'complete\n' > "$directory/complete.tmp"
  mv "$directory/complete.tmp" "$directory/complete"
}
