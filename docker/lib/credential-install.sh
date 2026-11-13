#!/usr/bin/env bash
# Internal installer implementation. Operators keep using install.sh/deploy.sh.

credential_tool() { bash "$SCRIPT_DIR/credentials.sh" --image "$image" "$@"; }

credential_revision() {
  sed -n 's/.*"revision": "\([0-9a-f]\{32\}\)".*/\1/p' "$1/manifest.json"
}

credential_lock_release() {
  if [[ -n ${credential_tty_state:-} ]]; then
    stty "$credential_tty_state"
    unset credential_tty_state
    printf '\n'
  fi
  if [[ ${credential_lock_owned:-false} = true ]]; then
    rm -f -- "$credential_store/.lock/pid"
    rmdir "$credential_store/.lock"
    credential_lock_owned=false
  fi
}

credential_read_secret() {
  local status=0
  credential_tty_state=$(stty -g) || return 1
  stty -echo || return 1
  # Disable echo before showing the prompt, including for fast pasted input.
  printf '%s' "$1" >&2
  IFS= read -r "$2" || status=$?
  stty "$credential_tty_state"
  unset credential_tty_state
  printf '\n' >&2
  return "$status"
}

credential_lock_acquire() {
  local pid
  if ! mkdir "$credential_store/.lock" 2>/dev/null; then
    pid=$(cat "$credential_store/.lock/pid" 2>/dev/null || true)
    if [[ $pid =~ ^[0-9]+$ ]] && ! kill -0 "$pid" 2>/dev/null; then
      rm -f -- "$credential_store/.lock/pid"
      rmdir "$credential_store/.lock" || die '凭据准备锁异常，请检查部署进程'
      mkdir "$credential_store/.lock" || die '另一个部署进程正在准备配置，请稍后重新执行原命令'
    else
      die '另一个部署进程正在准备配置，请稍后重新执行原命令'
    fi
  fi
  credential_lock_owned=true
  printf '%s\n' "$$" > "$credential_store/.lock/pid"
  trap credential_lock_release EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM HUP
}

credential_has_old_data() {
  local folder name contents
  for folder in "$volume/mysql/data" "$volume/data/redis" "$volume/data/es" "$volume/data/milvus-etcd" "$volume/data/milvus-minio" "$volume/data/milvus"; do
    if [[ -d $folder ]]; then
      contents=$(find "$folder" -mindepth 1 -maxdepth 1 -print -quit) || die '无法读取中间件数据目录，不能判断新装；请恢复访问权限后重试原命令'
      [[ -z $contents ]] || return 0
    fi
  done
  for name in bisheng-mysql bisheng-redis bisheng-es bisheng-milvus-etcd bisheng-milvus-minio bisheng-milvus-standalone bisheng-openfga bisheng-backend; do
    docker container inspect "$name" >/dev/null 2>&1 && return 0
  done
  return 1
}

credential_prompt_secret() {
  local component="$1" label="$2" file="$3" entry="$4"
  local credential_value credential_confirmation
  while true; do
    if [[ ! -f $file ]]; then
      [[ -t 0 ]] || die "当前不是交互终端，缺少${label}密码；请在交互终端重新执行原安装命令，或在.env配置BISHENG_CREDENTIAL_INPUTS_FILE供自动化使用"
      credential_read_secret "请输入${label}密码（输入隐藏）：" credential_value || die '输入已取消，请重新执行原安装命令继续'
      credential_read_secret '请再次输入确认：' credential_confirmation || die '输入已取消，请重新执行原安装命令继续'
      if [[ $credential_value != "$credential_confirmation" ]]; then
        printf '两次输入不一致，请重新输入。\n'
        unset credential_value credential_confirmation
        continue
      fi
      printf '%s' "$credential_value" > "$file"
      chmod 600 "$file"
      unset credential_value credential_confirmation
    fi
    printf 'version: 1\n%s:\n  %s: %s\n' "$component" "$entry" "$(basename "$file")" > "$credential_inputs/validate.yaml"
    if credential_tool validate-inputs --inputs "$credential_inputs/validate.yaml"; then return; fi
    [[ -t 0 ]] || die "${label}密码文件未通过检查，请修正输入文件后重新执行原命令"
    printf '%s密码不满足组件要求，请重新输入。\n' "$label"
    rm -f -- "$file"  # Only this attempt's private input, never a live bundle.
  done
}

