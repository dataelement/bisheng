#!/usr/bin/env bash
# Internal orchestration. Passwords stay in private files, never Docker argv/env.
credential_rotation_tool() {
  local rotation_network=none
  case "$1" in capture|preflight|step|verify) rotation_network=${credential_rotation_network:-none} ;; esac
  bash "$SCRIPT_DIR/credentials.sh" --image "$image" --network "$rotation_network" rotation "$@" --policy-root "$credential_store" --key-file "$KEY_FILE"
}
credential_rotation_state() {
  credential_rotation_tool "$@" --session-dir "$credential_rotation_session" --key-file "$KEY_FILE"
}
credential_rotation_fail() {
  if [[ ${credential_rotation_paused:-false} = true ]]; then
    local name
    while IFS= read -r name; do
      [[ -z $name ]] || docker stop "$name" >/dev/null 2>&1 || printf '暂停应用失败，请检查容器状态。\n' >&2
    done < "$credential_rotation_session/consumers"
    credential_rotation_state mark --phase NEEDS_ATTENTION >/dev/null 2>&1 || printf '保存异常阶段失败，请保留整个凭据目录。\n' >&2
  fi
  die "$1；保留凭据目录，修复后重新执行原命令继续，禁止删除数据目录"
}
credential_rotation_require_capability() {
  [[ ${credential_rotation_capable:-false} != true ]] || return 0
  local replacement
  while true; do
    if credential_rotation_tool capabilities > "$credential_store/rotation-capability" 2>/dev/null && [[ $(cat "$credential_store/rotation-capability") = rotation-v1 ]]; then
      credential_rotation_capable=true
      return
    fi
    [[ -t 0 ]] || die '本次选中改密需要本版本配套后端镜像，当前镜像不支持；账号未改变'
    IFS= read -r -p '当前镜像不支持逐项改密，请输入本版本配套后端镜像地址：' replacement || die '配套镜像选择已取消，账号未改变'
    [[ -n $replacement ]] || die '镜像地址为空，账号未改变'
    docker pull "$replacement" || die '配套镜像拉取失败，账号未改变'
    image=$replacement
    env_set "$ENV_FILE" BISHENG_BACKEND_IMAGE "$image"
  done
}
credential_rotation_select() {
  credential_rotation_manifest=''
  credential_rotation_session=''
  if [[ -f "$credential_store/rotation.active" ]]; then
    IFS= read -r credential_rotation_session < "$credential_store/rotation.active"
    [[ $credential_rotation_session = "$credential_store/rotations/"* && -f "$credential_rotation_session/plan.json" ]] || die '改密恢复标记异常，请恢复配套计划备份'
    credential_rotation_require_capability
    printf '发现未完成改密，将读取原计划和已保存密码，不重复输入。\n'
    return
  fi
  # Fresh installation already collected all five passwords; no second menu.
  if ! credential_has_old_data; then return; fi
  local supplied answer component label entry
  supplied=$(env_get "$ENV_FILE" BISHENG_CREDENTIAL_ROTATION_INPUTS_FILE)
  if [[ -n $supplied ]]; then
    [[ $supplied = /* && -f $supplied ]] || die '自动化改密输入必须是可读绝对路径'
  elif [[ ! -t 0 ]]; then
    return
  fi
  if [[ -n $supplied ]]; then
    credential_rotation_require_capability
    credential_tool validate-inputs --inputs "$supplied" || die '自动化改密输入检查失败'
    local request_id
    request_id=$(credential_rotation_tool request-id --inputs "$supplied") || die '自动化改密请求无法识别'
    if [[ -f "$credential_store/rotation.completed" && $(cat "$credential_store/rotation.completed") = "$request_id" ]]; then
      printf '这份自动化改密请求已经完成，本次复用现有密码。\n'
      return
    fi
    [[ ${BISHENG_ALLOW_CREDENTIAL_ROTATION:-} = yes ]] || die '自动化改密须显式设置 BISHENG_ALLOW_CREDENTIAL_ROTATION=yes'
    credential_rotation_manifest=$supplied
    return
  fi
  credential_inputs=$(mktemp -d "$credential_store/rotation-inputs.XXXXXX")
  chmod 700 "$credential_inputs"
  printf 'version: 1\n' > "$credential_inputs/inputs.yaml"
  credential_tool requirements --config "$BUNDLE/config.yaml" --env-file "$ENV_FILE" > "$credential_inputs/components" || die '无法读取现用组件列表'
  printf '逐项选择是否修改密码；直接回车表示保留，不会自动改动其他组件。\n'
  while IFS= read -r component <&3; do
    if [[ $component = elasticsearch && ${credential_es_already_selected:-false} = true ]]; then
      printf 'Elasticsearch已在旧版升级步骤中完成认证选择，本次不重复询问。\n'
      continue
    fi
    entry=password_file
    case "$component" in
      mysql) label=MySQL ;; redis) label=Redis ;; minio) label=MinIO; entry=secret_key_file ;;
      elasticsearch) label=Elasticsearch ;; milvus) label=Milvus ;; telemetry_elasticsearch) label='统计Elasticsearch' ;;
      *) die '不支持的改密组件' ;;
    esac
    while true; do
      IFS= read -r -p "是否修改${label}密码？[y/N]：" answer || die '选择已取消，尚未修改密码'
      case "$answer" in y|Y|yes) break ;; ''|n|N|no) break ;; *) printf '请输入y或n，或直接回车保留。\n' ;; esac
    done
    case "$answer" in y|Y|yes)
      credential_rotation_require_capability
      credential_prompt_secret "$component" "$label" "$credential_inputs/$component.password" "$entry"
      printf '%s:\n  %s: %s.password\n' "$component" "$entry" "$component" >> "$credential_inputs/inputs.yaml"
      credential_rotation_manifest="$credential_inputs/inputs.yaml"
      ;; esac
  done 3< "$credential_inputs/components"
  [[ -n $credential_rotation_manifest ]] || printf '已选择全部保留，将继续原部署流程。\n'
}

credential_rotation_socket() {
  local cnf=$1 log=$2 container=$3
  if [[ ! -f $(dirname "$cnf")/manifest.json ]]; then printf UNKNOWN; return; fi
  # Keep every observation immutable; --out deliberately refuses replacement.
  log="$log.$(od -An -N8 -tx1 /dev/urandom | tr -d ' \n').sealed"
  if credential_tool artifact native-stream --bundle "$(dirname "$cnf")" --name mysql-client.cnf --key-file "$KEY_FILE" \
      | docker exec -i "$container" mysql --defaults-extra-file=/dev/stdin --protocol=socket --execute='SELECT CURRENT_USER();' 2>&1 \
      | credential_tool artifact seal-stream --key-file "$KEY_FILE" --out "$log" >/dev/null; then
    printf OK
  elif credential_tool artifact open-stream --file "$log" --key-file "$KEY_FILE" | LC_ALL=C grep -q 'ERROR 1045 (28000)'; then printf DENIED
  else printf UNKNOWN; fi
}
credential_rotation_capture() {
  local folder=$1 project working files file service container source target old_socket=UNKNOWN
  mkdir -p "$folder"
  chmod 700 "$folder"
  credential_tool artifact context --out "$folder/.artifact-context.json" >/dev/null || die '无法准备加密捕获上下文'
  container=$(compose ps --all -q backend)
  [[ -n $container ]] || die '未找到当前项目的后端容器，无法确认现用部署来源'
  project=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "$container")
  working=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' "$container")
  files=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project.config_files"}}' "$container")
  [[ $project =~ ^[a-zA-Z0-9_-]+$ && $working = /* && -d $working && -n $files ]] || die '原部署来源不完整，尚未修改账号'
  local original=("${COMPOSE[@]}" --project-directory "$working" -p "$project")
  [[ ! -f $working/.env ]] || original+=(--env-file "$working/.env")
  local old_ifs=$IFS
  IFS=',' read -r -a original_files <<< "$files"
  IFS=$old_ifs
  for file in "${original_files[@]}"; do
    [[ $file = /* && -f $file ]] || die '原Compose配置文件缺失，尚未修改账号'
    original+=(-f "$file")
  done
  compose config 2>/dev/null | credential_tool artifact seal-stream --key-file "$KEY_FILE" --out "$folder/application.yaml" >/dev/null || die '应用目标配置无法校验，账号未改变'
  "${original[@]}" config 2>/dev/null | credential_tool artifact seal-stream --key-file "$KEY_FILE" --out "$folder/compose.yaml" >/dev/null || die '无法读取原Compose配置，账号未改变'
  local ids=()
  while IFS= read -r container; do [[ -z $container ]] || ids+=("$container"); done < <(docker ps -aq --filter "label=com.docker.compose.project=$project")
  [[ ${#ids[@]} -gt 0 ]] || die '未找到原部署容器'
  docker inspect "${ids[@]}" 2>/dev/null | credential_tool artifact seal-stream --key-file "$KEY_FILE" --out "$folder/containers.json" >/dev/null || die '无法保存原容器配置'
  credential_rotation_network=$(env_get "$ENV_FILE" BISHENG_NETWORK_NAME)
  credential_rotation_network=${credential_rotation_network:-bisheng-network}
  local requested
  requested=$(credential_rotation_tool request-components --inputs "$credential_rotation_manifest") || die '无法读取选中组件'
  for service in redis milvus minio mysql; do
    case "$service" in
      redis|mysql) [[ $'\n'"$requested"$'\n' = *$'\n'"$service"$'\n'* ]] || continue ;;
      minio) [[ $'\n'"$requested"$'\n' = *$'\nminio\n'* ]] || continue ;;
      milvus) [[ $'\n'"$requested"$'\n' = *$'\nminio\n'* || $'\n'"$requested"$'\n' = *$'\nmilvus\n'* ]] || continue ;;
    esac
    container=$("${original[@]}" ps -q "$service")
    [[ -n $container ]] || continue
    if [[ $service = mysql || $service = redis ]]; then
      for file in "$service/credential-entrypoint.sh" "$service/credential-health.sh"; do
        [[ -f $SCRIPT_DIR/$file && -r $SCRIPT_DIR/$file ]] || die '缺少配套中间件启动文件，账号未改变'
      done
    fi
    case "$service" in
      redis)
        docker exec "$container" sh -c 'test -x /usr/bin/setpriv && test -r /usr/local/bin/docker-entrypoint.sh' > "$folder/redis-tools.log" 2>&1 || die 'Redis镜像缺少已验证的用户切换工具，账号未改变'
        printf 'supported\n' > "$folder/redis-groups"
        # Standard managed layout only; compiler rejects include/shell overrides.
        if docker exec "$container" test -r /etc/redis.conf; then
          docker exec "$container" cat /etc/redis.conf 2>/dev/null > "$folder/redis.conf" || die '无法读取Redis配置，尚未修改账号'
        elif [[ -r $volume/redis/redis.conf ]]; then
          cp "$volume/redis/redis.conf" "$folder/redis.conf" || die '无法读取Redis配置，尚未修改账号'
        else
          die '无法读取Redis配置，尚未修改账号'
        fi
        chmod 600 "$folder/redis.conf"
        ;;
      milvus)
        docker exec "$container" cat /milvus/configs/milvus.yaml 2>/dev/null > "$folder/milvus.yaml" || die '无法读取Milvus原生配置'
        chmod 600 "$folder/milvus.yaml"
        if docker exec "$container" test -r /milvus/configs/user.yaml; then
          docker exec "$container" cat /milvus/configs/user.yaml 2>/dev/null > "$folder/user.yaml" || die '无法保存Milvus配置'
          chmod 600 "$folder/user.yaml"
        fi
        ;;
      minio)
        docker exec "$container" minio --version > "$folder/minio-version" 2>&1 || die '无法确认MinIO原生版本，尚未改密'
        if docker exec "$container" test -r /run/secrets/minio.user; then
          docker exec "$container" cat /run/secrets/minio.user > "$folder/minio.user" || die '无法保存MinIO账号配置'
          chmod 600 "$folder/minio.user"
        fi
        ;;
      mysql) old_socket=$(credential_rotation_socket "$BUNDLE/mysql-client.cnf" "$folder/mysql-socket.log" "$container") ;;
    esac
  done
  find "$folder" -type f -exec chmod 600 {} +
  credential_rotation_tool inventory --inventory-file "$folder" --socket-old "$old_socket" --key-file "$KEY_FILE" --out "$folder/inventory.json" || die '原部署资料校验失败，尚未修改账号'
  credential_rotation_tool capture --inventory-file "$folder/inventory.json" --inputs "$credential_rotation_manifest" --bundle "$BUNDLE" --key-file "$KEY_FILE" --env-file "$ENV_FILE" --out "$folder/verified.json" || die '选中组件未通过全部预检，账号尚未改变；请检查身份、权限和支持范围'
}

credential_rotation_confirm() {
  local answer=${BISHENG_ALLOW_CREDENTIAL_ROTATION:-}
  printf '本次改密组件：\n'
  credential_rotation_state info --field selected || die '无法读取改密计划'
  if [[ $answer != yes ]]; then
    [[ -t 0 ]] || die '请在交互终端重新执行原命令确认维护窗口'
    IFS= read -r -p '确认维护窗口、备份和其他节点已停写，允许暂停应用并修改以上密码？输入yes继续：' answer || die '维护确认已取消'
  fi
  [[ $answer = yes ]] || die '未确认维护；保留计划，下次原命令可以继续'
  credential_rotation_state mark --phase MAINTENANCE_CONFIRMED || die '维护确认保存失败，账号未改变'
}
credential_rotation_reload_redis_mount() {
  # Defense for sessions interrupted after a legacy live acl_setuser: reload the
  # read-only redis-users.acl mount without touching the data volume so preflight
  # sees file-backed identity again. No-op when redis is not mid-change.
  local phase id attempt state
  grep -qx redis "$credential_rotation_session/selected" 2>/dev/null || return 0
  phase=$(credential_rotation_state info --field component-phase --component redis 2>/dev/null) || return 0
  [[ $phase = CHANGE_INTENT || $phase = NATIVE_VERIFIED ]] || return 0
  id=$(compose ps -q redis 2>/dev/null) || return 0
  [[ -n $id ]] || return 0
  docker restart "$id" >/dev/null || return 0
  for attempt in {1..30}; do
    state=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$id" 2>/dev/null) || return 0
    case "$state" in healthy|running) return 0 ;; unhealthy|exited|dead) return 0 ;; esac
    sleep 1
  done
}
credential_rotation_ready() {
  local file=$1 service id state attempt ready executable
  for attempt in {1..150}; do
    ready=true
    while IFS= read -r service; do
      id=$("${COMPOSE[@]}" -p "$credential_rotation_project" -f "$file" ps -q "$service") || return 1
      [[ -n $id ]] || return 1
      state=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$id") || return 1
      case "$state" in healthy|running) ;; unhealthy|exited|dead) return 1 ;; *) ready=false ;; esac
      if [[ $service = elasticsearch && $state = healthy ]]; then
        executable=$(docker exec "$id" cat /proc/1/comm) || return 1
        # Bitnami setup starts a temporary JVM, then stops it and execs the
        # final JVM. A first successful TCP health check is insufficient.
        [[ $executable = java ]] || ready=false
      fi
    done < "$credential_rotation_session/services"
    [[ $ready != true ]] || return 0
    sleep 2
  done
  return 1
}
credential_rotation_run() {
  [[ -n ${credential_rotation_manifest:-}${credential_rotation_session:-} ]] || return 1
  local folder component stage phase original alias service mysql old new final name
  if [[ -z $credential_rotation_session ]]; then
    folder=$(mktemp -d "$credential_store/rotation-capture.XXXXXX")
    credential_rotation_capture "$folder"
    mkdir -p "$credential_store/rotations"
    credential_rotation_session="$credential_store/rotations/$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')"
    credential_rotation_tool prepare --bundle "$BUNDLE" --key-file "$KEY_FILE" --inputs "$credential_rotation_manifest" --env-file "$ENV_FILE" --inventory-file "$folder/verified.json" --installer-root "$SCRIPT_DIR" --secret-gid "$secret_gid" --deployment-root "$volume" --out-dir "$credential_rotation_session" || die '改密计划准备失败，账号未改变'
    printf '%s\n' "$credential_rotation_session" > "$credential_store/rotation.active.tmp"
    mv "$credential_store/rotation.active.tmp" "$credential_store/rotation.active"
    credential_rotation_state preflight || credential_rotation_fail '整批新旧身份预检未通过，账号未改变'
    credential_rotation_state mark --phase PREFLIGHT_OK || die '预检状态保存失败'
  fi
  credential_rotation_network=$(env_get "$ENV_FILE" BISHENG_NETWORK_NAME)
  credential_rotation_network=${credential_rotation_network:-bisheng-network}
  phase=$(credential_rotation_state info --field phase) || die '计划或密钥校验失败，不能续跑'
  if [[ $phase = PREPARED ]]; then
    credential_rotation_state preflight || credential_rotation_fail '整批新旧身份预检未通过，账号未改变'
    credential_rotation_state mark --phase PREFLIGHT_OK || die '密封预检计划无法恢复，账号未改变'
    phase=PREFLIGHT_OK
  fi
  if [[ $phase = COMPLETE ]]; then
    credential_rotation_state info --field request-id > "$credential_store/rotation.completed.tmp" || die '无法读取已完成请求'
    mv "$credential_store/rotation.completed.tmp" "$credential_store/rotation.completed"
    rm -f "$credential_store/rotation.active"
    return 0
  fi
  if [[ -t 0 && $phase != PREPARED && $phase != PREFLIGHT_OK ]]; then
    local recovery answer rollback
    IFS= read -r -p '恢复方式：1继续原计划，2申请配对回退［回车选1］：' recovery || die '恢复选择已取消'
    if [[ $recovery = 2 ]]; then
      IFS= read -r -p '配对回退会再次修改选中账号并恢复原配置，确认继续请输入yes：' answer || die '回退已取消'
      [[ $answer = yes ]] || die '未确认配对回退，原计划保留'
      rollback="$credential_store/rotations/$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')"
      credential_rotation_state rollback --out-dir "$rollback" --installer-root "$SCRIPT_DIR" --secret-gid "$secret_gid" --apply || die '当前计划不满足自动配对回退条件；原计划和停写状态保留，可继续原计划或由专人核实恢复'
      credential_rotation_session=$rollback
      credential_rotation_state mark --phase PREFLIGHT_OK || die '回退预检状态保存失败'
      printf '%s\n' "$credential_rotation_session" > "$credential_store/rotation.active.tmp"
      mv "$credential_store/rotation.active.tmp" "$credential_store/rotation.active"
    elif [[ -n $recovery && $recovery != 1 ]]; then die '请输入1或2后重新执行原命令'; fi
  fi
  credential_rotation_project=$(credential_rotation_state info --field project) || die '原项目身份读取失败'
  credential_rotation_state info --field consumers > "$credential_rotation_session/consumers" || die '无法读取需暂停应用'
  credential_rotation_state info --field selected > "$credential_rotation_session/selected" || die '无法读取选中组件'
  credential_rotation_paused=$(credential_rotation_state info --field paused) || die '无法核实原维护停写状态'
  credential_rotation_confirm
  credential_rotation_reload_redis_mount
  credential_rotation_state preflight || credential_rotation_fail '整批新旧身份复检未通过，本次未追加账号变更'
  credential_rotation_paused=true
  while IFS= read -r name; do
    [[ -z $name ]] || docker stop "$name" >/dev/null || credential_rotation_fail '暂停应用失败，账号未改变'
  done < "$credential_rotation_session/consumers"
  credential_rotation_state mark --phase CONSUMERS_STOPPED || credential_rotation_fail '暂停状态保存失败'
  while IFS= read -r component <&3; do
    phase=$(credential_rotation_state info --field component-phase --component "$component") || credential_rotation_fail '组件状态读取失败'
    [[ $phase != FILES_PERSISTED ]] || continue
    stage=$(credential_rotation_state info --field stage --component "$component") || credential_rotation_fail '目标配置读取失败'
    find "$stage" -maxdepth 1 -type f -exec chgrp "$secret_gid" {} + -exec chmod 640 {} +
    # Sealed-era stages kept derived files under stage/native/; Option C plaintext
    # bundles place secrets at the stage root, so skip when that directory is absent.
    if [[ -d $stage/native ]]; then
      find "$stage/native" -maxdepth 1 -type f -exec chgrp "$secret_gid" {} + -exec chmod 640 {} +
    fi
    if [[ -f $credential_rotation_session/native/redis.conf ]]; then
      chgrp "$secret_gid" "$credential_rotation_session/native/redis.conf"
      chmod 640 "$credential_rotation_session/native/redis.conf"
    fi
    original=$(credential_rotation_state info --field source) || credential_rotation_fail '原配置读取失败'
    old=UNKNOWN; new=UNKNOWN
    if [[ $component = mysql ]]; then
      mysql=$(compose ps -q mysql)
      old=$(credential_rotation_socket "$original/mysql-client.cnf" "$credential_rotation_session/socket-old.log" "$mysql")
      new=$(credential_rotation_socket "$stage/mysql-client.cnf" "$credential_rotation_session/socket-new.log" "$mysql")
    fi
    printf '正在处理%s密码和配套配置。\n' "$component"
    credential_rotation_state step --component "$component" --socket-old "$old" --socket-new "$new" --apply > "$credential_rotation_session/action" || credential_rotation_fail '原生账号处理未完成，请核对网络和账号状态后续跑；不会盲目重复写入'
    credential_rotation_state export --component "$component" --out "$credential_rotation_session/recreate.tmp.json" || credential_rotation_fail '原生配置导出失败'
    mv "$credential_rotation_session/recreate.tmp.json" "$credential_rotation_session/recreate.json"
    credential_rotation_state info --field images --component "$component" > "$credential_rotation_session/images" || credential_rotation_fail '原镜像信息读取失败'
    while IFS=' ' read -r original alias; do
      docker tag "$original" "$alias" || credential_rotation_fail '原镜像固定失败，未尝试下载替代镜像'
    done < "$credential_rotation_session/images"
    credential_rotation_state info --field services --component "$component" > "$credential_rotation_session/services" || credential_rotation_fail '原生依赖读取失败'
    local targets=()
    while IFS= read -r service; do targets+=("$service"); done < "$credential_rotation_session/services"
    "${COMPOSE[@]}" -p "$credential_rotation_project" -f "$credential_rotation_session/recreate.json" config --quiet || credential_rotation_fail '原生Compose校验失败'
    if [[ $component = minio ]]; then
      "${COMPOSE[@]}" -p "$credential_rotation_project" -f "$credential_rotation_session/recreate.json" stop milvus > "$credential_rotation_session/pause-milvus.log" 2>&1 || credential_rotation_fail '暂停对象存储消费者失败'
      "${COMPOSE[@]}" -p "$credential_rotation_project" -f "$credential_rotation_session/recreate.json" up -d --no-deps --force-recreate minio > "$credential_rotation_session/recreate.log" 2>&1 || credential_rotation_fail '对象存储容器更新失败'
      printf 'minio\n' > "$credential_rotation_session/services"
      credential_rotation_ready "$credential_rotation_session/recreate.json" || credential_rotation_fail '对象存储未就绪，Milvus保持暂停'
      printf 'milvus\n' > "$credential_rotation_session/services"
      "${COMPOSE[@]}" -p "$credential_rotation_project" -f "$credential_rotation_session/recreate.json" up -d --no-deps --force-recreate milvus >> "$credential_rotation_session/recreate.log" 2>&1 || credential_rotation_fail '对象存储消费者恢复失败'
    else
    "${COMPOSE[@]}" -p "$credential_rotation_project" -f "$credential_rotation_session/recreate.json" up -d --no-deps --force-recreate "${targets[@]}" > "$credential_rotation_session/recreate.log" 2>&1 || credential_rotation_fail '选中原生容器更新失败'
    fi
    credential_rotation_ready "$credential_rotation_session/recreate.json" || credential_rotation_fail '原生容器启动未就绪'
    # Milvus defaultRootPassword only initializes a missing root user. Verify
    # updates a root credential already stored in the data volume, then checks
    # the new password. The shell never sees either password.
    if [[ $component = mysql ]]; then
      mysql=$(compose ps -q mysql)
      original=$(credential_rotation_state info --field source) || credential_rotation_fail '原配置读取失败'
      old=$(credential_rotation_socket "$original/mysql-client.cnf" "$credential_rotation_session/socket-old.log" "$mysql")
      new=$(credential_rotation_socket "$stage/mysql-client.cnf" "$credential_rotation_session/socket-new.log" "$mysql")
    fi
    credential_rotation_state verify --component "$component" --socket-old "$old" --socket-new "$new" || credential_rotation_fail '新密码可用或旧密码失效尚未确认'
    credential_rotation_state persist --component "$component" || credential_rotation_fail '组件持久化状态保存失败'
  done 3< "$credential_rotation_session/selected"
  # A persisted checkpoint does not prove credentials remained valid during
  # an outage; recheck all selected identities before activating applications.
  while IFS= read -r component <&3; do
    old=UNKNOWN; new=UNKNOWN
    if [[ $component = mysql ]]; then
      original=$(credential_rotation_state info --field source) || credential_rotation_fail '原配置读取失败'
      stage=$(credential_rotation_state info --field stage --component "$component") || credential_rotation_fail '目标配置读取失败'
      mysql=$(compose ps -q mysql)
      old=$(credential_rotation_socket "$original/mysql-client.cnf" "$credential_rotation_session/socket-old.log" "$mysql")
      new=$(credential_rotation_socket "$stage/mysql-client.cnf" "$credential_rotation_session/socket-new.log" "$mysql")
    fi
    credential_rotation_state verify --component "$component" --socket-old "$old" --socket-new "$new" || credential_rotation_fail '最终新旧身份复检失败，应用保持停止'
  done 3< "$credential_rotation_session/selected"
  credential_rotation_state mark --phase ALL_VERIFIED || credential_rotation_fail '全部组件验证尚未完成'
  credential_rotation_state policy || credential_rotation_fail '部署策略生成失败'
  final=$(credential_rotation_state info --field final) || credential_rotation_fail '最终配置读取失败'
  BUNDLE=$final
  credential_runtime_publish_bundle
  final=$BUNDLE
  credential_rotation_state mark --phase ACTIVATING || credential_rotation_fail '启用状态保存失败'
  cp "$ENV_FILE" "$credential_store/rotation.activation.tmp"
  env_set "$credential_store/rotation.activation.tmp" BISHENG_CREDENTIALS_DIR "$final"
  env_set "$credential_store/rotation.activation.tmp" BISHENG_SECRET_KEYS_FILE "$KEY_FILE"
  env_set "$credential_store/rotation.activation.tmp" BISHENG_CREDENTIAL_REVISION "$(credential_revision "$final")"
  env_set "$credential_store/rotation.activation.tmp" BISHENG_SECRET_FILE_GID "$secret_gid"
  mv "$credential_store/rotation.activation.tmp" "$ENV_FILE"
  cp "$ENV_FILE" "$credential_store/prepared.env"
  BUNDLE=$final
  compose config --quiet || credential_rotation_fail '最终应用配置校验失败'
  # Only services that were running before maintenance are restored.
  for service in backend backend_worker frontend; do
    while IFS= read -r name; do
      local original_service
      original_service=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.service"}}' "$name") || credential_rotation_fail '原应用身份读取失败'
      [[ $original_service = "$service" ]] || continue
      compose up -d --no-deps --force-recreate "$service" > "$credential_rotation_session/apps.log" 2>&1 || credential_rotation_fail '应用恢复失败'
    done < "$credential_rotation_session/consumers"
  done
  # Fresh connections validate the activated bundle; pending unselected items
  # remain visible and are bound to the signed deployment policy.
  credential_rotation_tool validate-policy --bundle "$BUNDLE" --key-file "$KEY_FILE" --env-file "$ENV_FILE" >/dev/null || credential_rotation_fail '最终部署策略验证失败'
  local ready attempt
  ready=false
  # Backend health interval is 90s and startup can still be initializing after
  # two minutes. Match credential_wait_apps: 120 * 3s.
  for attempt in {1..120}; do
    ready=true
    while IFS= read -r name; do
      [[ -z $name ]] && continue
      phase=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$name") || credential_rotation_fail '应用状态读取失败'
      case "$phase" in healthy|running) ;; unhealthy|exited|dead) credential_rotation_fail '应用未通过启动检查' ;; *) ready=false ;; esac
    done < "$credential_rotation_session/consumers"
    [[ $ready != true ]] || break
    sleep 3
  done
  [[ $ready = true ]] || credential_rotation_fail '应用就绪等待超时'
  credential_rotation_state mark --phase SERVICES_READY || credential_rotation_fail '应用状态保存失败'
  credential_rotation_state mark --phase COMPLETE || credential_rotation_fail '完成状态保存失败'
  credential_rotation_state info --field request-id > "$credential_store/rotation.completed.tmp" || credential_rotation_fail '完成标记生成失败'
  mv "$credential_store/rotation.completed.tmp" "$credential_store/rotation.completed"
  rm -f "$credential_store/rotation.active"
  credential_rotation_paused=false
  return 0
}
