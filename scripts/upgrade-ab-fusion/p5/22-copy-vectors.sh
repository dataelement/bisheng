#!/usr/bin/env bash
# 方案 8.3: 兼容则物理迁入 Milvus/ES (保留向量, 重写 ID); 不兼容进例外清单, 不自动重解析.
# 禁止写 A 原 type=3 的 Collection/Index. 禁止覆盖 A 已有名.
set -euo pipefail
STEP="p5.22-vectors"
APPLY="${APPLY:-0}"
ACTION="${ACTION:-copy}"
BATCH_NO="${BATCH_NO:-fusion}"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
# shellcheck disable=SC1091
source "${PACK_ROOT}/lib/fusion_remote.sh"

: "${BACKEND_CONTAINER:=bisheng-backend}"
: "${A_BACKEND_CONTAINER:=bisheng-backend}"

mkdir -p "${LOG_DIR}/p5"
dump="${LOG_DIR}/p5/dump.json"
maps="${LOG_DIR}/p4/maps"
if [[ "${ACTION}" != "drop" ]]; then
  [[ -f "${dump}" ]] || die "缺少 ${dump}, 先跑 p5/30-apply.sh"
  [[ -d "${maps}" ]] || die "缺少 ${maps}"
  [[ -f "${maps}/knowledge-map.csv" ]] || die "缺少 knowledge-map.csv"
fi

forbid="${LOG_DIR}/p5/a-space-store-names.txt"
: > "${forbid}"
if [[ -f "${LOG_DIR}/p5/a-space-stores.tsv" ]]; then
  awk -F'\t' 'NR>1 {if($2!="") print $2; if($3!="") print $3}' "${LOG_DIR}/p5/a-space-stores.tsv" \
    | sed '/^$/d' >> "${forbid}"
fi
if [[ -f "${LOG_DIR}/p5/a-space-ids.txt" && -f "${LOG_DIR}/p5/a-knowledge-stores.tsv" ]]; then
  python3 - "${LOG_DIR}/p5/a-space-ids.txt" "${LOG_DIR}/p5/a-knowledge-stores.tsv" "${forbid}" <<'PY'
import sys
from pathlib import Path
ids=set()
for ln in Path(sys.argv[1]).read_text(encoding="utf-8").split():
    try:
        ids.add(int(ln))
    except ValueError:
        pass
out=Path(sys.argv[3])
old=set(x.strip() for x in out.read_text(encoding="utf-8").splitlines() if x.strip())
for ln in Path(sys.argv[2]).read_text(encoding="utf-8").splitlines()[1:]:
    parts=ln.split("\t")
    if len(parts)<4:
        continue
    try:
        kid=int(parts[0])
    except ValueError:
        continue
    if kid in ids:
        old.update(p for p in parts[2:4] if p)
out.write_text("\n".join(sorted(old))+"\n", encoding="utf-8")
PY
fi

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

stage_b() {
  docker exec "${BACKEND_CONTAINER}" mkdir -p /tmp/ab-fusion
  docker cp "${PACK_ROOT}/p5/vector_runtime.py" "${BACKEND_CONTAINER}:/tmp/ab-fusion/vector_runtime.py"
}

stage_a() {
  fusion_ssh_a mkdir -p /tmp/ab-fusion
  fusion_scp_to_a "${PACK_ROOT}/p5/vector_runtime.py" /tmp/ab-fusion/vector_runtime.py
  fusion_ssh_a docker exec "${A_BACKEND_CONTAINER}" mkdir -p /tmp/ab-fusion
  fusion_ssh_a docker cp /tmp/ab-fusion/vector_runtime.py "${A_BACKEND_CONTAINER}:/tmp/ab-fusion/vector_runtime.py"
}

runtime_b() {
  docker exec -i "${BACKEND_CONTAINER}" python /tmp/ab-fusion/vector_runtime.py "$@" </dev/null
}

runtime_a() {
  fusion_ssh_a docker exec -i "${A_BACKEND_CONTAINER}" python /tmp/ab-fusion/vector_runtime.py "$@" </dev/null
}

