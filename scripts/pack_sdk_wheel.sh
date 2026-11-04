#!/usr/bin/env bash
# Build the bisheng-sdk wheel and stage it for the platform's own distribution.
#
#   bash scripts/pack_sdk_wheel.sh
#
# RELEASE CONTRACT — read this before changing anything below.
#
#   Changing the SDK means re-running this script AND committing its output.
#   The backend image's build context is only ./src/backend/ (ci.yml +
#   src/backend/Dockerfile `COPY ./ ./`), so src/bisheng-sdk/ is NOT in the
#   image. The wheel therefore has to travel inside the backend package — the
#   same reason the CLI wheel does. Skip the commit and `/versions` keeps
#   answering `sdk: null`, the simple index keeps 404ing, and a hosted build
#   that lists `bisheng-sdk` in requirements.txt fails with "no matching
#   distribution" — a release problem that reads like a broken platform.
#
#   This script and scripts/pack_cli_wheel.sh write the SAME manifest.json and
#   stage into the SAME directory. Both therefore:
#     * delete only their own `bisheng_sdk-*.whl` / `bisheng_cli-*.whl`, and
#     * MERGE their section into the existing manifest instead of rewriting it.
#   Rewriting (the shape this file's sibling shipped with first) silently drops
#   the other section, and nothing downstream notices until a developer's pip
#   cannot find the package.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SDK_DIR="${REPO_ROOT}/src/bisheng-sdk"
ARTIFACTS_DIR="${REPO_ROOT}/src/backend/bisheng/dev_toolkit/artifacts"
COMPAT_MODULE="${REPO_ROOT}/src/backend/bisheng/dev_toolkit/sdk_compat.py"
SMOKE_VENV="${TMPDIR:-/tmp}/bisheng-sdk-smoke-$$"

fail() {
  echo "[FAIL] $*" >&2
  exit 1
}

command -v uv >/dev/null 2>&1 || fail "uv not found on PATH — see src/backend/AGENTS.md for setup"
[ -d "${SDK_DIR}" ] || fail "src/bisheng-sdk/ does not exist — the SDK package has not landed yet"

VERSION="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "${SDK_DIR}/bisheng_sdk/__init__.py")"
[ -n "${VERSION}" ] || fail "could not read __version__ from bisheng_sdk/__init__.py"

# The platform's declared floor, read from the backend constant so there is one
# source for it and no chance of the manifest and the module disagreeing.
MIN_COMPATIBLE="$(sed -n 's/^SDK_MIN_COMPATIBLE = "\(.*\)"$/\1/p' "${COMPAT_MODULE}")"
[ -n "${MIN_COMPATIBLE}" ] || fail "could not read SDK_MIN_COMPATIBLE from ${COMPAT_MODULE#"${REPO_ROOT}/"}"

echo "[1/5] building wheel for bisheng-sdk ${VERSION} (platform floor ${MIN_COMPATIBLE})"
rm -rf "${SDK_DIR}/dist"
(cd "${SDK_DIR}" && uv build --wheel)

WHEEL="$(ls "${SDK_DIR}"/dist/*.whl 2>/dev/null | head -n 1 || true)"
[ -n "${WHEEL}" ] || fail "uv build produced no wheel"
WHEEL_NAME="$(basename "${WHEEL}")"

echo "[2/5] validating ${WHEEL_NAME}"
[ -s "${WHEEL}" ] || fail "${WHEEL_NAME} is empty"
# A directory with a hyphen in its name (bisheng-sdk) is exactly the case where
# hatchling cannot infer the package dir: without
# `[tool.hatch.build.targets.wheel] packages = ["bisheng_sdk"]` the build
# succeeds and produces a wheel that installs cleanly and contains no code.
#
# ⚠️ The listing is captured first instead of piped into `grep -q`. Under
# `set -o pipefail`, `grep -q` exits on its first match, `unzip` dies of
# SIGPIPE, and the pipeline reports 141 — so a good wheel is reported as bad.
# Measured on the CLI script the first time it ever ran.
WHEEL_LISTING="$(unzip -l "${WHEEL}")"
for member in bisheng_sdk/auth.py bisheng_sdk/retrieve.py bisheng_sdk/storage.py; do
  case "${WHEEL_LISTING}" in
    *"${member}"*) ;;
    *) fail "${WHEEL_NAME} does not contain ${member} — check [tool.hatch.build.targets.wheel] packages" ;;
  esac
