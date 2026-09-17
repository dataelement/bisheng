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
python3 "${PACK_ROOT}/p5/rebuild_minio_jobs.py" \
  --dump "${LOG_DIR}/p5/dump.json" \
  --maps "${LOG_DIR}/p4/maps" \
  --out "${jobs}"
[[ -f "${jobs}" ]] || die "缺少 ${jobs}, 先跑 p5/30-apply.sh 生成 SQL"

guess_minio() {
  # 现场常见 container_name=bisheng-milvus-minio, 但业务也走同一实例 (compose 服务名 minio).
  # 先排除 milvus, 找不到再回退到任意 minio 容器.
  local side="$1" names=""
  if [[ "${side}" == "a" ]]; then
    names="$(fusion_ssh_a docker ps --format '{{.Names}}')"
  else
    names="$(docker ps --format '{{.Names}}')"
  fi
  printf '%s\n' "${names}" | grep -i minio | grep -vi milvus | head -1 \
    || printf '%s\n' "${names}" | grep -i minio | head -1
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
  # 必须吃掉本地 stdin, 否则 while-read 作业文件会被 ssh 吸走只处理第一行
  fusion_ssh_a docker run --rm --network "container:${A_MINIO_CONTAINER}" \
    -e "MC_HOST_dst=http://${a_user}:${a_pass}@127.0.0.1:9000" \
    "${IMAGE_MC}" "$@" </dev/null
}

ensure_mc_image() {
  if docker image inspect "${IMAGE_MC}" >/dev/null 2>&1; then
    log "B 已有 mc 镜像 ${IMAGE_MC}"
    return
  fi
  log "B 拉取 mc 镜像 ${IMAGE_MC}"
  docker pull "${IMAGE_MC}"
}

ensure_mc_image_a() {
  if fusion_ssh_a docker image inspect "${IMAGE_MC}" >/dev/null 2>&1; then
    log "A 已有 mc 镜像 ${IMAGE_MC}"
    return
  fi
  log "A 拉不到 dockerhub 时从 B 导镜像"
  if fusion_ssh_a docker pull "${IMAGE_MC}"; then
    return
  fi
  local img="/tmp/fusion-mc-image-$$.tar"
  docker save "${IMAGE_MC}" -o "${img}"
  fusion_scp_to_a "${img}" /tmp/fusion-mc-image.tar
  rm -f "${img}"
  fusion_ssh_a docker load -i /tmp/fusion-mc-image.tar
  fusion_ssh_a rm -f /tmp/fusion-mc-image.tar
}

ensure_mc_image
if [[ "${APPLY}" == "1" ]]; then
  ensure_mc_image_a
fi

copied=0
total=0
missing=0
skipped=0
stage="/tmp/fusion-minio-stage-$$"
mkdir -p "${stage}"
cleanup_stage() { rm -rf "${stage}" "/tmp/fusion-minio-stage-$$.tgz"; }
trap cleanup_stage EXIT

while IFS= read -r line <&3; do
  [[ -n "${line}" ]] || continue
  [[ "${line}" == b_file_id* ]] && continue
  src="$(printf '%s' "${line}" | awk -F'\t' '{print $2}')"
  dst="$(printf '%s' "${line}" | awk -F'\t' '{print $3}')"
  [[ -n "${src}" && -n "${dst}" ]] || continue
  total=$((total + 1))
  if [[ "${APPLY}" != "1" ]]; then
    continue
  fi
  mkdir -p "${stage}/$(dirname "${dst}")"
  if docker run --rm --network "container:${B_MINIO_CONTAINER}" \
    -v "${stage}:/stage" \
    -e "MC_HOST_src=http://${b_user}:${b_pass}@127.0.0.1:9000" \
    "${IMAGE_MC}" cp "src/${B_MINIO_BUCKET}/${src}" "/stage/${dst}"; then
    copied=$((copied + 1))
  else
    log "B 无对象 ${src}"
    missing=$((missing + 1))
  fi
done 3< "${jobs}"

if [[ "${APPLY}" == "1" && "${copied}" -gt 0 ]]; then
  tarfile="/tmp/fusion-minio-stage-$$.tgz"
  tar -C "${stage}" -czf "${tarfile}" .
  fusion_scp_to_a "${tarfile}" /tmp/fusion-minio-stage.tgz
  fusion_ssh_a bash -s <<REMOTE
set -euo pipefail
stage=/tmp/fusion-minio-stage
rm -rf "\$stage"
mkdir -p "\$stage"
tar -C "\$stage" -xzf /tmp/fusion-minio-stage.tgz
docker run --rm --network "container:${A_MINIO_CONTAINER}" \
  -v "\$stage:/stage" \
  -e "MC_HOST_dst=http://${a_user}:${a_pass}@127.0.0.1:9000" \
  "${IMAGE_MC}" mirror "/stage" "dst/${A_MINIO_BUCKET}"
rm -rf "\$stage" /tmp/fusion-minio-stage.tgz
REMOTE
fi

if [[ "${APPLY}" != "1" ]]; then
  log "APPLY=0, 将拷 ${total} 个对象. B=${B_MINIO_CONTAINER}/${B_MINIO_BUCKET} A=${A_MINIO_CONTAINER}/${A_MINIO_BUCKET}"
else
  log "copied=${copied} skipped=${skipped} missing=${missing} total=${total}"
fi
ledger "${STEP}" "OK" "APPLY=${APPLY} jobs=${total} copied=${copied} skipped=${skipped:-0} missing=${missing:-0}"
echo "OK ${STEP} jobs=${total} copied=${copied} skipped=${skipped:-0} missing=${missing:-0} APPLY=${APPLY}"