if [[ "${ACTION}" == "drop" ]]; then
  created="${LOG_DIR}/p5/vector-created.tsv"
  [[ -f "${created}" ]] || die "缺少 ${created}, 没有本批创建记录可删"
  if [[ "${APPLY}" != "1" ]]; then
    log "APPLY=0, 将按 ${created} 删除本批 Collection/Index"
    ledger "${STEP}" "OK" "APPLY=0 drop preview"
    echo "OK ${STEP} APPLY=0 drop preview"
    exit 0
  fi
  [[ -n "${A_BACKEND_CONTAINER}" ]] || die "drop 需要 A_BACKEND_CONTAINER"
  stage_a
  fusion_scp_to_a "${forbid}" /tmp/ab-fusion/forbid.txt
  fusion_ssh_a docker cp /tmp/ab-fusion/forbid.txt "${A_BACKEND_CONTAINER}:/tmp/ab-fusion/forbid.txt"
  while IFS=$'\t' read -r kind name _ <&3; do
    [[ "${kind}" == "kind" || -z "${kind}" ]] && continue
    if [[ "${kind}" == "milvus" ]]; then
      runtime_a drop-milvus --collection "${name}" --forbid-file /tmp/ab-fusion/forbid.txt
    else
      runtime_a drop-es --index "${name}" --forbid-file /tmp/ab-fusion/forbid.txt
    fi
  done 3< "${created}"
  ledger "${STEP}" "OK" "APPLY=1 dropped"
  echo "OK ${STEP} dropped"
  exit 0
fi

described=0
b_desc="${LOG_DIR}/p5/b-vector-describe.json"
a_desc="${LOG_DIR}/p5/a-vector-describe.json"
if [[ -n "${BACKEND_CONTAINER}" && -n "${A_BACKEND_CONTAINER}" ]]; then
  stage_b
  stage_a
  runtime_b describe --out /tmp/ab-fusion/b-desc.json
  docker cp "${BACKEND_CONTAINER}:/tmp/ab-fusion/b-desc.json" "${b_desc}"
  runtime_a describe --out /tmp/ab-fusion/a-desc.json
  fusion_ssh_a docker cp "${A_BACKEND_CONTAINER}:/tmp/ab-fusion/a-desc.json" /tmp/ab-fusion/a-desc.json
  fusion_scp_from_a /tmp/ab-fusion/a-desc.json "${a_desc}"
  described=1
else
  if [[ "${APPLY}" == "1" && "${ACTION}" == "copy" ]]; then
    die "未发现 backend 容器, APPLY=1 无法迁 Milvus/ES. export BACKEND_CONTAINER / A_BACKEND_CONTAINER"
  fi
  log "未发现 backend 容器, 只出门禁 pending. B=${BACKEND_CONTAINER:-?} A=${A_BACKEND_CONTAINER:-?}"
  echo '{"collections":{},"indices":{}}' > "${b_desc}"
  echo '{"collections":{},"indices":{}}' > "${a_desc}"
fi

desc_flags=()
if [[ "${described}" == "1" ]]; then
  desc_flags=(--described)
fi
python3 "${PACK_ROOT}/p5/build_vector_jobs.py" \
  --dump "${dump}" \
  --maps "${maps}" \
  --out-dir "${LOG_DIR}/p5" \
  --batch "${BATCH_NO}" \
  --b-describe "${b_desc}" \
  --a-describe "${a_desc}" \
  --a-space-stores "${LOG_DIR}/p5/a-space-stores.tsv" \
  --a-knowledge-stores "${LOG_DIR}/p5/a-knowledge-stores.tsv" \
  --b-models "${LOG_DIR}/p5/b-llm-models.jsonl" \
  --a-models "${LOG_DIR}/p5/a-llm-models.jsonl" \
  "${desc_flags[@]}"

jobs="${LOG_DIR}/p5/vector-jobs.tsv"
exc="${LOG_DIR}/p5/vector-exceptions.tsv"
job_n=0
exc_n=0
pending_n=0
if [[ -f "${jobs}" ]]; then
  job_n="$(awk 'NR>1 && $0!="" {c++} END{print c+0}' "${jobs}")"