done
case "${WHEEL_NAME}" in
  *"-${VERSION}-"*) ;;
  *) fail "wheel name ${WHEEL_NAME} does not carry version ${VERSION}" ;;
esac

echo "[3/5] install smoke test in a clean venv"
rm -rf "${SMOKE_VENV}"
uv venv "${SMOKE_VENV}" >/dev/null
trap 'rm -rf "${SMOKE_VENV}"' EXIT
# The SDK's real distribution path is `pip install bisheng-sdk` inside an app's
# build container, where uv.lock plays no part and the dependency ceilings in
# the wheel metadata are the only constraint. That is what gets exercised here —
# running pytest in the source tree can only ever test the versions this machine
# already resolved.
uv pip install --quiet --python "${SMOKE_VENV}/bin/python" "${WHEEL}" \
  || fail "installing the wheel into a clean venv failed"
"${SMOKE_VENV}/bin/python" -c "
import bisheng_sdk, bisheng_sdk.auth, bisheng_sdk.retrieve, bisheng_sdk.storage, bisheng_sdk.errors
assert bisheng_sdk.__version__ == '${VERSION}', bisheng_sdk.__version__
" || fail "the installed wheel does not import its three capability modules at version ${VERSION}"

echo "[4/5] staging into ${ARTIFACTS_DIR#"${REPO_ROOT}/"}"
mkdir -p "${ARTIFACTS_DIR}"
# Only this package's wheels. `rm -f *.whl` here would delete the CLI wheel the
# manifest still advertises, and /cli/download would 404 for the next release.
rm -f "${ARTIFACTS_DIR}"/bisheng_sdk-*.whl
cp "${WHEEL}" "${ARTIFACTS_DIR}/${WHEEL_NAME}"

if command -v sha256sum >/dev/null 2>&1; then
  SHA256="$(sha256sum "${ARTIFACTS_DIR}/${WHEEL_NAME}" | awk '{print $1}')"
else
  SHA256="$(shasum -a 256 "${ARTIFACTS_DIR}/${WHEEL_NAME}" | awk '{print $1}')"
fi

# Merge, never rewrite: the `cli` and `platform` sections belong to the sibling
# script and must survive byte-for-byte (cli-quality.yml diffs this file).
MANIFEST="${ARTIFACTS_DIR}/manifest.json" \
SDK_VERSION="${VERSION}" \
SDK_MIN_COMPATIBLE="${MIN_COMPATIBLE}" \
SDK_FILENAME="${WHEEL_NAME}" \
SDK_SHA256="${SHA256}" \
python3 - <<'PY'
import json
import os
from pathlib import Path

path = Path(os.environ["MANIFEST"])
manifest = {}
if path.is_file():
    manifest = json.loads(path.read_text(encoding="utf-8"))

manifest["sdk"] = {
    "version": os.environ["SDK_VERSION"],
    "min_compatible": os.environ["SDK_MIN_COMPATIBLE"],
    "filename": os.environ["SDK_FILENAME"],
    "sha256": os.environ["SDK_SHA256"],
}
# Both packing scripts write the same note, so the file does not flip between
# two wordings depending on which of them ran last (cli-quality.yml diffs it).
manifest["_note"] = (
    "Generated by scripts/pack_cli_wheel.sh and scripts/pack_sdk_wheel.sh. "
    "Commit this file and the wheels beside it; the backend image cannot see src/bisheng-cli/ or src/bisheng-sdk/."
)
path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
PY

echo "[5/5] checking the artifacts are actually committable"
if git -C "${REPO_ROOT}" check-ignore -q "${ARTIFACTS_DIR}/${WHEEL_NAME}"; then
  git -C "${REPO_ROOT}" check-ignore -v "${ARTIFACTS_DIR}/${WHEEL_NAME}" >&2 || true
  fail "the wheel is matched by a .gitignore rule — it would never reach the image"
fi

echo "[OK] ${WHEEL_NAME} (${SHA256:0:12}…) staged in ${ARTIFACTS_DIR#"${REPO_ROOT}/"}"
echo "     Commit both the wheel and manifest.json, or /versions keeps answering sdk=null"
echo "     and a hosted build listing bisheng-sdk cannot resolve it."