credential_collect_inputs() {
  local supplied component label entry file
  supplied=$(env_get "$ENV_FILE" BISHENG_CREDENTIAL_INPUTS_FILE)
  if [[ -n $supplied ]]; then
    [[ $supplied = /* && -f $supplied ]] || die '自动化密码输入文件必须是可读的绝对路径'
    credential_tool validate-inputs --inputs "$supplied" || die '客户密码输入检查失败，尚未启动服务'
    credential_manifest="$supplied"
    return
  fi
  credential_inputs="$credential_store/inputs"
  mkdir -p "$credential_inputs"
  chmod 700 "$credential_inputs"
  credential_tool requirements --config "$credential_config" --env-file "$ENV_FILE" > "$credential_inputs/components" || die '基础配置读取失败，尚未启动服务'
  printf 'version: 1\n' > "$credential_inputs/inputs.yaml"
  # Keep stdin on the terminal: password prompts must not read the component list.
  while IFS= read -r component <&3; do
    entry=password_file
    case "$component" in
      mysql) label=MySQL ;;
      redis) label=Redis ;;
      minio) label=MinIO; entry=secret_key_file ;;
      elasticsearch) label=Elasticsearch ;;
      milvus) label=Milvus ;;
      telemetry_elasticsearch) label='统计Elasticsearch' ;;
      *) die '基础配置返回了不支持的组件，尚未启动服务' ;;
    esac
    file="$credential_inputs/$component.password"
    credential_prompt_secret "$component" "$label" "$file" "$entry"
    printf '%s:\n  %s: %s\n' "$component" "$entry" "$(basename "$file")" >> "$credential_inputs/inputs.yaml"
    if [[ $component = minio ]]; then
      # Account identifiers are not passwords; retain the existing account when supplied.
      local account
      account=$(env_get "$ENV_FILE" MINIO_ROOT_USER)
      account=${account:-minioadmin}
      printf '%s' "$account" > "$credential_inputs/minio.user"
      printf '  access_key_file: minio.user\n' >> "$credential_inputs/inputs.yaml"
    fi
  done 3< "$credential_inputs/components"
  credential_manifest="$credential_inputs/inputs.yaml"
}

credential_initialize_store() {
  credential_store="$SCRIPT_DIR/.generated/credential-security"
  [[ ! -L $credential_store ]] || die '凭据目录不能是符号链接'
  mkdir -p "$credential_store/keys" "$credential_store/revisions"
  chmod 700 "$credential_store" "$credential_store/keys" "$credential_store/revisions"
  credential_lock_acquire
}

credential_setup() {
  local stored_bundle stored_key attempt actual_revision recovered
  credential_adopt=false
  [[ ${credential_lock_owned:-false} = true ]] || credential_initialize_store
  stored_bundle=''; stored_key=''
  if [[ -f "$credential_store/prepared.env" ]]; then
    stored_bundle=$(env_get "$credential_store/prepared.env" BISHENG_CREDENTIALS_DIR)
    stored_key=$(env_get "$credential_store/prepared.env" BISHENG_SECRET_KEYS_FILE)
  fi
  BUNDLE=${BUNDLE:-$stored_bundle}
  KEY_FILE=${KEY_FILE:-$stored_key}
  if [[ -z $BUNDLE && -n $KEY_FILE && ! -f $KEY_FILE ]]; then
    [[ -t 0 ]] || die '已配置的密钥文件缺失，请在交互终端重新执行原命令并提供备份；不会生成替代密钥'
    IFS= read -r -p '请输入现用密钥备份文件的完整路径：' recovered || die '密钥恢复已取消'
    [[ $recovered = /* && -f $recovered ]] || die '备份密钥不可读，数据未改变'
    KEY_FILE=$recovered
  fi
  if [[ -n $BUNDLE ]]; then
    if [[ $BUNDLE != /* || ! -d $BUNDLE ]]; then
      [[ -t 0 ]] || die '现用配置目录缺失，请在交互终端重新执行原命令并提供备份；不会按新装覆盖数据'
      IFS= read -r -p '请输入现用配置包备份目录的完整路径：' recovered || die '配置恢复已取消'
      [[ $recovered = /* && -d $recovered ]] || die '备份配置目录不可读，数据未改变'
      BUNDLE=$recovered
    fi
    if [[ $KEY_FILE != /* || ! -f $KEY_FILE ]]; then
      [[ -t 0 ]] || die '现用密钥文件缺失，请在交互终端重新执行原命令，按引导提供备份；不会生成替代密钥'
      IFS= read -r -p '现用密钥缺失，请输入匹配的备份密钥文件完整路径：' recovered || die '恢复输入已取消'
      [[ $recovered = /* && -f $recovered ]] || die '备份密钥路径不可读，现有数据保持不变'
      KEY_FILE=$recovered
    fi
    printf '检测到已有部署配置，将复用现有密码和密钥。\n'
  else
    # Never initialize fresh credentials over existing middleware state.
    if credential_has_old_data; then
      credential_prepare_legacy
    else
      credential_config="$volume/bisheng/config/config.yaml"
      [[ -f $credential_config ]] || die '未找到基础业务配置，请检查DOCKER_VOLUME_DIRECTORY'
      printf '首次部署，将引导设置本公司的密码，其余安全配置自动完成。\n'
      credential_collect_inputs
      KEY_FILE=${KEY_FILE:-$credential_store/keys/keys.json}
      if [[ ! -e $KEY_FILE ]]; then
        credential_tool keygen --out "$KEY_FILE" || die '部署密钥准备失败，尚未启动服务'
      fi
      attempt=$(mktemp -d "$credential_store/revisions/prepare.XXXXXX")
      BUNDLE="$attempt/bundle"
      credential_tool prepare --mode fresh --config "$credential_config" --inputs "$credential_manifest" \
        --env-file "$ENV_FILE" --deployment-root "$volume" --key-file "$KEY_FILE" --out-dir "$BUNDLE" \
        || die '配置准备失败，现有密码输入和密钥已保留，重新执行原命令即可继续'
    fi
  fi
  if grep -q '"mode": "adopt-key"' "$BUNDLE/manifest.json"; then credential_adopt=true; fi
  if [[ $credential_adopt = true ]]; then
    credential_tool check --bundle "$BUNDLE" --key-file "$KEY_FILE" --env-file "$ENV_FILE" || die '现用配置检查失败，未提交数据库迁移'
  else
    credential_tool check --bundle "$BUNDLE" --key-file "$KEY_FILE" --env-file "$ENV_FILE" --enforce || die '凭据检查失败，未启动服务，请核对现用配置与密钥备份'
  fi
  actual_revision=$(credential_revision "$BUNDLE")
  [[ $actual_revision =~ ^[0-9a-f]{32}$ ]] || die '配置版本读取失败，尚未启动服务'
  [[ -z $REVISION || $REVISION = "$actual_revision" ]] || die '显式指定的配置版本与现用文件不一致'
  REVISION=$actual_revision
  # Recover a prepared-but-not-activated attempt after an interruption. No keys or
  # passwords enter the marker. Each replacement is atomic in the same directory.
  : > "$credential_store/prepared.env.tmp"
  env_set "$credential_store/prepared.env.tmp" BISHENG_CREDENTIALS_DIR "$BUNDLE"
  env_set "$credential_store/prepared.env.tmp" BISHENG_SECRET_KEYS_FILE "$KEY_FILE"
  mv "$credential_store/prepared.env.tmp" "$credential_store/prepared.env"
}
