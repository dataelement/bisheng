#!/usr/bin/env bash
# F028 — Conversation export dependency smoke test.
# Run inside the bisheng-backend container:
#   docker exec -it bisheng-backend bash scripts/check_export_dependencies.sh
#
# Validates pandoc / LibreOffice (soffice) / Chinese fonts and runs an
# end-to-end md -> docx -> pdf round-trip to make sure the rendering toolchain
# is actually wired up. Exits non-zero on any missing or broken piece.

set -u

GREEN="\033[0;32m"
RED="\033[0;31m"
YELLOW="\033[1;33m"
NC="\033[0m"

pass() { echo -e "${GREEN}[PASS]${NC} $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }

EXIT_CODE=0

echo "=== F028 export dependencies smoke test ==="
echo

# --- pandoc ---
if command -v pandoc >/dev/null 2>&1; then
  PANDOC_VERSION=$(pandoc --version | head -1)
  pass "pandoc available: ${PANDOC_VERSION}"
else
  fail "pandoc NOT found (expected /usr/bin/pandoc, installed by base.Dockerfile line 22-27)"
  EXIT_CODE=1
fi

# --- LibreOffice (soffice) ---
if command -v soffice >/dev/null 2>&1; then
  SOFFICE_VERSION=$(soffice --version 2>&1 | head -1)
  pass "soffice available: ${SOFFICE_VERSION}"
elif command -v libreoffice >/dev/null 2>&1; then
  SOFFICE_VERSION=$(libreoffice --version 2>&1 | head -1)
  pass "libreoffice available: ${SOFFICE_VERSION}"
else
  fail "soffice/libreoffice NOT found (expected from base.Dockerfile line 12 apt install)"
  EXIT_CODE=1
fi

# --- Chinese fonts ---
if command -v fc-list >/dev/null 2>&1; then
  ZH_FONT_COUNT=$(fc-list :lang=zh 2>/dev/null | wc -l)
  if [ "${ZH_FONT_COUNT}" -gt 0 ]; then
    pass "Chinese fonts: ${ZH_FONT_COUNT} family/style entries detected"
    fc-list :lang=zh | head -5 | sed 's/^/       /'
  else
    fail "fc-list returned 0 Chinese fonts (expected fonts-wqy-zenhei from base.Dockerfile line 13)"
    EXIT_CODE=1
  fi
else
  warn "fc-list not available; skipping Chinese font check"
fi

# --- End-to-end round-trip: md -> docx -> pdf ---
echo
echo "--- End-to-end md -> docx -> pdf round-trip ---"
TMP=$(mktemp -d)
trap 'rm -rf "${TMP}"' EXIT

cat > "${TMP}/sample.md" <<'EOF'
**Admin:**

今天天气 (today weather)

---

**DeepSeek v3.2:**

# 1. 经济因素

通货膨胀与货币政策:黄金常被视为对冲通胀的工具。

| 列 A | 列 B |
| --- | --- |
| 1 | 测试中文 |

```python
def hello():
    print("中文 mixed with English")
```
EOF

if pandoc -f markdown -t docx -o "${TMP}/sample.docx" "${TMP}/sample.md" 2>"${TMP}/pandoc.err"; then
  DOCX_SIZE=$(wc -c < "${TMP}/sample.docx")
  pass "pandoc md -> docx OK (${DOCX_SIZE} bytes)"
else
  fail "pandoc md -> docx FAILED:"
  cat "${TMP}/pandoc.err" | sed 's/^/       /'
  EXIT_CODE=1
fi

if [ -f "${TMP}/sample.docx" ]; then
  SOFFICE_BIN=$(command -v soffice || command -v libreoffice)
  if [ -n "${SOFFICE_BIN}" ]; then
    if "${SOFFICE_BIN}" --headless --convert-to pdf --outdir "${TMP}" "${TMP}/sample.docx" >"${TMP}/soffice.log" 2>&1; then
      if [ -f "${TMP}/sample.pdf" ]; then
        PDF_SIZE=$(wc -c < "${TMP}/sample.pdf")
        HEAD=$(head -c 4 "${TMP}/sample.pdf")
        if [ "${HEAD}" = "%PDF" ]; then
          pass "soffice docx -> pdf OK (${PDF_SIZE} bytes, header %PDF)"
        else
          fail "soffice produced a file but it does not start with %PDF magic"
          EXIT_CODE=1
        fi
      else
        fail "soffice docx -> pdf produced no output file"
        cat "${TMP}/soffice.log" | sed 's/^/       /'
        EXIT_CODE=1
      fi
    else
      fail "soffice docx -> pdf FAILED:"
      cat "${TMP}/soffice.log" | sed 's/^/       /'
      EXIT_CODE=1
    fi
  fi
fi

echo
if [ ${EXIT_CODE} -eq 0 ]; then
  echo -e "${GREEN}=== ALL CHECKS PASSED — F028 export toolchain is ready ===${NC}"
else
  echo -e "${RED}=== ONE OR MORE CHECKS FAILED — see [FAIL] lines above ===${NC}"
fi

exit ${EXIT_CODE}
