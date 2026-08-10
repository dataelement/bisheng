#!/usr/bin/env bash
# Package a Linsight skill bundle into an importable .zip.
#
#   bash scripts/pack_linsight_skill.sh linsight-skills/bisheng-pptx [outdir]
#
# Validates the constraints the backend enforces on import (SKILL.md at the
# archive root, kebab-case name matching the directory, size caps) so failures
# surface here rather than as an 11051/11052/11059 error in the admin UI.

set -euo pipefail

SRC="${1:-}"
OUT_DIR="${2:-dist}"

if [ -z "${SRC}" ]; then
  echo "usage: bash scripts/pack_linsight_skill.sh <skill-dir> [outdir]" >&2
  exit 2
fi

SRC="${SRC%/}"
NAME="$(basename "${SRC}")"

if [ ! -f "${SRC}/SKILL.md" ]; then
  echo "[FAIL] ${SRC}/SKILL.md not found — SKILL.md must sit at the bundle root" >&2
  exit 1
fi

# frontmatter name must equal the directory name (deepagents resolves skills by path)
FM_NAME="$(awk '/^---[[:space:]]*$/{n++; next} n==1 && /^name:/{sub(/^name:[[:space:]]*/, ""); gsub(/["\r]/, ""); print; exit}' "${SRC}/SKILL.md")"
if [ -z "${FM_NAME}" ]; then
  echo "[FAIL] SKILL.md frontmatter has no 'name'" >&2
  exit 1
fi
if [ "${FM_NAME}" != "${NAME}" ]; then
  echo "[FAIL] frontmatter name '${FM_NAME}' != directory name '${NAME}'" >&2
  exit 1
fi
if ! printf '%s' "${NAME}" | grep -Eq '^[a-z0-9]+(-[a-z0-9]+)*$'; then
  echo "[FAIL] '${NAME}' is not kebab-case; import would silently rewrite it" >&2
  exit 1
fi

mkdir -p "${OUT_DIR}"
ZIP_PATH="${OUT_DIR}/${NAME}.zip"
rm -f "${ZIP_PATH}"

ABS_ZIP="$(cd "${OUT_DIR}" && pwd)/${NAME}.zip"
(
  cd "${SRC}"
  zip -Xrq "${ABS_ZIP}" . \
    -x '*/__pycache__/*' '__pycache__/*' '*.pyc' '.DS_Store' '*/.DS_Store'
)

ZIP_BYTES=$(wc -c < "${ZIP_PATH}" | tr -d ' ')
RAW_BYTES=$(find "${SRC}" -type f -not -path '*/__pycache__/*' -not -name '*.pyc' -not -name '.DS_Store' -exec wc -c {} + | tail -1 | awk '{print $1}')
FILE_COUNT=$(find "${SRC}" -type f -not -path '*/__pycache__/*' -not -name '*.pyc' -not -name '.DS_Store' | wc -l | tr -d ' ')

MAX_ZIP=$((10 * 1024 * 1024))
MAX_RAW=$((100 * 1024 * 1024))

printf '%s\n' "[OK] ${ZIP_PATH}"
printf '     name        : %s\n' "${NAME}"
printf '     files       : %s\n' "${FILE_COUNT}"
printf '     zip size    : %s bytes (limit %s)\n' "${ZIP_BYTES}" "${MAX_ZIP}"
printf '     unpacked    : %s bytes (limit %s)\n' "${RAW_BYTES}" "${MAX_RAW}"

STATUS=0
if [ "${ZIP_BYTES}" -gt "${MAX_ZIP}" ]; then
  echo "[FAIL] zip exceeds the 10MB upload cap (error 11052)" >&2
  STATUS=1
fi
if [ "${RAW_BYTES}" -gt "${MAX_RAW}" ]; then
  echo "[FAIL] unpacked bundle exceeds the 100MB cap (error 11059)" >&2
  STATUS=1
fi

if [ "${STATUS}" -eq 0 ]; then
  echo "     导入方式: 管理端 → 灵思 → 技能 → 上传，选择上面的 zip（需要租户管理员权限）"
fi
exit "${STATUS}"
