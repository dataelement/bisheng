#!/usr/bin/env bash
# 核对本批映射、A 原空间元数据、原会话仍在、悬挂 FK.
# VERIFY_STORAGE=1 时再查 MinIO 抽样和检索金标 (APPLY=1 拷完后才开).
set -euo pipefail
STEP="p5.40-verify"
VERIFY_STORAGE="${VERIFY_STORAGE:-0}"
MINIO_SAMPLE="${MINIO_SAMPLE:-5}"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
# shellcheck disable=SC1091
source "${PACK_ROOT}/lib/fusion_remote.sh"
BATCH_NO="${BATCH_NO:-fusion-$(date +%Y%m%d)}"

base="${LOG_DIR}/p5/a-baseline.tsv"
[[ -f "${base}" ]] || die "缺少 ${base}, 先跑 p5/00-protect-a-baseline.sh"
[[ -f "${LOG_DIR}/p5/dump.json" ]] || die "缺少 dump.json, 先跑 p5/30-apply.sh"
[[ -f "${LOG_DIR}/p5/a-space-meta.tsv" ]] || die "缺少 a-space-meta.tsv, 重新跑 p5/00-protect-a-baseline.sh"

expect_space="$(awk -F'\t' '$1=="a_space_cnt"{print $2}' "${base}" | tr -d '[:space:]')"
now_space="$(mysql_a "SELECT COUNT(*) FROM knowledge WHERE type=3" | tr -d '[:space:]')"
[[ "${now_space}" -ge "${expect_space}" ]] || die "A 空间数从 ${expect_space} 变成 ${now_space}"

expect_file="$(awk -F'\t' '$1=="a_space_file_cnt"{print $2}' "${base}" | tr -d '[:space:]')"
now_file="$(mysql_a "SELECT COUNT(*) FROM knowledgefile f JOIN knowledge k ON f.knowledge_id=k.id WHERE k.type=3" | tr -d '[:space:]')"
[[ "${now_file}" -ge "${expect_file}" ]] || die "A 空间文件数从 ${expect_file} 变成 ${now_file}"

expect_session="$(awk -F'\t' '$1=="a_session_cnt"{print $2}' "${base}" | tr -d '[:space:]')"
now_session="$(mysql_a "SELECT COUNT(*) FROM message_session" | tr -d '[:space:]')"
[[ "${now_session}" -ge "${expect_session}" ]] || die "A 会话数从 ${expect_session} 变成 ${now_session}"

expect_message="$(awk -F'\t' '$1=="a_message_cnt"{print $2}' "${base}" | tr -d '[:space:]')"
now_message="$(mysql_a "SELECT COUNT(*) FROM chatmessage" | tr -d '[:space:]')"
[[ "${now_message}" -ge "${expect_message}" ]] || die "A 消息数从 ${expect_message} 变成 ${now_message}"

{
  echo "metric	value"
  echo "a_space_cnt	${now_space}"
  echo "a_space_file_cnt	${now_file}"
  echo "a_session_cnt	${now_session}"
  echo "a_message_cnt	${now_message}"
} > "${LOG_DIR}/p5/a-now.tsv"

mysql_a_tsv "SELECT id,name,description,user_id,tenant_id,DATE_FORMAT(update_time,'%Y-%m-%d %H:%i:%s') AS update_time FROM knowledge WHERE type=3 ORDER BY id" \
  > "${LOG_DIR}/p5/a-space-meta-now.tsv"
mysql_a_tsv "SELECT f.id FROM knowledgefile f JOIN knowledge k ON f.knowledge_id=k.id WHERE k.type=3 ORDER BY f.id" \
  > "${LOG_DIR}/p5/a-space-file-ids-now.tsv"
mysql_a_tsv "SELECT chat_id FROM message_session" \
  > "${LOG_DIR}/p5/a-chat-ids-now.tsv"

python3 - "${PACK_ROOT}" "${LOG_DIR}/p5" <<'PY'
import sys
from pathlib import Path

pack, log = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, str(pack))
from fusion.sql import load_table
from fusion.verify_accept import compare_space_meta, ids_from_tsv, missing_ids

errs = compare_space_meta(
    load_table(log / "a-space-meta.tsv"),
    load_table(log / "a-space-meta-now.tsv"),
)
miss_files = missing_ids(
    ids_from_tsv(log / "a-space-file-ids.tsv", "id"),
    ids_from_tsv(log / "a-space-file-ids-now.tsv", "id"),
)
if miss_files:
    errs.append("A 空间文件 id 消失: " + ",".join(miss_files[:20]))
miss_chats = missing_ids(
    ids_from_tsv(log / "a-pre-chat-ids.tsv", "chat_id"),
    ids_from_tsv(log / "a-chat-ids-now.tsv", "chat_id"),
)
if miss_chats:
    errs.append("A 原会话 chat_id 消失: " + ",".join(miss_chats[:20]))
if errs:
    print("\n".join(errs), file=sys.stderr)
    sys.exit(2)
print("A 原空间元数据/文件/会话 id 仍在")
PY

python3 "${PACK_ROOT}/fusion/cli.py" verify-counts \
  --dump "${LOG_DIR}/p5/dump.json" \
  --maps "${LOG_DIR}/p4/maps" \
  --a-baseline "${base}" \
  --a-now "${LOG_DIR}/p5/a-now.tsv" \
  --out "${LOG_DIR}/p5/verify-counts.json"

