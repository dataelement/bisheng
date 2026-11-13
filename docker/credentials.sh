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
for arg in "$@"; do
  [[ $arg != --online || $network != none ]] || die 'online check requires explicit --network'
done
mounts=(); i=0
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
    --out|--out-dir|--config|--inputs|--base-bundle|--bundle|--key-file|--env-file|--runtime-env-file|--primary-file|--retiring-file|--deployment-root)
      flag=${args[$i]}; i=$((i+1)); [[ $i -lt ${#args[@]} ]] || die 'missing path'
      path=${args[$i]}; [[ $path = /* && $path != *,* ]] || die 'use absolute paths without commas'
      if [[ $flag = --out || $flag = --out-dir ]]; then
        [[ ! -e $path ]] || die 'output already exists'
        parent=$(dirname "$path"); [[ -d $parent ]] || die 'create a private output parent first'
        add_mount "$parent" false
      elif [[ $flag = --inputs ]]; then
        [[ -f $path ]] || die 'input manifest missing'
        parent=$(dirname "$path")
        add_mount "$parent" true
      else
        [[ -e $path ]] || die 'input path missing'
        add_mount "$path" true
      fi ;;
  esac
  i=$((i+1))
done
# No docker --env-file or host secret environment is inherited. The Python
# --env-file option parses a read-only file without shell evaluation.
docker image inspect "$image" >/dev/null 2>&1 || die 'local image unavailable; prepare-only never pulls'
exec docker run --rm --pull=never --network "$network" --read-only --tmpfs /tmp:rw,nosuid,noexec,size=64m \
  --user "$(id -u):$(id -g)" -e PYTHONDONTWRITEBYTECODE=1 \
  ${mounts[@]+"${mounts[@]}"} --entrypoint python "$image" -m bisheng.core.config.credential_tool "${args[@]}"
