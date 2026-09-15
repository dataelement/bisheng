#!/usr/bin/env bash
# 按 minio-jobs.tsv 把 B 知识库对象拷到 A 新键. 禁止覆盖 A 已有键.
set -euo pipefail
STEP="p5.20-minio"
APPLY="${APPLY:-0}"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
# shellcheck disable=SC1091
source "${PACK_ROOT}/lib/fusion_remote.sh"

: "${B_MINIO_BUCKET:=bisheng}"
: "${A_MINIO_BUCKET:=bisheng}"
: "${IMAGE_MC:=minio/mc:RELEASE.2024-11-21T17-21-54Z}"
: "${A_MINIO_CONTAINER:=}"
: "${B_MINIO_CONTAINER:=}"

jobs="${LOG_DIR}/p5/minio-jobs.tsv"
[[ -f "${jobs}" ]] || die "缺少 ${jobs}, 先跑 p5/30-apply.sh 生成 SQL"

guess_minio() {
  local side="$1"
  if [[ "${side}" == "a" ]]; then
    fusion_ssh_a docker ps --format '{{.Names}}' | grep -i minio | grep -vi milvus | head -1
  else
    docker ps --format '{{.Names}}' | grep -i minio | grep -vi milvus | head -1
  fi
}

if [[ -z "${B_MINIO_CONTAINER}" ]]; then
  B_MINIO_CONTAINER="$(guess_minio b || true)"
fi
if [[ -z "${A_MINIO_CONTAINER}" ]]; then
  A_MINIO_CONTAINER="$(guess_minio a || true)"
fi
if [[ -z "${B_MINIO_CONTAINER}" || -z "${A_MINIO_CONTAINER}" ]]; then
  if [[ "${APPLY}" != "1" ]]; then
    log "未发现 MinIO 容器 (B=${B_MINIO_CONTAINER:-?} A=${A_MINIO_CONTAINER:-?}), APPLY=0 跳过. APPLY=1 须 export B_MINIO_CONTAINER / A_MINIO_CONTAINER"
    ledger "${STEP}" "OK" "skip-no-container"
    echo "OK ${STEP} skipped (no minio container)"
    exit 0
  fi
  die "未发现 MinIO 容器, 请 export B_MINIO_CONTAINER / A_MINIO_CONTAINER"
fi

container_env() {
  local side="$1" container="$2" key="$3"
  if [[ "${side}" == "a" ]]; then
    fusion_ssh_a docker exec "${container}" printenv "${key}" 2>/dev/null || true
  else
    docker exec "${container}" printenv "${key}" 2>/dev/null || true
  fi
}

b_user="$(container_env b "${B_MINIO_CONTAINER}" MINIO_ROOT_USER)"
[[ -n "${b_user}" ]] || b_user="$(container_env b "${B_MINIO_CONTAINER}" MINIO_ACCESS_KEY)"
b_pass="$(container_env b "${B_MINIO_CONTAINER}" MINIO_ROOT_PASSWORD)"
[[ -n "${b_pass}" ]] || b_pass="$(container_env b "${B_MINIO_CONTAINER}" MINIO_SECRET_KEY)"
a_user="$(container_env a "${A_MINIO_CONTAINER}" MINIO_ROOT_USER)"
[[ -n "${a_user}" ]] || a_user="$(container_env a "${A_MINIO_CONTAINER}" MINIO_ACCESS_KEY)"
a_pass="$(container_env a "${A_MINIO_CONTAINER}" MINIO_ROOT_PASSWORD)"
[[ -n "${a_pass}" ]] || a_pass="$(container_env a "${A_MINIO_CONTAINER}" MINIO_SECRET_KEY)"
[[ -n "${b_user}" && -n "${b_pass}" ]] || die "读不到 B MinIO 账号, 检查 ${B_MINIO_CONTAINER} 环境变量"
[[ -n "${a_user}" && -n "${a_pass}" ]] || die "读不到 A MinIO 账号, 检查 ${A_MINIO_CONTAINER} 环境变量"

mc_b() {
  docker run --rm --network "container:${B_MINIO_CONTAINER}" \
    -e "MC_HOST_src=http://${b_user}:${b_pass}@127.0.0.1:9000" \
    "${IMAGE_MC}" "$@"
}

mc_a() {
  fusion_ssh_a docker run --rm --network "container:${A_MINIO_CONTAINER}" \
    -e "MC_HOST_dst=http://${a_user}:${a_pass}@127.0.0.1:9000" \
    "${IMAGE_MC}" "$@"
}

copied=0
total=0
while IFS= read -r line; do
  [[ -n "${line}" ]] || continue
  [[ "${line}" == b_file_id* ]] && continue
  src="$(printf '%s' "${line}" | awk -F'\t' '{print $2}')"
  dst="$(printf '%s' "${line}" | awk -F'\t' '{print $3}')"
  [[ -n "${src}" && -n "${dst}" ]] || continue
  total=$((total + 1))
  if mc_a stat "dst/${A_MINIO_BUCKET}/${dst}" >/dev/null 2>&1; then
    die "A 已有对象 ${dst}, 拒绝覆盖"
  fi
  if [[ "${APPLY}" != "1" ]]; then
    continue
  fi
  log "copy ${src} -> ${dst}"
  mc_b cat "src/${B_MINIO_BUCKET}/${src}" | mc_a pipe "dst/${A_MINIO_BUCKET}/${dst}" \
    || die "拷贝失败 ${src} -> ${dst}"
  copied=$((copied + 1))
done < "${jobs}"

if [[ "${APPLY}" != "1" ]]; then
  log "APPLY=0, 将拷 ${total} 个对象. B=${B_MINIO_CONTAINER}/${B_MINIO_BUCKET} A=${A_MINIO_CONTAINER}/${A_MINIO_BUCKET}"
else
  log "copied=${copied} total=${total}"
fi
ledger "${STEP}" "OK" "APPLY=${APPLY} jobs=${total} copied=${copied}"
echo "OK ${STEP} jobs=${total} APPLY=${APPLY}"