while IFS=$'\t' read -r name sql; do
  [[ -n "${name}" ]] || continue
  cnt="$(mysql_a "${sql}" | tr -d '[:space:]')"
  log "dangling ${name}=${cnt}"
  [[ "${cnt}" == "0" ]] || die "悬挂引用 ${name} count=${cnt}"
done < <(python3 - "${PACK_ROOT}" "${BATCH_NO}" <<'PY'
import sys
from pathlib import Path
pack, batch = Path(sys.argv[1]), sys.argv[2]
sys.path.insert(0, str(pack))
from fusion.verify_accept import dangling_checks
for name, sql in dangling_checks(batch or None):
    print(f"{name}\t{sql}")
PY
)

maps="$(mysql_a "SELECT COUNT(*) FROM fusion_map" || echo 0)"
echo "fusion_map rows=${maps}"
echo "A space ${expect_space} -> ${now_space} (must not drop)"
if [[ -f "${LOG_DIR}/p5/gaps-model-tool.tsv" ]]; then
  echo "model/tool gaps:"
  cat "${LOG_DIR}/p5/gaps-model-tool.tsv"
fi
if [[ -f "${LOG_DIR}/p5/vector-exceptions.tsv" ]]; then
  echo "vector exceptions (need_reparse, not auto):"
  cat "${LOG_DIR}/p5/vector-exceptions.tsv"
fi
if [[ -f "${LOG_DIR}/p5/exceptions-session-groups.tsv" ]]; then
  echo "session group_ids dropped:"
  cat "${LOG_DIR}/p5/exceptions-session-groups.tsv"
fi
if [[ -f "${LOG_DIR}/p5/gaps-assistant-links.tsv" ]]; then
  echo "assistantlink skipped:"
  cat "${LOG_DIR}/p5/gaps-assistant-links.tsv"
fi

if [[ "${VERIFY_STORAGE}" == "1" ]]; then
  jobs="${LOG_DIR}/p5/minio-jobs.tsv"
  if [[ -f "${jobs}" ]]; then
    : "${A_MINIO_BUCKET:=bisheng}"
    : "${IMAGE_MC:=minio/mc:RELEASE.2024-11-21T17-21-54Z}"
    if [[ -z "${A_MINIO_CONTAINER:-}" ]]; then
      names="$(fusion_ssh_a docker ps --format '{{.Names}}')"
      A_MINIO_CONTAINER="$(printf '%s\n' "${names}" | grep -i minio | grep -vi milvus | head -1 || true)"
      [[ -n "${A_MINIO_CONTAINER}" ]] || A_MINIO_CONTAINER="$(printf '%s\n' "${names}" | grep -i minio | head -1 || true)"
    fi
    [[ -n "${A_MINIO_CONTAINER}" ]] || die "VERIFY_STORAGE=1 需要 A_MINIO_CONTAINER"
    a_user="$(fusion_ssh_a docker exec "${A_MINIO_CONTAINER}" printenv MINIO_ROOT_USER 2>/dev/null || true)"
    [[ -n "${a_user}" ]] || a_user="$(fusion_ssh_a docker exec "${A_MINIO_CONTAINER}" printenv MINIO_ACCESS_KEY 2>/dev/null || true)"
    a_pass="$(fusion_ssh_a docker exec "${A_MINIO_CONTAINER}" printenv MINIO_ROOT_PASSWORD 2>/dev/null || true)"
    [[ -n "${a_pass}" ]] || a_pass="$(fusion_ssh_a docker exec "${A_MINIO_CONTAINER}" printenv MINIO_SECRET_KEY 2>/dev/null || true)"
    [[ -n "${a_user}" && -n "${a_pass}" ]] || die "读不到 A MinIO 账号"
    sampled=0
    while IFS=$'\t' read -r dst <&3; do
      [[ -n "${dst}" ]] || continue
      sampled=$((sampled + 1))
      fusion_ssh_a docker run --rm --network "container:${A_MINIO_CONTAINER}" \
        -e "MC_HOST_dst=http://${a_user}:${a_pass}@127.0.0.1:9000" \
        "${IMAGE_MC}" stat "dst/${A_MINIO_BUCKET}/${dst}" >/dev/null </dev/null \
        || die "A MinIO 缺少对象 ${dst}"
    done 3< <(python3 - "${jobs}" "${MINIO_SAMPLE}" <<'PY'
import sys
from pathlib import Path
path, n = Path(sys.argv[1]), int(sys.argv[2])
rows = []
for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
    if i == 0 or not line.strip():
        continue
    parts = line.split("\t")
    if len(parts) >= 3 and parts[2]:
        rows.append(parts[2])
    if len(rows) >= n:
        break
print("\n".join(rows))
PY
)
    log "MinIO sampled=${sampled}"
  fi
  vjobs="${LOG_DIR}/p5/vector-jobs.tsv"
  [[ -f "${vjobs}" ]] || die "VERIFY_STORAGE=1 缺少 ${vjobs}, 先跑 p5/22-copy-vectors.sh"
  if grep -E $'\t(copy|convert|skip)\t' "${vjobs}" >/dev/null; then
    GOLD_ALLOW_FAIL=0 bash "${PACK_ROOT}/p5/50-retrieve-gold.sh"
  else
    log "vector-jobs 无 copy/convert, 跳过金标"
  fi
fi

ledger "${STEP}" "OK" "space ${now_space} files ${now_file} storage=${VERIFY_STORAGE}"
echo "OK ${STEP}"
