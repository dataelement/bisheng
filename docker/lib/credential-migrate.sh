#!/usr/bin/env bash
# Legacy adoption remains guided by the original installer, with sealed captures.
credential_migration_consent() {
  local answer=${BISHENG_ALLOW_CREDENTIAL_MIGRATION:-}
  [[ ${credential_migration_confirmed:-false} != true ]] || return 0
  if [[ $answer != yes ]]; then
    [[ -t 0 ]] || die '已有部署需要维护确认；请在交互终端重新执行原命令，不会按新装覆盖'
    printf '将保持实际密码不变，外置密钥并迁移密文和凭据存储。\n'
    IFS= read -r -p '确认维护窗口和其他节点停写，允许暂停本机应用（输入yes继续）：' answer || die '维护确认已取消'
  fi
  [[ $answer = yes ]] || die '未确认维护，现有部署未改变'
  mkdir -p "$credential_store/migration"
  chmod 700 "$credential_store/migration"
  credential_migration_confirmed=true
}

credential_stop_legacy_apps() {
  local service project ids
  project=$(env_get "$ENV_FILE" COMPOSE_PROJECT_NAME)
  project=${project:-$(basename "$SCRIPT_DIR")}
  for service in frontend gateway backend_worker backend; do
    ids=$(docker ps -q --filter "label=com.docker.compose.project=$project" --filter "label=com.docker.compose.service=$service") || die '无法核实原应用归属'
    while IFS= read -r id; do
      [[ -z $id ]] || docker stop "$id" >/dev/null || die '暂停旧应用失败，尚未提交数据库迁移'
    done <<< "$ids"
  done
}

credential_prepare_legacy() {
  local directory="$credential_store/migration" backup_source attempt project backend answer
  credential_migration_consent
  project=$(env_get "$ENV_FILE" COMPOSE_PROJECT_NAME)
  project=${project:-$(basename "$SCRIPT_DIR")}
  backend=$(docker ps -aq --filter "label=com.docker.compose.project=$project" --filter 'label=com.docker.compose.service=backend') || die '无法核实原后端归属'
  [[ $backend != *$'\n'* ]] || die '原后端归属不唯一，账号未修改'
  printf '正在准备原密钥和加密快照，秘密内容不会显示在终端。\n'
  if [[ ! -s $directory/retiring.json && -n $backend ]]; then
    if docker exec "$backend" python -c 'import ast, json, os
from pathlib import Path
p = os.environ.get("BS_SECRET_KEYS_FILE")
if p:
    data = json.loads(Path(p).read_text())
else:
    tree = ast.parse(Path("/app/bisheng/core/config/settings.py").read_text())
    found = [ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "secret_key" for t in n.targets)]
    if len(found) != 1 or not isinstance(found[0], str): raise ValueError("explicit key backup required")
    data = {"version": 1, "keys": found}
