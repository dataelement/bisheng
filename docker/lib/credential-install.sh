#!/usr/bin/env bash
# Internal installer implementation. Operators keep using install.sh/deploy.sh.

credential_registry_login() {
  [[ ${credential_registry_authenticated:-false} != true ]] || return 0
  local registry_user registry_password
  registry_user=$(env_get "$ENV_FILE" CR_REGISTRY_USERNAME)
  registry_password=$(env_get "$ENV_FILE" CR_REGISTRY_PASSWORD)
  printf '%s\n' "${registry_password:-dataelem}" | docker login cr.dataelem.com --username "${registry_user:-docker}" --password-stdin \
    || die 'CR镜像源登录失败，请检查网络与镜像源配置'
  credential_registry_authenticated=true
}

credential_pull_image() {
  local reference=$1
  if [[ ${credential_image_pull_policy:-always} != always ]] && docker image inspect "$reference" >/dev/null 2>&1; then return 0; fi
  [[ ${credential_image_pull_policy:-always} != never ]] || return 1
  case "$reference" in cr.dataelem.com/*) credential_registry_login ;; esac
  docker pull "$reference"
}

credential_tool() {
  local extra=()
  if [[ ${1:-} = validate-inputs && -n ${KEY_FILE:-} ]]; then extra=(--key-file "$KEY_FILE"); fi
  bash "$SCRIPT_DIR/credentials.sh" --image "$image" "$@" ${extra[@]+"${extra[@]}"}
}

credential_deployment_identity() {
  if [[ -n ${credential_deployment_id:-} ]]; then printf '%s' "$credential_deployment_id"; return; fi
  if [[ -f ${credential_store:-}/deployment.id ]]; then cat "$credential_store/deployment.id"; return; fi
  if [[ -f ${BUNDLE:-}/manifest.json ]]; then
    sed -n 's/.*"deployment_id": "\([0-9a-f]\{32\}\)".*/\1/p' "$BUNDLE/manifest.json"
    return
  fi
  die '缺少部署身份，尚未修改账号'
}

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
  trap 'printf "此次部署脚本执行失败：收到中断信号。\n" >&2; exit 130' INT
  trap 'printf "此次部署脚本执行失败：收到终止信号。\n" >&2; exit 143' TERM HUP
}

credential_has_old_data() {
  local folder contents project existing
  for folder in "$volume/mysql/data" "$volume/data/redis" "$volume/data/es" "$volume/data/milvus-etcd" "$volume/data/milvus-minio" "$volume/data/milvus"; do
    if [[ -d $folder ]]; then
      # A native daemon may own its 0700 data directory. Treat inaccessible
      # state as existing, never as a fresh installation under another UID.
      [[ -r $folder && -x $folder ]] || return 0
      contents=$(find "$folder" -mindepth 1 -maxdepth 1 -print -quit) || die '无法读取中间件数据目录，不能判断新装；请恢复访问权限后重试原命令'
      [[ -z $contents ]] || return 0
    fi
  done
  project=$(env_get "$ENV_FILE" COMPOSE_PROJECT_NAME)
  project=${project:-$(basename "$SCRIPT_DIR")}
  existing=$(docker ps -aq --filter "label=com.docker.compose.project=$project") || die '无法确认当前部署资源，未修改账号'
  [[ -z $existing ]] || return 0
  return 1
}

