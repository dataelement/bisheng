#!/usr/bin/env bash
# B -> A 融合编排. 默认 APPLY=0, 只导出/生成 SQL/dry-run, 不写 A.
# 不迁: Redis/JWT/分享签名密钥, A 原 knowledge.type=3 不做 UPDATE/DELETE,
#       B 的 type=3 默认跳过 (MIGRATE_B_SPACES=0), 积分/遥测不迁, 审计迁.
# APPLY=1 还要 CONFIRM_FULL_MIGRATE=1.
set -euo pipefail
STEP="full-migrate"
APPLY="${APPLY:-0}"
CONFIRM_FULL_MIGRATE="${CONFIRM_FULL_MIGRATE:-0}"
STAGE="all"

usage() {
  cat <<'EOF'
用法:
  bash full-migrate.sh
  bash full-migrate.sh --stage identity-export
  APPLY=0 bash full-migrate.sh
  APPLY=1 CONFIRM_FULL_MIGRATE=1 bash full-migrate.sh

阶段:
  control -> a-baseline -> identity-export -> identity-propose
  -> identity-apply -> business-export -> business-apply
  -> minio -> vectors -> openfga -> verify

可选 (不要靠 all 自动跑):
  retrieve-gold / incr / publish
  首次 business-export 会 LABEL=start 抓水位

在 B 源机上跑: 本地 docker mysql 是 B, A 走 SSH.
前置: 终端里会问 A 的地址/账号/端口 (写入 env.sh); 密码只进当前窗口, 不写文件.
已填过则回显确认. 无人值守: SKIP_A_SSH_PROMPT=1 且已有 env.sh + SSHPASS/密钥.
EOF
}

# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")" && pwd)/lib/common.sh"
load_env
# shellcheck disable=SC1091
source "${PACK_ROOT}/lib/fusion_remote.sh"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --stage) STAGE="$2"; shift 2 ;;
    *) die "未知参数 $1" ;;
  esac
done

if [[ "${APPLY}" == "1" && "${CONFIRM_FULL_MIGRATE}" != "1" ]]; then
  die "全迁 APPLY=1 需要 CONFIRM_FULL_MIGRATE=1"
fi

prompt_a_ssh_target
resolve_batch_no
export APPLY BATCH_NO
mkdir -p "${LOG_DIR}/p4" "${LOG_DIR}/p5"
ledger "${STEP}" "START" "APPLY=${APPLY} stage=${STAGE} batch=${BATCH_NO}"

run_stage() {
  local name="$1"
  shift
  log "---- ${name} ----"
  "$@"
}

want() {
  [[ "${STAGE}" == "all" || "${STAGE}" == "$1" ]]
}

if want control; then
  run_stage control bash "${PACK_ROOT}/p4/00-install-control.sh"
fi
if want a-baseline; then
  run_stage a-baseline bash "${PACK_ROOT}/p5/00-protect-a-baseline.sh"
fi
if want identity-export; then
  run_stage identity-export bash "${PACK_ROOT}/p4/01-export-identity.sh"
fi
if want identity-propose; then
  run_stage identity-propose bash "${PACK_ROOT}/p4/02-propose-maps.sh"
fi
if want identity-apply; then
  run_stage identity-apply bash "${PACK_ROOT}/p4/10-apply-identity.sh"
fi
if want business-export; then
  if [[ ! -f "${LOG_DIR}/p6/start/summary.tsv" ]]; then
    LABEL=start bash "${PACK_ROOT}/p6/10-capture-watermark.sh"
  fi
  run_stage business-export bash "${PACK_ROOT}/p5/10-export-b-business.sh"
fi
if want business-apply; then
  run_stage business-apply bash "${PACK_ROOT}/p5/30-apply.sh"
fi
if want minio; then
  run_stage minio bash "${PACK_ROOT}/p5/20-copy-minio.sh"
fi
if want vectors; then
  run_stage vectors bash "${PACK_ROOT}/p5/22-copy-vectors.sh"
fi
if want openfga; then
  run_stage openfga bash "${PACK_ROOT}/p5/35-apply-openfga.sh"
fi
if want verify; then
  if [[ "${APPLY}" == "1" ]]; then
    VERIFY_STORAGE=1 run_stage verify bash "${PACK_ROOT}/p5/40-verify.sh"
  else
    run_stage verify bash "${PACK_ROOT}/p5/40-verify.sh"
  fi
fi
if [[ "${STAGE}" == "retrieve-gold" ]]; then
  run_stage retrieve-gold bash "${PACK_ROOT}/p5/50-retrieve-gold.sh"
fi
if [[ "${STAGE}" == "incr" ]]; then
  run_stage incr bash "${PACK_ROOT}/p6/30-apply-incr.sh"
fi
if [[ "${STAGE}" == "publish" ]]; then
  run_stage publish bash "${PACK_ROOT}/p5/36-publish-flows.sh"
fi

ledger "${STEP}" "OK" "stage=${STAGE}"
echo "OK ${STEP}"
