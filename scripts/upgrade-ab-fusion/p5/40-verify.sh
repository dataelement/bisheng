#!/usr/bin/env bash
# 核对 A 原空间计数未下降, 且本批映射条数对得上 B 基线.
set -euo pipefail
STEP="p5.40-verify"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
# shellcheck disable=SC1091
source "${PACK_ROOT}/lib/fusion_remote.sh"

base="${LOG_DIR}/p5/a-baseline.tsv"
[[ -f "${base}" ]] || die "缺少 ${base}, 先跑 p5/00-protect-a-baseline.sh"
[[ -f "${LOG_DIR}/p5/dump.json" ]] || die "缺少 dump.json, 先跑 p5/30-apply.sh"

expect_space="$(awk -F'\t' '$1=="a_space_cnt"{print $2}' "${base}" | tr -d '[:space:]')"
now_space="$(mysql_a "SELECT COUNT(*) FROM knowledge WHERE type=3" | tr -d '[:space:]')"
[[ "${now_space}" -ge "${expect_space}" ]] || die "A 空间数从 ${expect_space} 变成 ${now_space}"

expect_file="$(awk -F'\t' '$1=="a_space_file_cnt"{print $2}' "${base}" | tr -d '[:space:]')"
now_file="$(mysql_a "SELECT COUNT(*) FROM knowledgefile f JOIN knowledge k ON f.knowledge_id=k.id WHERE k.type=3" | tr -d '[:space:]')"
[[ "${now_file}" -ge "${expect_file}" ]] || die "A 空间文件数从 ${expect_file} 变成 ${now_file}"

{
  echo "metric	value"
  echo "a_space_cnt	${now_space}"
  echo "a_space_file_cnt	${now_file}"
} > "${LOG_DIR}/p5/a-now.tsv"

python3 "${PACK_ROOT}/fusion/cli.py" verify-counts \
  --dump "${LOG_DIR}/p5/dump.json" \
  --maps "${LOG_DIR}/p4/maps" \
  --a-baseline "${base}" \
  --a-now "${LOG_DIR}/p5/a-now.tsv" \
  --out "${LOG_DIR}/p5/verify-counts.json"

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
ledger "${STEP}" "OK" "space ${now_space} files ${now_file}"
echo "OK ${STEP}"