fi
if [[ -f "${exc}" ]]; then
  exc_n="$(awk 'NR>1 && $0!="" {c++} END{print c+0}' "${exc}")"
  pending_n="$(awk -F'\t' 'NR>1 && $5=="pending" {c++} END{print c+0}' "${exc}")"
fi
log "vector jobs=${job_n} exceptions=${exc_n} pending=${pending_n} action=${ACTION} APPLY=${APPLY}"

if [[ "${APPLY}" != "1" ]]; then
  ledger "${STEP}" "OK" "APPLY=0 jobs=${job_n} exceptions=${exc_n}"
  echo "OK ${STEP} APPLY=0 jobs=${job_n} exceptions=${exc_n} pending=${pending_n}"
  echo "例外清单 ${exc}; 不自动重解析. APPLY=1 才写入 A Milvus/ES"
  exit 0
fi

if [[ "${pending_n}" != "0" ]]; then
  die "还有 ${pending_n} 条 pending describe, 禁止 APPLY"
fi

require_a_25_for_apply
require_b_25_for_apply
[[ -n "${BACKEND_CONTAINER}" && -n "${A_BACKEND_CONTAINER}" ]] || die "APPLY=1 需要两侧 backend 容器"
stage_b
stage_a
fusion_scp_to_a "${forbid}" /tmp/ab-fusion/forbid.txt
fusion_ssh_a docker cp /tmp/ab-fusion/forbid.txt "${A_BACKEND_CONTAINER}:/tmp/ab-fusion/forbid.txt"

created="${LOG_DIR}/p5/vector-created.tsv"
printf 'kind\tname\tb_id\n' > "${created}"
work="${LOG_DIR}/p5/vector-work"
mkdir -p "${work}"

extract_json() {
  python3 - "$1" "$2" "$3" "$4" <<'PY'
import json, sys
from pathlib import Path
data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
bucket, name, dest = sys.argv[2], sys.argv[3], Path(sys.argv[4])
payload = (data.get(bucket) or {}).get(name) or {}
dest.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
if not payload:
    raise SystemExit(f"missing {bucket} {name}")
PY
}