print(json.dumps(data))' > "$directory/retiring.tmp" 2>/dev/null; then
      mv "$directory/retiring.tmp" "$directory/retiring.json"
    else rm -f "$directory/retiring.tmp"; fi
  fi
  if [[ ! -s $directory/retiring.json ]]; then
    [[ -t 0 ]] || die '无法读取有效旧密钥，请通过原命令提供配套备份；不会生成替代旧身份'
    IFS= read -r -p '请输入旧密钥备份JSON文件完整路径：' backup_source || die '密钥恢复已取消'
    [[ $backup_source = /* && -r $backup_source ]] || die '旧密钥备份不可读'
    cp "$backup_source" "$directory/retiring.json"
  fi
  chmod 600 "$directory/retiring.json"
  credential_tool validate-keyring --key-file "$directory/retiring.json" || die '旧密钥无效，请保留现场和配套备份'
  if [[ ! -f $credential_store/keys/primary.json ]]; then
    credential_tool keygen --out "$credential_store/keys/primary.json" || die '主密钥准备失败'
  fi
  KEY_FILE="$credential_store/keys/transition.json"
  if [[ ! -f $KEY_FILE ]]; then
    credential_tool join-keyrings --primary-file "$credential_store/keys/primary.json" --retiring-file "$directory/retiring.json" --out "$KEY_FILE" || die '过渡密钥准备失败'
  fi
  if [[ ! -f $directory/.artifact-context.json ]]; then
    credential_tool artifact context --deployment-id "$(credential_deployment_identity)" --out "$directory/.artifact-context.json" >/dev/null || die '无法准备密文捕获上下文'
  fi
  credential_tool artifact legacy-seal --session-dir "$directory" --key-file "$KEY_FILE" >/dev/null || die '旧捕获文件加密转换失败，账号未修改'
  if [[ ! -s $directory/source.yaml ]]; then
    if [[ -z $backend ]] || ! docker exec "$backend" python -c 'from pathlib import Path; import sys; sys.stdout.buffer.write(Path("/app/bisheng/config.yaml").read_bytes())' 2>/dev/null \
      | credential_tool artifact seal-stream --key-file "$KEY_FILE" --out "$directory/source.yaml" >/dev/null; then
      rm -f "$directory/source.yaml"  # Discard only this failed encrypted capture.
      [[ -t 0 ]] || die '无法读取现用配置，请在交互终端提供配套备份'
      backup_source="$volume/bisheng/config/config.yaml"
      IFS= read -r -p "请输入现用配置完整路径（回车使用 $backup_source）：" answer || die '恢复已取消'
      backup_source=${answer:-$backup_source}
      [[ $backup_source = /* && -r $backup_source ]] || die '现用配置不可读'
      credential_tool artifact seal-stream --key-file "$KEY_FILE" --out "$directory/source.yaml" < "$backup_source" >/dev/null || die '配置加密导入失败'
    fi
  fi
  if [[ ! -s $directory/runtime-env.json ]]; then
    if [[ -z $backend ]] || ! docker inspect --format '{{json .Config.Env}}' "$backend" 2>/dev/null \
      | credential_tool artifact seal-stream --key-file "$KEY_FILE" --out "$directory/runtime-env.json" >/dev/null; then
      rm -f "$directory/runtime-env.json"
      [[ -t 0 ]] || die '无法读取旧环境来源，请在交互终端提供备份'
      IFS= read -r -p '请输入原后端环境快照JSON备份完整路径：' backup_source || die '恢复已取消'
      [[ $backup_source = /* && -r $backup_source ]] || die '环境快照不可读'
      credential_tool artifact seal-stream --key-file "$KEY_FILE" --out "$directory/runtime-env.json" < "$backup_source" >/dev/null || die '环境快照加密导入失败'
    fi
  fi
  attempt=$(mktemp -d "$credential_store/revisions/adopt.XXXXXX")
  BUNDLE="$attempt/bundle"
  credential_tool prepare --mode adopt-key --config "$directory/source.yaml" --runtime-env-file "$directory/runtime-env.json" \
    --env-file "$ENV_FILE" --deployment-root "$volume" --key-file "$KEY_FILE" --out-dir "$BUNDLE" || die '配置迁移预检失败，保留加密快照后重试'
  credential_adopt=true
  credential_save_prepared_pair
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
    compose run --rm --no-deps -v "$backup:/maintenance" --entrypoint sh backend \
      -c 'python scripts/rewrap_credentials.py --all-tenants --resume /maintenance/run --apply' \
      || die '密文迁移尚未完成，业务保持停止；修复原因后重新执行原命令会自动续跑原计划'
  else
    compose run --rm --no-deps -v "$backup:/maintenance" --entrypoint sh backend \
      -c 'python scripts/rewrap_credentials.py --all-tenants --backup-dir /maintenance/run' \
      || die '数据库密文预检失败，业务保持停止；修复后重新执行原命令'
    compose run --rm --no-deps -v "$backup:/maintenance" --entrypoint sh backend \
      -c 'python scripts/rewrap_credentials.py --all-tenants --backup-dir /maintenance/run --apply' \
      || die '数据库迁移尚未完成；原备份已保留，重新执行原命令将自动识别并续跑'
  fi
  compose run --rm --no-deps -v "$backup:/maintenance" --entrypoint sh backend \
    -c 'python scripts/rewrap_credentials.py --all-tenants --verify-primary-only' \
    || die '新密钥独立复检失败，业务保持停止，请保留过渡密钥后重试'
  printf 'complete\n' > "$directory/complete.tmp"
  mv "$directory/complete.tmp" "$directory/complete"
}
