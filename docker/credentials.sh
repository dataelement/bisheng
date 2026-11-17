#!/usr/bin/env bash
# Execute the offline tool from the release backend image, never host Python.
set -euo pipefail
umask 077
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/install-env.sh"
die() { printf 'credentials: %s\n' "$*" >&2; exit 2; }
image=""; network=none
while [[ $# -gt 0 ]]; do
  case "$1" in
    --image|--network) [[ $# -ge 2 ]] || die 'missing wrapper option'; if [[ $1 = --image ]]; then image=$2; else network=$2; fi; shift 2 ;;
    *) break ;;
  esac
done
[[ $# -gt 0 ]] || die 'specify keygen, prepare or check; --image IMAGE [--network NETWORK]'
image=${image:-$(env_get "$SCRIPT_DIR/.env" BISHENG_BACKEND_IMAGE)}
[[ -n $image ]] || die 'set --image to the matching credential-enabled backend image'
args=("$@")
deployment_marker="$(credential_store_path)/deployment.id"
has_deployment=false
for arg in "$@"; do [[ $arg != --deployment-id ]] || has_deployment=true; done
if [[ -f $deployment_marker && $has_deployment = false ]]; then
  deployment=$(cat "$deployment_marker")
  [[ $deployment =~ ^[0-9a-f]{32}$ ]] || die 'invalid deployment identity'
  args+=(--deployment-id "$deployment")
fi
if [[ ${args[0]:-} = artifact && -t 1 ]]; then
  case ${args[1]:-} in open-stream|native-stream) die 'decrypted material requires a private output pipe' ;; esac
fi
for arg in "$@"; do
  [[ $arg != --online || $network != none ]] || die 'online check requires explicit --network'
done
if [[ ${args[0]:-} = artifact ]]; then
  case ${args[1]:-} in es-discover|es-freeze|es-observe|es-verify|es-persist) [[ $network != none ]] || die 'ES migration requires explicit project network' ;; esac
  for arg in "${args[@]}"; do [[ $arg != --preserve-redis-acl || $network != none ]] || die 'Redis ACL capture requires explicit project network'; done
fi
if [[ ${args[0]:-} = rotation ]]; then
  case "${args[1]:-}" in capture|preflight|step|verify) [[ $network != none ]] || die 'native rotation requires explicit --network' ;; esac
fi
mounts=(); i=0; rotation_session=""
add_context_mount() {
  local directory
  directory=$(dirname "$1")
  while [[ $directory != / ]]; do
    if [[ -f $directory/.artifact-context.json ]]; then
      add_mount "$directory/.artifact-context.json" true
      return
    fi
    directory=$(dirname "$directory")
  done
}
add_mount() {
  local path=$1 readonly=$2 spec existing index=0
  spec="type=bind,source=$path,target=$path"
  for existing in ${mounts[@]+"${mounts[@]}"}; do
    if [[ $existing = "$spec" || $existing = "$spec,readonly" ]]; then
      # Input and output parents may coincide. Keep one mount; an explicitly
      # requested output needs write access regardless of argument order.
      if [[ $readonly = false ]]; then mounts[$index]=$spec; fi
      return
    fi
    index=$((index + 1))
  done
  if [[ $readonly = true ]]; then spec="$spec,readonly"; fi
  mounts+=(--mount "$spec")
}
while [[ $i -lt ${#args[@]} ]]; do
  case "${args[$i]}" in
    --policy-root|--session-dir|--inventory-file|--out|--out-dir|--destination|--config|--inputs|--base-bundle|--bundle|--key-file|--env-file|--runtime-env-file|--primary-file|--retiring-file|--deployment-root|--file|--key-dir)
      flag=${args[$i]}; i=$((i+1)); [[ $i -lt ${#args[@]} ]] || die 'missing path'
      path=${args[$i]}; [[ $path = /* && $path != *,* ]] || die 'use absolute paths without commas'
      if [[ $flag = --out || $flag = --out-dir || $flag = --destination ]]; then
        [[ $flag = --destination || ! -e $path ]] || die 'output already exists'
        parent=$(dirname "$path"); [[ -d $parent ]] || die 'create a private output parent first'
        add_mount "$parent" false
      elif [[ $flag = --key-dir ]]; then
        [[ -d $path ]] || die 'create the private role-key directory first'
        add_mount "$path" false
      elif [[ $flag = --session-dir ]]; then
        rotation_session=$path
        [[ -d $path ]] || die 'rotation session missing'
        add_mount "$path" false
      elif [[ $flag = --env-file && ${args[0]:-} = artifact && ${args[1]:-} = sanitize-env ]]; then
        [[ -f $path ]] || die 'environment file missing'
        add_mount "$(dirname "$path")" false
      elif [[ $flag = --bundle && ${args[0]:-} = artifact && ${args[1]:-} = migrate-verify ]]; then
        [[ -d $path ]] || die 'staged migration bundle missing'
        add_mount "$path" false  # Verification writes the signed deployment policy.
      elif [[ $flag = --policy-root && ${args[0]:-} = artifact && ${args[1]:-} = migrate-clean ]]; then
        [[ -f $path/deployment.id ]] || die 'managed deployment store marker missing'
        add_mount "$path" false
      elif [[ $flag = --inputs ]]; then
        [[ -f $path ]] || die 'input manifest missing'
        parent=$(dirname "$path")
        add_mount "$parent" true
        add_context_mount "$path"
      else
        [[ -e $path ]] || die 'input path missing'
        add_mount "$path" true
        add_context_mount "$path"
      fi ;;
  esac
  i=$((i+1))
done
# Journal may reference absolute paths that never appear on the CLI (adopt
# source/bundle under another project tree). Without binding them, the
# read-only tool container fails with a misleading "invalid YAML" error.
mount_session_journal_paths() {
  local session=$1 journal=$1/journal.json path
  [[ -f $journal ]] || return 0
  command -v python3 >/dev/null 2>&1 || die 'python3 required to resolve session journal paths'
  while IFS= read -r path; do
    [[ -n $path ]] || continue
    [[ $path = /* && $path != *,* ]] || die "session journal path must be absolute without commas: $path"
    [[ -e $path ]] || die "session journal references missing path: $path"
    add_mount "$path" true
    add_context_mount "$path"
  done < <(python3 -c '
import json, sys
journal = json.load(open(sys.argv[1], encoding="utf-8"))
seen = set()
for key in ("source", "bundle", "store"):
    value = journal.get(key)
    if isinstance(value, str) and value not in seen:
        seen.add(value)
        print(value)
' "$journal")
}
if [[ -n ${rotation_session:-} ]]; then
  mount_session_journal_paths "$rotation_session"
fi
# No docker --env-file or host secret environment is inherited. The Python
# --env-file option parses a read-only file without shell evaluation.
docker image inspect "$image" >/dev/null 2>&1 || die 'local image unavailable; prepare-only never pulls'
labels=()
if [[ -n $rotation_session ]]; then
  active=$(docker ps -q --filter "label=com.bisheng.credential.session=$rotation_session") || die 'cannot inspect in-flight maintenance'
  [[ -z $active ]] || die 'a previous tool still owns this session; wait for it to exit before retrying'
  labels+=(--label "com.bisheng.credential.session=$rotation_session")
fi
stdin_args=()
if [[ ${args[0]:-} = artifact ]]; then
  case ${args[1]:-} in seal-input|seal-stream|seed|migrate-bindings|es-capture|es-compile-current) stdin_args=(-i) ;; esac
fi
exec docker run ${labels[@]+"${labels[@]}"} ${stdin_args[@]+"${stdin_args[@]}"} --rm --pull=never --network "$network" --read-only --ulimit core=0:0 --tmpfs /tmp:rw,nosuid,noexec,size=64m \
  --user "$(id -u):$(id -g)" -e PYTHONDONTWRITEBYTECODE=1 \
  ${mounts[@]+"${mounts[@]}"} --entrypoint python "$image" -m bisheng.core.config.credential_tool "${args[@]}"