copy_one() {
  local b_id="$1" a_coll="$2" b_coll="$3" a_idx="$4" b_idx="$5" expr="$6" ktype="$7"
  local schema="${work}/${b_id}.milvus-schema.json"
  local mapping="${work}/${b_id}.es-mapping.json"
  local raw_m="${work}/${b_id}.milvus.jsonl"
  local rew_m="${work}/${b_id}.milvus.rewritten.jsonl"
  local raw_e="${work}/${b_id}.es.jsonl"
  local rew_e="${work}/${b_id}.es.rewritten.jsonl"
  local missing_file="error"
  if [[ "${ktype}" == "1" ]]; then
    missing_file="drop_field"
  fi
  extract_json "${b_desc}" collections "${b_coll}" "${schema}"
  extract_json "${b_desc}" indices "${b_idx}" "${mapping}" || extract_json "${b_desc}" indices "${b_coll}" "${mapping}"

  runtime_b export-milvus --collection "${b_coll}" --expr "${expr}" --out "/tmp/ab-fusion/${b_id}.m.jsonl"
  docker cp "${BACKEND_CONTAINER}:/tmp/ab-fusion/${b_id}.m.jsonl" "${raw_m}"
  python3 "${PACK_ROOT}/p5/rewrite_vector_jsonl.py" --src "${raw_m}" --dst "${rew_m}" --maps "${maps}" --schema "${schema}" --missing-file "${missing_file}"
  fusion_scp_to_a "${rew_m}" "/tmp/ab-fusion/${b_id}.m.jsonl"
  fusion_scp_to_a "${schema}" "/tmp/ab-fusion/${b_id}.schema.json"
  fusion_ssh_a docker cp "/tmp/ab-fusion/${b_id}.m.jsonl" "${A_BACKEND_CONTAINER}:/tmp/ab-fusion/${b_id}.m.jsonl"
  fusion_ssh_a docker cp "/tmp/ab-fusion/${b_id}.schema.json" "${A_BACKEND_CONTAINER}:/tmp/ab-fusion/${b_id}.schema.json"
  runtime_a import-milvus --collection "${a_coll}" --schema "/tmp/ab-fusion/${b_id}.schema.json" \
    --src "/tmp/ab-fusion/${b_id}.m.jsonl" --forbid-file /tmp/ab-fusion/forbid.txt
  printf 'milvus\t%s\t%s\n' "${a_coll}" "${b_id}" >> "${created}"

  local es_query=""
  if [[ -n "${expr}" ]]; then
    es_query="$(python3 - "${b_id}" <<'PY'
import json, sys
kid = sys.argv[1]
val = int(kid) if kid.isdigit() else kid
print(json.dumps({
    "bool": {
        "should": [
            {"term": {"metadata.knowledge_id": val}},
            {"term": {"metadata.knowledge_id": kid}},
        ],
        "minimum_should_match": 1,
    }
}))
PY
)"
    runtime_b export-es --index "${b_idx}" --query "${es_query}" --out "/tmp/ab-fusion/${b_id}.e.jsonl"
  else
    runtime_b export-es --index "${b_idx}" --out "/tmp/ab-fusion/${b_id}.e.jsonl"
  fi
  docker cp "${BACKEND_CONTAINER}:/tmp/ab-fusion/${b_id}.e.jsonl" "${raw_e}"
  python3 "${PACK_ROOT}/p5/rewrite_vector_jsonl.py" --src "${raw_e}" --dst "${rew_e}" --maps "${maps}" --schema "${schema}" --missing-file "${missing_file}"
  fusion_scp_to_a "${rew_e}" "/tmp/ab-fusion/${b_id}.e.jsonl"
  fusion_scp_to_a "${mapping}" "/tmp/ab-fusion/${b_id}.mapping.json"
  fusion_ssh_a docker cp "/tmp/ab-fusion/${b_id}.e.jsonl" "${A_BACKEND_CONTAINER}:/tmp/ab-fusion/${b_id}.e.jsonl"
  fusion_ssh_a docker cp "/tmp/ab-fusion/${b_id}.mapping.json" "${A_BACKEND_CONTAINER}:/tmp/ab-fusion/${b_id}.mapping.json"
  if ! runtime_a import-es --index "${a_idx}" --mapping "/tmp/ab-fusion/${b_id}.mapping.json" \
    --src "/tmp/ab-fusion/${b_id}.e.jsonl" --forbid-file /tmp/ab-fusion/forbid.txt; then
    runtime_a drop-milvus --collection "${a_coll}" --forbid-file /tmp/ab-fusion/forbid.txt || true
    die "ES 导入失败, 已尝试删除 ${a_coll}"
  fi
  printf 'es\t%s\t%s\n' "${a_idx}" "${b_id}" >> "${created}"
}

csv_unescape() {
  python3 -c 'import csv,io,sys
s=sys.argv[1] if len(sys.argv)>1 else ""
print(next(csv.reader(io.StringIO(s), delimiter="\t"), [""])[0] if s else "")
' "$1"
}

copied=0
skipped=0
while IFS=$'\t' read -r b_id a_id type verdict b_collection a_collection b_index a_index expr conversions reason <&3; do
  [[ "${b_id}" == "b_id" || -z "${b_id}" ]] && continue
  if [[ "${verdict}" == "skip" ]]; then
    log "skip knowledge ${b_id} -> ${a_id} already on A ${a_collection}"
    skipped=$((skipped + 1))
    continue
  fi
  [[ "${verdict}" == "copy" || "${verdict}" == "convert" ]] || continue
  expr="$(csv_unescape "${expr}")"
  log "copy knowledge ${b_id} -> ${a_id} ${b_collection} => ${a_collection} expr=${expr}"
  copy_one "${b_id}" "${a_collection}" "${b_collection}" "${a_index}" "${b_index}" "${expr}" "${type}"
  copied=$((copied + 1))
done 3< "${jobs}"

if [[ -s "${LOG_DIR}/p5/vector-exceptions.sql" ]]; then
  apply_sql_on_a "${LOG_DIR}/p5/vector-exceptions.sql"
fi

ledger "${STEP}" "OK" "APPLY=1 copied=${copied} skipped=${skipped} exceptions=${exc_n}"
echo "OK ${STEP} copied=${copied} skipped=${skipped} exceptions=${exc_n}"
