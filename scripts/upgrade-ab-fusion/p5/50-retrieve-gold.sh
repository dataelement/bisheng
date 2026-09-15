#!/usr/bin/env bash
# 检索金标: 同一向量在 B/A 对打, 比较 remap 后的 file_id. 只读, 不写 A.
set -euo pipefail
STEP="p5.50-gold"
GOLD_SAMPLE="${GOLD_SAMPLE:-3}"
GOLD_K="${GOLD_K:-5}"
GOLD_MIN_HIT="${GOLD_MIN_HIT:-0.8}"
GOLD_ALLOW_FAIL="${GOLD_ALLOW_FAIL:-0}"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
# shellcheck disable=SC1091
source "${PACK_ROOT}/lib/fusion_remote.sh"

: "${BACKEND_CONTAINER:=bisheng-backend}"
: "${A_BACKEND_CONTAINER:=bisheng-backend}"

jobs="${LOG_DIR}/p5/vector-jobs.tsv"
maps="${LOG_DIR}/p4/maps"
[[ -f "${jobs}" ]] || die "缺少 ${jobs}, 先跑 p5/22-copy-vectors.sh"
[[ -d "${maps}" ]] || die "缺少 ${maps}"

guess_backend() {
  local side="$1"
  if [[ "${side}" == "a" ]]; then
    fusion_ssh_a docker ps --format '{{.Names}}' | grep -i backend | grep -vi worker | head -1
  else
    docker ps --format '{{.Names}}' | grep -i backend | grep -vi worker | head -1
  fi
}

if ! docker ps --format '{{.Names}}' | grep -qx "${BACKEND_CONTAINER}"; then
  BACKEND_CONTAINER="$(guess_backend b || true)"
fi
if ! fusion_ssh_a docker ps --format '{{.Names}}' | grep -qx "${A_BACKEND_CONTAINER}"; then
  A_BACKEND_CONTAINER="$(guess_backend a || true)"
fi
[[ -n "${BACKEND_CONTAINER}" && -n "${A_BACKEND_CONTAINER}" ]] || die "检索金标需要两侧 backend 容器"

docker exec "${BACKEND_CONTAINER}" mkdir -p /tmp/ab-fusion
docker cp "${PACK_ROOT}/p5/vector_runtime.py" "${BACKEND_CONTAINER}:/tmp/ab-fusion/vector_runtime.py"
fusion_ssh_a mkdir -p /tmp/ab-fusion
fusion_scp_to_a "${PACK_ROOT}/p5/vector_runtime.py" /tmp/ab-fusion/vector_runtime.py
fusion_ssh_a docker exec "${A_BACKEND_CONTAINER}" mkdir -p /tmp/ab-fusion
fusion_ssh_a docker cp /tmp/ab-fusion/vector_runtime.py "${A_BACKEND_CONTAINER}:/tmp/ab-fusion/vector_runtime.py"

runtime_b() {
  docker exec -i "${BACKEND_CONTAINER}" python /tmp/ab-fusion/vector_runtime.py "$@"
}
runtime_a() {
  fusion_ssh_a docker exec -i "${A_BACKEND_CONTAINER}" python /tmp/ab-fusion/vector_runtime.py "$@"
}

work="${LOG_DIR}/p5/gold-work"
mkdir -p "${work}"
cases="${work}/cases.json"
echo '[]' > "${cases}"

copy_n=0
while IFS=$'\t' read -r b_id a_id type verdict b_collection a_collection b_index a_index expr conversions reason; do
  [[ "${b_id}" == "b_id" || -z "${b_id}" ]] && continue
  [[ "${verdict}" == "copy" || "${verdict}" == "convert" ]] || continue
  copy_n=$((copy_n + 1))
  job_dir="${work}/${b_id}"
  mkdir -p "${job_dir}"
  runtime_b sample-milvus --collection "${b_collection}" --limit "${GOLD_SAMPLE}" --out "/tmp/ab-fusion/${b_id}.sample.jsonl"
  docker cp "${BACKEND_CONTAINER}:/tmp/ab-fusion/${b_id}.sample.jsonl" "${job_dir}/sample.jsonl"
  i=0
  while IFS= read -r line; do
    [[ -z "${line}" ]] && continue
    i=$((i + 1))
    printf '%s\n' "${line}" > "${job_dir}/${i}.vec.json"
    fusion_scp_to_a "${job_dir}/${i}.vec.json" "/tmp/ab-fusion/${b_id}.${i}.vec.json"
    docker cp "${job_dir}/${i}.vec.json" "${BACKEND_CONTAINER}:/tmp/ab-fusion/${b_id}.${i}.vec.json"
    fusion_ssh_a docker cp "/tmp/ab-fusion/${b_id}.${i}.vec.json" "${A_BACKEND_CONTAINER}:/tmp/ab-fusion/${b_id}.${i}.vec.json"
    runtime_b search-milvus --collection "${b_collection}" --vector-file "/tmp/ab-fusion/${b_id}.${i}.vec.json" \
      --limit "${GOLD_K}" --out "/tmp/ab-fusion/${b_id}.${i}.b.json"
    runtime_a search-milvus --collection "${a_collection}" --vector-file "/tmp/ab-fusion/${b_id}.${i}.vec.json" \
      --limit "${GOLD_K}" --out "/tmp/ab-fusion/${b_id}.${i}.a.json"
    docker cp "${BACKEND_CONTAINER}:/tmp/ab-fusion/${b_id}.${i}.b.json" "${job_dir}/${i}.b.json"
    fusion_ssh_a docker cp "${A_BACKEND_CONTAINER}:/tmp/ab-fusion/${b_id}.${i}.a.json" "/tmp/ab-fusion/${b_id}.${i}.a.json"
    fusion_scp_from_a "/tmp/ab-fusion/${b_id}.${i}.a.json" "${job_dir}/${i}.a.json"
    python3 - "${cases}" "${b_id}" "${a_collection}" "${job_dir}/${i}.b.json" "${job_dir}/${i}.a.json" <<'PY'
import json, sys
from pathlib import Path
path, b_id, a_coll, b_hits_p, a_hits_p = sys.argv[1:6]
cases = json.loads(Path(path).read_text(encoding="utf-8"))
cases.append({
    "b_id": b_id,
    "a_collection": a_coll,
    "b_hits": json.loads(Path(b_hits_p).read_text(encoding="utf-8")),
    "a_hits": json.loads(Path(a_hits_p).read_text(encoding="utf-8")),
})
Path(path).write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
PY
  done < "${job_dir}/sample.jsonl"
done < "${jobs}"

out="${LOG_DIR}/p5/retrieve-gold.tsv"
set +e
python3 "${PACK_ROOT}/p5/score_retrieve_gold.py" \
  --cases "${cases}" \
  --maps "${maps}" \
  --out "${out}" \
  --k "${GOLD_K}" \
  --min-overlap "${GOLD_MIN_HIT}"
rc=$?
set -e
if [[ "${rc}" != "0" && "${GOLD_ALLOW_FAIL}" == "1" ]]; then
  log "金标未达标, GOLD_ALLOW_FAIL=1 继续"
  rc=0
fi
ledger "${STEP}" "$([[ ${rc} == 0 ]] && echo OK || echo FAIL)" "jobs=${copy_n}"
[[ "${rc}" == "0" ]] || die "检索金标未达标, 见 ${out}"
echo "OK ${STEP} copy_jobs=${copy_n} -> ${out}"