credential_prompt_secret() {
  local component="$1" label="$2" file="$3" entry="$4"
  local credential_value credential_confirmation status deployment minimum
  minimum=6
  [[ $component = minio ]] && minimum=8
  deployment=$(credential_deployment_identity)
  while true; do
    if [[ ! -f $file ]]; then
      [[ -t 0 ]] || die "当前不是交互终端，缺少${label}密码；请在交互终端重新执行原安装命令，或在.env配置BISHENG_CREDENTIAL_INPUTS_FILE供自动化使用"
      credential_read_secret "请输入${label}密码（至少${minimum}位，输入隐藏）：" credential_value || die '输入已取消，请重新执行原安装命令继续'
      credential_read_secret '请再次输入确认：' credential_confirmation || die '输入已取消，请重新执行原安装命令继续'
      if [[ $credential_value != "$credential_confirmation" ]]; then
        printf '两次输入不一致，请重新输入。\n'
        unset credential_value credential_confirmation
        continue
      fi
      if printf '%s' "$credential_value" | credential_tool artifact seal-input --component "$component" \
          --key-file "$KEY_FILE" --deployment-id "$deployment" --out "$file" >/dev/null; then
        status=0
      else status=$?; fi
      unset credential_value credential_confirmation
      if [[ $status != 0 ]]; then
        [[ $status = 4 ]] || die '加密输入准备失败，账号未修改；保留现有密钥后重试'
        printf '%s密码至少%s位，且不能使用占位符；请重新输入。\n' "$label" "$minimum"
        continue
      fi
    fi
    printf 'version: 1\n%s:\n  %s: %s\n' "$component" "$entry" "$(basename "$file")" > "$credential_inputs/validate.yaml"
    if credential_tool validate-inputs --inputs "$credential_inputs/validate.yaml" --key-file "$KEY_FILE" --deployment-id "$deployment"; then return; fi
    [[ -t 0 ]] || die "${label}密码文件未通过检查，请修正输入文件后重新执行原命令"
    printf '%s密码至少%s位，且不能使用占位符；请重新输入。\n' "$label" "$minimum"
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
  local saved_bundle deployment parent
  credential_store=$(credential_store_path)
  [[ ! -L $credential_store ]] || die '凭据目录不能是符号链接，安装停止'
  parent=$(dirname "$credential_store")
  if [[ -L $parent || ( -e $parent && ! -d $parent ) ]]; then
    die '凭据父目录不可用，安装停止'
  fi
  if [[ ! -d $parent ]]; then
    mkdir -p "$parent" || die '无法创建凭据父目录，安装停止'
  fi
  mkdir -p "$credential_store/keys" "$credential_store/revisions" || die '无法创建固定凭据目录，安装停止'
  chmod 700 "$credential_store" "$credential_store/keys" "$credential_store/revisions" || die '无法设置固定凭据目录权限，安装停止'
  credential_lock_acquire
  if [[ ! -f "$credential_store/deployment.id" ]]; then
    saved_bundle=${BUNDLE:-$(env_get "$ENV_FILE" BISHENG_CREDENTIALS_DIR)}
    deployment=''
    if [[ -f $saved_bundle/manifest.json ]]; then
      deployment=$(sed -n 's/.*"deployment_id": "\([0-9a-f]\{32\}\)".*/\1/p' "$saved_bundle/manifest.json")
    fi
    deployment=${deployment:-$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')}
    printf '%s\n' "$deployment" > "$credential_store/deployment.id"
    chmod 600 "$credential_store/deployment.id"
  fi
  credential_deployment_id=$(cat "$credential_store/deployment.id")
  [[ $credential_deployment_id =~ ^[0-9a-f]{32}$ ]] || die '部署身份标记无效，未修改账号'
}

credential_import_existing_bundle() {
  local project ids id working candidate found='' original_bundle original_key original_volume value setting
  project=$(env_get "$ENV_FILE" COMPOSE_PROJECT_NAME)
  project=${project:-$(basename "$SCRIPT_DIR")}
  ids=$(docker ps -aq --filter "label=com.docker.compose.project=$project" --filter 'label=com.docker.compose.service=backend') || die '无法读取原部署归属'
  while IFS= read -r id; do
    [[ -n $id ]] || continue
    working=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' "$id") || return 1
    candidate="$working/.env"
    [[ $working = /* && -f $candidate ]] || continue
    if [[ -n $found && $found != "$candidate" ]]; then
      die '检测到同项目的多个部署配置目录；请在原命令中明确提供配置包和密钥，不能自动猜测'
    fi
    found=$candidate
  done <<< "$ids"
  [[ -n $found && $found != "$ENV_FILE" ]] || return 1
  [[ $(env_get "$found" COMPOSE_PROJECT_NAME) = "$project" ]] || return 1
  original_bundle=$(env_get "$found" BISHENG_CREDENTIALS_DIR)
  original_key=$(env_get "$found" BISHENG_SECRET_KEYS_FILE)
  [[ $original_bundle = /* && -f $original_bundle/manifest.json && $original_key = /* && -f $original_key ]] || return 1
  BUNDLE=$original_bundle
  if [[ ${credential_key_explicit:-false} != true ]]; then KEY_FILE=$original_key; fi
  original_volume=$(env_get "$found" DOCKER_VOLUME_DIRECTORY)
  case "$original_volume" in /*) ;; *) original_volume="$(dirname "$found")/${original_volume:-.}" ;; esac
  [[ -d $original_volume ]] || die '原数据目录不可读，未准备新数据目录'
  volume=$(cd "$original_volume" && pwd)
  env_set "$ENV_FILE" DOCKER_VOLUME_DIRECTORY "$volume"
  for setting in BISHENG_NETWORK_NAME BISHENG_NGINX_CONF_DIR; do
    value=$(env_get "$found" "$setting")
    if [[ $setting = BISHENG_NGINX_CONF_DIR && -n $value && $value != /* ]]; then value="$(dirname "$found")/$value"; fi
    [[ -z $value ]] || env_set "$ENV_FILE" "$setting" "$value"
  done
  printf '已识别原部署配置，将只读导入现用凭据并复用原数据目录；旧项目代码保留。\n'
}

# deployment-policy.json binds an immutable baseline directory. Abandoning a
# migration/session without retiring the prepared pair leaves a reusable
# pointer whose baseline path no longer exists; refuse that reuse early.
credential_policy_baseline_path() {
  local bundle=$1
  [[ -f $bundle/deployment-policy.json ]] || return 0
  sed -n 's/.*"baseline": "\([^"]*\)".*/\1/p' "$bundle/deployment-policy.json" | head -n1
}

credential_retire_unusable_policy_bundle() {
  local baseline stamp dest env_bundle
  [[ -n ${BUNDLE:-} && -d ${BUNDLE:-} && -f $BUNDLE/deployment-policy.json ]] || return 0
  baseline=$(credential_policy_baseline_path "$BUNDLE")
  [[ -n $baseline ]] || return 0
  [[ -d $baseline ]] && return 0
  stamp=$(date +%Y%m%d-%H%M%S)
  dest="$credential_store/abandoned/abandoned-${stamp}-missing-baseline"
  mkdir -p "$dest"
  chmod 700 "$dest"
  printf '%s\n' "$BUNDLE" > "$dest/bundle.path"
  printf '%s\n' "$baseline" > "$dest/missing-baseline.path"
  if [[ -f $credential_store/prepared.env ]]; then
    mv "$credential_store/prepared.env" "$dest/prepared.env"
  fi
  case "$BUNDLE/" in
    "$credential_store/revisions/"*)
      mv "$BUNDLE" "$dest/bundle"
      ;;
  esac
  env_bundle=$(env_get "$ENV_FILE" BISHENG_CREDENTIALS_DIR)
  if [[ -z $env_bundle || $env_bundle = "$BUNDLE" || $env_bundle = "$(cat "$dest/bundle.path")" ]]; then
    env_set "$ENV_FILE" BISHENG_CREDENTIALS_DIR ''
    env_set "$ENV_FILE" BISHENG_SECRET_KEYS_FILE ''
    env_set "$ENV_FILE" BISHENG_CREDENTIAL_REVISION ''
  fi
  printf '现用配置包的部署策略基线目录已缺失（%s）；已归档半成品指针到 %s，将重新准备配置，不改动中间件数据。\n' \
    "$baseline" "$dest"
  BUNDLE=''
  if [[ ${credential_key_explicit:-false} != true ]]; then KEY_FILE=''; fi
}

credential_setup() {
  local stored_bundle stored_key attempt actual_revision recovered
  credential_adopt=false
  credential_preserve_native=false
  [[ ${credential_lock_owned:-false} = true ]] || credential_initialize_store
  stored_bundle=''; stored_key=''
  if [[ -f "$credential_store/prepared.env" ]]; then
    stored_bundle=$(env_get "$credential_store/prepared.env" BISHENG_CREDENTIALS_DIR)
    stored_key=$(env_get "$credential_store/prepared.env" BISHENG_SECRET_KEYS_FILE)
  fi
  if [[ -z $BUNDLE && -n $stored_bundle ]]; then
    BUNDLE=$stored_bundle
    # Preparation commits a pair. A stale .env key must not split that pair
    # after interruption before activation; explicit CLI recovery still wins.
    if [[ ${credential_key_explicit:-false} != true ]]; then KEY_FILE=$stored_key; fi
  fi
  KEY_FILE=${KEY_FILE:-$stored_key}
  credential_retire_unusable_policy_bundle
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
      credential_retire_unusable_policy_bundle
      [[ -n $BUNDLE ]] || die '提供的配置包部署策略基线已缺失；请提供完整配套备份后重新执行原命令'
    fi
    if [[ -n $BUNDLE ]]; then
      if [[ $KEY_FILE != /* || ! -f $KEY_FILE ]]; then
        [[ -t 0 ]] || die '现用密钥文件缺失，请在交互终端重新执行原命令，按引导提供备份；不会生成替代密钥'
        IFS= read -r -p '现用密钥缺失，请输入匹配的备份密钥文件完整路径：' recovered || die '恢复输入已取消'
        [[ $recovered = /* && -f $recovered ]] || die '备份密钥路径不可读，现有数据保持不变'
        KEY_FILE=$recovered
      fi
      printf '检测到已有部署配置，将复用现有密码和密钥。\n'
    fi
  fi
  if [[ -z $BUNDLE ]]; then
    # Never initialize fresh credentials over existing middleware state.
    # A new delivery directory starts with an empty data path. Discover the
    # existing Compose deployment before treating that empty path as fresh.
    if credential_import_existing_bundle; then
      credential_retire_unusable_policy_bundle
      [[ -n $BUNDLE ]] || die '识别到的原部署配置策略基线已缺失；请提供完整配套备份，或清理原配置指针后重新执行原命令'
      :
    elif credential_has_old_data; then
      credential_prepare_legacy
    else
      credential_config="$volume/bisheng/config/config.yaml"
      [[ -f $credential_config ]] || die '未找到基础业务配置，请检查DOCKER_VOLUME_DIRECTORY'
      printf '首次部署，将引导设置本公司的密码，其余安全配置自动完成。\n'
      credential_fresh_install=true
      KEY_FILE=${KEY_FILE:-$credential_store/keys/keys.json}
      if [[ ! -e $KEY_FILE ]]; then
        credential_tool keygen --out "$KEY_FILE" || die '部署密钥准备失败，尚未启动服务'
      fi
      credential_collect_inputs
      attempt=$(mktemp -d "$credential_store/revisions/prepare.XXXXXX")
      BUNDLE="$attempt/bundle"
      credential_tool prepare --mode fresh --config "$credential_config" --inputs "$credential_manifest" \
        --env-file "$ENV_FILE" --deployment-root "$volume" --key-file "$KEY_FILE" --out-dir "$BUNDLE" \
        || die '配置准备失败，现有密码输入和密钥已保留，重新执行原命令即可继续'
    fi
  fi
  if command -v credential_sealed_migration_prepare >/dev/null 2>&1; then
    credential_sealed_migration_prepare
  fi
  if command -v credential_runtime_seed_bundle >/dev/null 2>&1; then
    credential_runtime_seed_bundle
  fi
  if command -v credential_sealed_migration_verify >/dev/null 2>&1; then
    credential_sealed_migration_verify
  fi
  if grep -q '"mode": "adopt-key"' "$BUNDLE/manifest.json"; then credential_adopt=true; fi
  if [[ -f "$BUNDLE/deployment-policy.json" ]]; then
    local policy_mode
    # Missing baselines are retired before reuse; remaining failures are signature/hash mismatches.
    policy_mode=$(credential_tool rotation validate-policy --policy-root "$credential_store" --bundle "$BUNDLE" --key-file "$KEY_FILE" --env-file "$ENV_FILE") \
      || die '部署策略或基线不匹配，请恢复完整配套备份'
    [[ $policy_mode != preserve-native ]] || credential_preserve_native=true
  elif [[ $credential_adopt = true ]]; then
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
  credential_save_prepared_pair
}

credential_save_prepared_pair() {
  : > "$credential_store/prepared.env.tmp"
  env_set "$credential_store/prepared.env.tmp" BISHENG_CREDENTIALS_DIR "$BUNDLE"
  env_set "$credential_store/prepared.env.tmp" BISHENG_SECRET_KEYS_FILE "$KEY_FILE"
  mv "$credential_store/prepared.env.tmp" "$credential_store/prepared.env"
}
