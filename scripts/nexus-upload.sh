#!/usr/bin/env bash
# 把离线包上传到 Nexus raw 仓库。--verify sha256 时先整文件比对，不一致不覆盖；
# 上传后再整文件下载比对。全部通过后才写 latest-<arch>.json。
#
#   export NEXUS_USER=ci-publisher NEXUS_PASS=******
#   ./nexus-upload.sh --dir dist --version 3.1.0 --arch amd64 \
#     --base-url https://nexus.dataelem.com --repo raw-hosted \
#     --method rest --verify sha256 --update-latest
set -euo pipefail

DIR=""
VERSION=""
ARCH=""
BASE_URL="https://nexus.dataelem.com"
REPO="raw-hosted"
PREFIX="deploy/bisheng"
METHOD="rest"
UPDATE_LATEST=0
DRY_RUN=0
VERIFY="size"
RETRIES=3
RETRY_DELAY=3
ALLOW_EXISTING=1
USER="${NEXUS_USER:-}"
PASS="${NEXUS_PASS:-}"
PRECHECK="error"

log() { printf '[nexus-upload] %s\n' "$*" >&2; }
die() { printf '[nexus-upload][ERROR] %s\n' "$*" >&2; exit 2; }

usage() { sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0; }
need_cmd() { command -v "$1" >/dev/null 2>&1 || die "缺少命令：$1"; }

if command -v sha256sum >/dev/null 2>&1; then SHA256="sha256sum";
elif command -v shasum >/dev/null 2>&1; then SHA256="shasum -a 256";
else SHA256=""; fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dir)            DIR="${2:?}"; shift 2 ;;
    --version)        VERSION="${2:?}"; shift 2 ;;
    --arch)           ARCH="${2:?}"; shift 2 ;;
    --base-url)       BASE_URL="${2:?}"; shift 2 ;;
    --repo)           REPO="${2:?}"; shift 2 ;;
    --prefix)         PREFIX="${2:?}"; shift 2 ;;
    --method)         METHOD="${2:?}"; shift 2 ;;
    --verify)         VERIFY="${2:?}"; shift 2 ;;
    --retries)        RETRIES="${2:?}"; shift 2 ;;
    --user)           USER="${2:?}"; shift 2 ;;
    --pass)           PASS="${2:?}"; shift 2 ;;
    --update-latest)  UPDATE_LATEST=1; shift ;;
    --no-allow-existing) ALLOW_EXISTING=0; shift ;;
    --dry-run)        DRY_RUN=1; shift ;;
    -h|--help)        usage ;;
    *)                die "未知参数：$1（--help 查看用法）" ;;
  esac
done

[[ -n "$DIR" && -d "$DIR" ]] || die "--dir 必须是已存在的目录"
[[ -n "$VERSION" ]] || die "必须指定 --version"
[[ "$ARCH" =~ ^(amd64|arm64)$ ]] || die "--arch 只能是 amd64 或 arm64"
[[ "$METHOD" =~ ^(rest|put)$ ]] || die "--method 只能是 rest 或 put"
[[ "$VERIFY" =~ ^(size|sha256|none)$ ]] || die "--verify 只能是 size / sha256 / none"
BASE_URL="${BASE_URL%/}"
need_cmd curl
need_cmd python3

REMOTE_DIR="${PREFIX}/${VERSION}/${ARCH}"
REMOTE_URL_BASE="${BASE_URL}/repository/${REPO}/${REMOTE_DIR}"

shopt -s nullglob
LOCAL=(); REMOTE=()

INDEX_FILE=""
if [[ -f "$DIR/download.json" ]]; then
  INDEX_FILE="$DIR/download.json"
  plan="$(python3 - "$DIR" "$VERSION" "$ARCH" <<'PYINDEX'
import hashlib, json, pathlib, re, sys
root = pathlib.Path(sys.argv[1]).resolve()
index = json.loads((root / 'download.json').read_text())
if index.get('version') != sys.argv[2] or index.get('arch') != sys.argv[3]:
    raise SystemExit('下载清单版本/架构与上传目标不一致')
