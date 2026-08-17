#!/usr/bin/env bash
# Build the bisheng-cli wheel and stage it for the platform's download endpoint.
#
#   bash scripts/pack_cli_wheel.sh
#
# RELEASE CONTRACT — read this before changing anything below.
#
#   Changing the CLI means re-running this script AND committing its output.
#   The backend image's build context is only ./src/backend/ (ci.yml +
#   src/backend/Dockerfile `COPY ./ ./`), so src/bisheng-cli/ is NOT in the
#   image. The wheel therefore has to travel inside the backend package, which
#   is why the artifacts directory lives under bisheng/dev_toolkit/. Skip the
#   commit and the platform keeps serving the previous wheel with no warning.
#
#   The directory name `artifacts` is deliberate. .gitignore carries `build/`,
#   `lib/`, `wheels/` and `sdist/` WITHOUT a leading slash, so those names are
#   ignored at every depth and `git add` on them fails silently. Do not rename.
#
# The install smoke test at the end is not optional padding. app-proxy shipped
# `fastapi>=0.115` with no ceiling; the dev machine resolved 0.121 with a fully
# green suite while production resolved 0.141 and died at module import. Running
# pytest in the source tree can never catch that class of failure, because it
# tests the versions the dev environment already resolved. The CLI's real
# distribution path is `pip install <wheel>` on somebody else's machine, so that
# is what gets exercised here.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI_DIR="${REPO_ROOT}/src/bisheng-cli"
ARTIFACTS_DIR="${REPO_ROOT}/src/backend/bisheng/dev_toolkit/artifacts"
SMOKE_VENV="${TMPDIR:-/tmp}/bisheng-cli-smoke-$$"

fail() {
  echo "[FAIL] $*" >&2
  exit 1
}

command -v uv >/dev/null 2>&1 || fail "uv not found on PATH — see src/backend/AGENTS.md for setup"

VERSION="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "${CLI_DIR}/bisheng_cli/__init__.py")"
[ -n "${VERSION}" ] || fail "could not read __version__ from bisheng_cli/__init__.py"

echo "[1/5] building wheel for bisheng-cli ${VERSION}"
rm -rf "${CLI_DIR}/dist"
(cd "${CLI_DIR}" && uv build --wheel)

WHEEL="$(ls "${CLI_DIR}"/dist/*.whl 2>/dev/null | head -n 1 || true)"
[ -n "${WHEEL}" ] || fail "uv build produced no wheel"
WHEEL_NAME="$(basename "${WHEEL}")"

echo "[2/5] validating ${WHEEL_NAME}"
[ -s "${WHEEL}" ] || fail "${WHEEL_NAME} is empty"
# Missing `[tool.hatch.build.targets.wheel] packages` produces a wheel that
# builds, uploads and installs cleanly while containing no code at all.
#
# ⚠️ The listing is captured first instead of piped into `grep -q`. Under
# `set -o pipefail` (line 27), `grep -q` exits the moment it matches, `unzip`
# then dies of SIGPIPE, and the pipeline reports 141 — so a wheel that DOES
# contain the module is reported as one that does not. Measured, not theorised:
# this exact check failed on a perfectly good wheel the first time the script
# was ever run. A guard that lies in the failing direction is worse than no
# guard, because the fix people reach for is deleting it.
WHEEL_LISTING="$(unzip -l "${WHEEL}")"
case "${WHEEL_LISTING}" in
  *"bisheng_cli/main.py"*) ;;
  *) fail "${WHEEL_NAME} does not contain bisheng_cli/ — check [tool.hatch.build.targets.wheel] packages" ;;
esac
case "${WHEEL_NAME}" in
  *"-${VERSION}-"*) ;;
  *) fail "wheel name ${WHEEL_NAME} does not carry version ${VERSION}" ;;
esac

echo "[3/5] install smoke test in a clean venv"
rm -rf "${SMOKE_VENV}"
uv venv "${SMOKE_VENV}" >/dev/null
trap 'rm -rf "${SMOKE_VENV}"' EXIT
# `uv venv` does not seed pip, so the install goes through uv targeting that
# interpreter. It is the same resolution path a user's `pip install <wheel>`
# takes — what matters is that the venv starts empty and the wheel's own
# metadata decides which dependency versions land in it.
uv pip install --quiet --python "${SMOKE_VENV}/bin/python" "${WHEEL}" \
  || fail "installing the wheel into a clean venv failed"
# (a) module-level import of the production entry point
"${SMOKE_VENV}/bin/python" -c "import bisheng_cli.main" \
  || fail "import bisheng_cli.main failed in the clean venv — a dependency resolved to an incompatible version"
# (b) the console script is really registered, and agrees on the version
SMOKE_VERSION="$("${SMOKE_VENV}/bin/bisheng" --version | awk '{print $2}')" \
  || fail "the 'bisheng' console script did not run"
[ "${SMOKE_VERSION}" = "${VERSION}" ] \
  || fail "console script reports ${SMOKE_VERSION}, package says ${VERSION}"
# (c) the argparse tree can be built
"${SMOKE_VENV}/bin/bisheng" deploy --help >/dev/null || fail "'bisheng deploy --help' failed"

echo "[4/5] staging into ${ARTIFACTS_DIR#"${REPO_ROOT}/"}"
mkdir -p "${ARTIFACTS_DIR}"
rm -f "${ARTIFACTS_DIR}"/*.whl
cp "${WHEEL}" "${ARTIFACTS_DIR}/${WHEEL_NAME}"

if command -v sha256sum >/dev/null 2>&1; then
  SHA256="$(sha256sum "${ARTIFACTS_DIR}/${WHEEL_NAME}" | awk '{print $1}')"
else
  SHA256="$(shasum -a 256 "${ARTIFACTS_DIR}/${WHEEL_NAME}" | awk '{print $1}')"
fi

cat > "${ARTIFACTS_DIR}/manifest.json" <<JSON
{
  "cli": {
    "version": "${VERSION}",
    "min_compatible": "${VERSION}",
    "filename": "${WHEEL_NAME}",
    "sha256": "${SHA256}"
  },
  "platform": {
    "version": "${VERSION}"
  },
  "_note": "Generated by scripts/pack_cli_wheel.sh. Commit this file and the wheel beside it; the backend image cannot see src/bisheng-cli/."
}
JSON

echo "[5/5] checking the artifacts are actually committable"
if git -C "${REPO_ROOT}" check-ignore -q "${ARTIFACTS_DIR}/${WHEEL_NAME}"; then
  git -C "${REPO_ROOT}" check-ignore -v "${ARTIFACTS_DIR}/${WHEEL_NAME}" >&2 || true
  fail "the wheel is matched by a .gitignore rule — it would never reach the image"
fi

echo "[OK] ${WHEEL_NAME} (${SHA256:0:12}…) staged in ${ARTIFACTS_DIR#"${REPO_ROOT}/"}"
echo "     Commit both the wheel and manifest.json, or the platform will serve the previous version."