seen = set()
for item in index['files']:
    name = item['name']
    if not re.fullmatch(r'[A-Za-z0-9_./+-]+', name) or any(p in ('', '.', '..') for p in name.split('/')) or name in seen:
        raise SystemExit('下载清单文件名无效或重复')
    seen.add(name)
    source = root / name
    if source.is_symlink() or root not in source.resolve().parents:
        raise SystemExit('上传文件不能逃逸产物目录')
    digest = hashlib.sha256()
    with source.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    if source.stat().st_size != item['size'] or digest.hexdigest() != item['sha256']:
        raise SystemExit('上传文件与下载清单不一致：' + name)
    print(name)
PYINDEX
)" || die "下载清单或交付文件无效"
  while IFS= read -r name; do LOCAL+=( "$DIR/$name" ); REMOTE+=( "$name" ); done <<< "$plan"
else
  # Legacy bundles produced before download.json retain their existing upload layout.
  PARTS=( "${DIR}"/*.tar.part.* )
  if [[ ${#PARTS[@]} -gt 0 ]]; then
    for p in "${PARTS[@]}"; do LOCAL+=( "$p" ); REMOTE+=( "$(basename "$p")" ); done
  else
    TARS=( "${DIR}"/*.tar )
    [[ ${#TARS[@]} -gt 0 ]] || die "${DIR} 下既没有 *.tar.part.* 也没有 *.tar"
    for t in "${TARS[@]}"; do LOCAL+=( "$t" ); REMOTE+=( "$(basename "$t")" ); done
  fi

  MFS=( "${DIR}"/manifest*.json )
  for m in "${MFS[@]}"; do
    case "$(basename "$m")" in
      manifest.json|manifest-*.json) LOCAL+=( "$m" ); REMOTE+=( "manifest.json" ); break ;;
    esac
  done
  SS=( "${DIR}"/SHA256SUMS* )
  for s in "${SS[@]}"; do
    case "$(basename "$s")" in
      *.parts) continue ;;
      SHA256SUMS|SHA256SUMS-*) LOCAL+=( "$s" ); REMOTE+=( "SHA256SUMS" ); break ;;
    esac
  done

fi

log "待上传 ${#LOCAL[@]} 个文件 -> ${REMOTE_DIR}"

file_bytes() {
  if stat -c %s "$1" >/dev/null 2>&1; then stat -c %s "$1"; else stat -f %z "$1"; fi
}

if [[ "$DRY_RUN" -eq 1 ]]; then
  log "== DRY RUN =="
  for i in "${!LOCAL[@]}"; do
    log "  $(basename "${LOCAL[$i]}") -> ${REMOTE[$i]}  ($(file_bytes "${LOCAL[$i]}") bytes)"
  done
  if [[ "$UPDATE_LATEST" -eq 1 ]]; then
    log "  将更新 ${PREFIX}/latest-${ARCH}.json"
  fi
  exit 0
fi

[[ -n "$USER" && -n "$PASS" ]] || die "缺少账号：请设置 NEXUS_USER / NEXUS_PASS 或 --user/--pass"
[[ "$VERIFY" != sha256 || -n "$SHA256" ]] || die "缺少 sha256sum/shasum，无法做 sha256 校验"

FAILED=0

hash_file() { $SHA256 "$1" | awk '{print $1}'; }

remote_get() {
  local name="$1" dest="$2"
  curl -sS -o "$dest" -w '%{http_code}' -u "${USER}:${PASS}" "${REMOTE_URL_BASE}/${name}" || printf '000'
}

precheck_file() {
  local f="$1" name="$2" tmp code want got
  PRECHECK=error
  tmp="$(mktemp)"
  code="$(remote_get "$name" "$tmp")"
  if [[ "$code" == "404" ]]; then
    rm -f "$tmp"
    PRECHECK=missing
    return 0
  fi
  if [[ "$code" != "200" ]]; then
    rm -f "$tmp"
    log "FAIL ${name} 上传前读取远端失败 HTTP ${code}"
    return 0
  fi
  want="$(hash_file "$f")"
  got="$(hash_file "$tmp")"
  rm -f "$tmp"
  if [[ "$want" == "$got" ]]; then
    PRECHECK=match
  else
    log "FAIL ${name} 远端已存在但 sha256 不同，不覆盖"
    PRECHECK=mismatch
  fi
}

remote_header_length() {
  curl -sSI -u "${USER}:${PASS}" "$1" \
    | tr -d '\r' \
    | awk 'tolower($1)=="content-length:"{print $2}' | tail -1
}

remote_size_matches() {
  local name="$1" f="$2" want got
  want="$(file_bytes "$f")"
  got="$(remote_header_length "${REMOTE_URL_BASE}/${name}")"
  [[ -n "$got" && "$got" == "$want" ]]
}

upload_one() {
  local f="$1" name="$2" http body attempt=1 directory="$REMOTE_DIR" filename
  filename="${name##*/}"
  [[ "$name" != */* ]] || directory="${REMOTE_DIR}/${name%/*}"
  while [[ "$attempt" -le "$RETRIES" ]]; do
    body="$(mktemp)"
    if [[ "$METHOD" == "rest" ]]; then
      http="$(curl -sS -o "$body" -w '%{http_code}' -u "${USER}:${PASS}" \
        -F "raw.directory=${directory}" \
        -F "raw.asset1=@${f};type=application/octet-stream" \
        -F "raw.asset1.filename=${filename}" \
        "${BASE_URL}/service/rest/v1/components?repository=${REPO}" || echo "000")"
    else
      http="$(curl -sS -o "$body" -w '%{http_code}' -u "${USER}:${PASS}" \
        -X PUT --upload-file "$f" \
        "${REMOTE_URL_BASE}/${name}" || echo "000")"
    fi
    case "$http" in
      200|201|204)
        rm -f "$body"
        log "OK   ${name}  (${http})"
        return 0 ;;
      409)
        if [[ "$ALLOW_EXISTING" -eq 1 && "$VERIFY" != sha256 ]] && remote_size_matches "$name" "$f"; then
          rm -f "$body"; log "SKIP ${name}  (409, 远端大小一致)"; return 0
        fi
        log "FAIL ${name}  (409)"; rm -f "$body"; return 1 ;;
      *)
        log "WARN ${name}  HTTP ${http}（第 ${attempt}/${RETRIES} 次）"
        head -c 300 "$body" >&2 || true; echo >&2
        rm -f "$body"
        ;;
    esac
    attempt=$((attempt + 1))
    if [[ "$attempt" -le "$RETRIES" ]]; then sleep "$RETRY_DELAY"; fi
  done
  log "FAIL ${name}  重试耗尽"
  return 1
}

verify_one() {
  local f="$1" name="$2" tmp want got
  if [[ "$VERIFY" == "none" ]]; then return 0; fi
  if [[ "$VERIFY" == "size" ]]; then
    remote_size_matches "$name" "$f" || { log "VERIFY-FAIL ${name} (size)"; return 1; }
    log "VERIFY ${name}  size ok"
    return 0
  fi
  want="$(hash_file "$f")"
  tmp="$(mktemp)"
  code="$(remote_get "$name" "$tmp")"
  got="$(hash_file "$tmp")"
  rm -f "$tmp"
  [[ "$code" == "200" && "$want" == "$got" ]] || { log "VERIFY-FAIL ${name} (sha256)"; return 1; }
  log "VERIFY ${name}  sha256 ok"
}

checked_upload() {
  local f="$1" name="$2"
  if [[ "$VERIFY" == sha256 ]]; then
    precheck_file "$f" "$name"
    case "$PRECHECK" in
      match) log "SKIP ${name}  (远端 sha256 一致)"; return 0 ;;
      missing) ;;
      *) return 1 ;;
    esac
  fi
  upload_one "$f" "$name" && verify_one "$f" "$name"
}

for i in "${!LOCAL[@]}"; do
  if ! checked_upload "${LOCAL[$i]}" "${REMOTE[$i]}"; then FAILED=$((FAILED + 1)); fi
done

# A fixed-version index is the publication marker: never publish it after a partial upload.
if [[ -n "$INDEX_FILE" && "$FAILED" -eq 0 ]]; then
  if checked_upload "$INDEX_FILE" download.json; then
    LOCAL+=( "$INDEX_FILE" ); REMOTE+=( download.json )
  else
    FAILED=$((FAILED + 1))
  fi
fi

if [[ "$UPDATE_LATEST" -eq 1 && "$FAILED" -eq 0 ]]; then
  LATEST_NAME="latest-${ARCH}.json"
  LATEST_LOCAL="${DIR}/${LATEST_NAME}"
  export NU_VERSION="$VERSION" NU_ARCH="$ARCH" NU_REMOTE_DIR="$REMOTE_DIR" \
         NU_BASE_URL="$BASE_URL" NU_REPO="$REPO"
  PAIRS=()
  for i in "${!LOCAL[@]}"; do PAIRS+=( "${LOCAL[$i]}:${REMOTE[$i]}" ); done
  python3 - "$LATEST_LOCAL" "${PAIRS[@]}" <<'PY'
import hashlib, json, os, sys
from datetime import datetime, timezone

out_path = sys.argv[1]
allow = os.environ["NU_BASE_URL"] + "/repository/" + os.environ["NU_REPO"] + "/" + os.environ["NU_REMOTE_DIR"]
version = os.environ["NU_VERSION"]
arch = os.environ["NU_ARCH"]

def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()

entries = []
for pair in sys.argv[2:]:
    local, remote = pair.rsplit(":", 1)
    entries.append({
        "name": remote,
        "url": "%s/%s" % (allow, remote),
        "size": os.path.getsize(local),
        "sha256": sha256(local),
    })
bundle = "bisheng-offline-%s-%s" % (version, arch)
payload = {
    "product": "bisheng",
    "version": version,
    "arch": arch,
    "path": os.environ["NU_REMOTE_DIR"],
    "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "files": entries,
    "verify": "sha256sum -c SHA256SUMS",
    "usage": (
        "cat %s.tar.part.* > %s.tar  # 未分卷时不要 cat，直接使用 json 里的 .tar\n"
        "tar xf %s.tar && cd %s\n"
        "sha256sum -c SHA256SUMS\n"
        "tar xzf docker.tar.gz\n"
        "bash docker/install.sh --offline"
    ) % (bundle, bundle, bundle, bundle),
}
with open(out_path, "w") as handle:
    json.dump(payload, handle, ensure_ascii=False, indent=2)
    handle.write("\n")
PY
  code="$(curl -sS -o /dev/null -w '%{http_code}' -u "${USER}:${PASS}" \
    -X PUT --upload-file "$LATEST_LOCAL" \
    "${BASE_URL}/repository/${REPO}/${PREFIX}/${LATEST_NAME}" || echo "000")"
  case "$code" in
    200|201|204) log "OK   ${PREFIX}/${LATEST_NAME}" ;;
    *) log "FAIL ${LATEST_NAME} 上传失败 HTTP ${code}"; FAILED=$((FAILED + 1)) ;;
  esac
fi

if [[ "$FAILED" -gt 0 ]]; then
  log "完成，但有 ${FAILED} 项失败"
  exit 1
fi

cat >&2 <<EOF
[nexus-upload] 全部完成
  版本目录：${REMOTE_URL_BASE}/
  版本指针：${BASE_URL}/repository/${REPO}/${PREFIX}/latest-${ARCH}.json

客户侧：
  curl -fsSLO ${BASE_URL}/repository/${REPO}/${PREFIX}/latest-${ARCH}.json
  # 按 files[].url 下载，并用 files[].sha256 校验
  # 分卷时才合并；未分卷时 json 里直接是 .tar，不要 cat part
  cat bisheng-offline-${VERSION}-${ARCH}.tar.part.* > bisheng-offline-${VERSION}-${ARCH}.tar
  tar xf bisheng-offline-${VERSION}-${ARCH}.tar && cd bisheng-offline-${VERSION}-${ARCH}
  sha256sum -c SHA256SUMS
  tar xzf docker.tar.gz
  bash docker/install.sh --offline
EOF
