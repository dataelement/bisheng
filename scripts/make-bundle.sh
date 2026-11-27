#!/usr/bin/env bash
# 生成毕昇离线安装包：一次 docker save、压缩、docker.tar.gz、manifest、校验和、外层 tar。
# images.txt 每行必须是三列：ENV_NAME service ref
#
#   ./make-bundle.sh --version 3.1.0 --arch amd64 --images-file images.txt \
#                    --docker-dir ./docker --out dist [--with-gateway]
set -euo pipefail
export COPYFILE_DISABLE=1

VERSION=""
ARCH=""
IMAGES_FILE=""
DOCKER_DIR=""
OUT_DIR="dist"
COMPRESS="zstd"
SPLIT_SIZE="2G"
DO_PULL=1
KEEP_STAGE=0
WITH_GATEWAY=0
DRY_RUN=0
ZSTD_LEVEL=10
STAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

log()  { printf '[make-bundle] %s\n' "$*" >&2; }
die()  { printf '[make-bundle][ERROR] %s\n' "$*" >&2; exit 1; }

usage() {
  sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
}

need_cmd() { command -v "$1" >/dev/null 2>&1 || die "缺少命令：$1"; }

if command -v sha256sum >/dev/null 2>&1; then
  SHA256="sha256sum"
elif command -v shasum >/dev/null 2>&1; then
  SHA256="shasum -a 256"
else
  die "缺少 sha256sum 或 shasum"
fi

file_size() {
  if stat -c %s "$1" >/dev/null 2>&1; then stat -c %s "$1"; else stat -f %z "$1"; fi
}

to_bytes() {
  local v="$1"
  printf '%s' "$v" | awk '
    /^[0-9]+$/{print $0; next}
    /^[0-9]+[KkMmGgTt]$/{
      n=substr($0,1,length($0)-1); u=toupper(substr($0,length($0),1));
      m=(u=="K")?1024:(u=="M")?1024^2:(u=="G")?1024^3:1024^4;
      printf "%.0f\n", n*m; next}
    {exit 1}'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)      VERSION="${2:?}"; shift 2 ;;
    --arch)         ARCH="${2:?}"; shift 2 ;;
    --images-file)  IMAGES_FILE="${2:?}"; shift 2 ;;
    --docker-dir)   DOCKER_DIR="${2:?}"; shift 2 ;;
    --out)          OUT_DIR="${2:?}"; shift 2 ;;
    --compress)     COMPRESS="${2:?}"; shift 2 ;;
    --split-size)   SPLIT_SIZE="${2:?}"; shift 2 ;;
    --zstd-level)   ZSTD_LEVEL="${2:?}"; shift 2 ;;
    --no-pull)      DO_PULL=0; shift ;;
    --keep-stage)   KEEP_STAGE=1; shift ;;
    --with-gateway) WITH_GATEWAY=1; shift ;;
    --dry-run)      DRY_RUN=1; shift ;;
    -h|--help)      usage ;;
    *)              die "未知参数：$1（--help 查看用法）" ;;
  esac
done

[[ -n "$VERSION" ]]     || die "必须指定 --version（如 3.1.0）"
[[ "$VERSION" =~ ^[0-9][A-Za-z0-9._-]*$ ]] || die "--version 格式非法，不允许路径字符"
[[ "$ARCH" =~ ^(amd64|arm64)$ ]] || die "--arch 只能是 amd64 或 arm64"
[[ -n "$IMAGES_FILE" ]]  || die "必须指定 --images-file"
[[ -f "$IMAGES_FILE" ]]  || die "镜像清单不存在：$IMAGES_FILE"
[[ -n "$DOCKER_DIR" ]]   || die "必须指定 --docker-dir"
[[ -d "$DOCKER_DIR" ]]   || die "docker 目录不存在：$DOCKER_DIR"

case "$COMPRESS" in
  zstd) need_cmd zstd ;;
  gzip) need_cmd gzip ;;
  none) ;;
  *) die "--compress 只能是 zstd / gzip / none" ;;
esac
need_cmd python3
[[ "$DRY_RUN" -eq 1 ]] || need_cmd docker

BYTES=$(to_bytes "$SPLIT_SIZE") || die "--split-size 格式非法：$SPLIT_SIZE"
[[ "$BYTES" =~ ^[0-9]+$ && "$BYTES" -gt 0 ]] || die "--split-size 必须大于零"
NAME="bisheng-offline-${VERSION}-${ARCH}"
STAGE="${OUT_DIR}/${NAME}"

ENVS=()
SERVICES=()
REFS=()
while IFS= read -r line; do
  line="${line%%#*}"
  line="$(printf '%s' "$line" | awk '{$1=$1;print}')"
  [[ -z "$line" ]] && continue
  cols=$(printf '%s' "$line" | awk '{print NF}')
  [[ "$cols" -eq 3 ]] || die "images.txt 每行必须是三列 ENV_NAME service ref：$line"
  ENVS+=("$(printf '%s' "$line" | awk '{print $1}')")
  SERVICES+=("$(printf '%s' "$line" | awk '{print $2}')")
  REFS+=("$(printf '%s' "$line" | awk '{print $3}')")
done < "$IMAGES_FILE"

[[ ${#REFS[@]} -gt 0 ]] || die "镜像清单为空：$IMAGES_FILE"
log "镜像数量：${#REFS[@]}，版本 ${VERSION} / ${ARCH}"

if [[ "$DRY_RUN" -eq 1 ]]; then
  log "== DRY RUN（不拉取、不导出）=="
  for i in "${!REFS[@]}"; do
    log "  ${ENVS[$i]}  ${SERVICES[$i]}  ${REFS[$i]}"
  done
  log "  组装目录：${STAGE}"
  log "  压缩：${COMPRESS}（zstd level=${ZSTD_LEVEL}） 分卷阈值：${SPLIT_SIZE} (${BYTES} bytes)"
  exit 0
fi

mkdir -p "${STAGE}/images"
DIGESTS=()

for i in "${!REFS[@]}"; do
  ref="${REFS[$i]}"
  if [[ "$DO_PULL" -eq 1 ]]; then
    log "pull $ref"
    docker pull --platform "linux/${ARCH}" "$ref" >/dev/null
  fi

  repo="${ref%:*}"
  digest=""
  digests="$(docker image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' "$ref")" \
    || die "无法读取 $ref 的 RepoDigests"
  while IFS= read -r item; do
    [[ -z "$item" ]] && continue
    if [[ "${item%@*}" == "$repo" ]]; then
      digest="${item#*@}"
      break
    fi
  done <<EOF
$digests
EOF
  [[ "$digest" == sha256:* ]] || die "$ref 的 RepoDigests 里没有仓库 ${repo} 的 manifest digest"

  img_arch="$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$ref")"
  [[ "$img_arch" == "linux/${ARCH}" ]] || die "$ref 架构为 ${img_arch}，需要 linux/${ARCH}"

  DIGESTS+=("$digest")
  log "  -> ${digest} (${img_arch})"
done

IMAGES_TAR="${STAGE}/images/all-images.tar"
log "docker save -> ${IMAGES_TAR}"
docker save -o "$IMAGES_TAR" "${REFS[@]}"

case "$COMPRESS" in
  zstd)
    log "zstd 压缩（level=${ZSTD_LEVEL}，多线程）"
    zstd -q -f -T0 "-${ZSTD_LEVEL}" "$IMAGES_TAR" -o "${STAGE}/images.tar.zst"
    rm -f "$IMAGES_TAR"
    IMAGES_OUT="images.tar.zst"
    ;;
  gzip)
    log "gzip 压缩"
    gzip -9 -f "$IMAGES_TAR"
    IMAGES_OUT="images.tar.gz"
    mv "${IMAGES_TAR}.gz" "${STAGE}/${IMAGES_OUT}"
    ;;
  none)
    IMAGES_OUT="images/all-images.tar"
    ;;
esac
rmdir "${STAGE}/images" 2>/dev/null || true

log "打包 docker 目录"
docker_parent="$(cd "$(dirname "$DOCKER_DIR")" && pwd)"
docker_base="$(basename "$DOCKER_DIR")"
tar -czf "${STAGE}/docker.tar.gz" \
  --exclude='.git' --exclude='node_modules' --exclude='__pycache__' \
  --exclude="${docker_base}/.env" --exclude="${docker_base}/.generated" \
  --exclude="${docker_base}/data" --exclude="${docker_base}/mysql/data" \
  -C "$docker_parent" "$docker_base"

log "生成 manifest.json"
export MB_VERSION="$VERSION" MB_ARCH="$ARCH" MB_STAMP="$STAMP" \
       MB_IMAGES_OUT="$IMAGES_OUT" MB_DOCKER_OUT="docker.tar.gz" \
       MB_SHA256="$SHA256"

python3 - "$STAGE" "${#REFS[@]}" "${ENVS[@]}" "${SERVICES[@]}" "${REFS[@]}" "${DIGESTS[@]}" <<'PY'
import json, os, subprocess, sys

stage = sys.argv[1]
count = int(sys.argv[2])
rest = sys.argv[3:]
envs = rest[0:count]
services = rest[count:2*count]
refs = rest[2*count:3*count]
digests = rest[3*count:4*count]

def sha256(path):
    out = subprocess.check_output(os.environ["MB_SHA256"].split() + [path])
    return out.decode().split()[0]

files = []
for fn in (os.environ["MB_IMAGES_OUT"], os.environ["MB_DOCKER_OUT"]):
    path = os.path.join(stage, fn)
    if not os.path.exists(path):
        raise SystemExit("缺少打包文件：%s" % fn)
    files.append({"name": fn, "size": os.path.getsize(path), "sha256": sha256(path)})

images = []
for env_name, service, ref, digest in zip(envs, services, refs, digests):
    images.append({
        "env": env_name,
        "service": service,
        "ref": ref,
        "digest": digest,
        "arch": os.environ["MB_ARCH"],
    })

git_commit = os.environ.get("GIT_COMMIT") or os.environ.get("GITHUB_SHA") or os.environ.get("DRONE_COMMIT") or ""
manifest = {
    "product": "bisheng",
    "version": os.environ["MB_VERSION"],
    "arch": os.environ["MB_ARCH"],
    "git_commit": git_commit,
    "git_ref": os.environ.get("GIT_REF") or os.environ.get("GITHUB_REF") or "",
    "ci": {
        "provider": os.environ.get("CI_PROVIDER") or ("github" if os.environ.get("GITHUB_ACTIONS") else "local"),
        "run_id": os.environ.get("GITHUB_RUN_ID") or os.environ.get("DRONE_BUILD_NUMBER") or "",
        "workflow": os.environ.get("GITHUB_WORKFLOW") or os.environ.get("DRONE_STAGE_NAME") or "",
    },
    "built_at": os.environ["MB_STAMP"],
    "images": images,
    "files": files,
    "notes": "offline bundle; after tar xzf docker.tar.gz, run: bash docker/install.sh --offline",
}
with open(os.path.join(stage, "manifest.json"), "w") as handle:
    json.dump(manifest, handle, ensure_ascii=False, indent=2)
    handle.write("\n")
PY

log "生成 SHA256SUMS"
(
  cd "$STAGE"
  : > SHA256SUMS
  for f in manifest.json "$IMAGES_OUT" docker.tar.gz; do
    [[ -f "$f" ]] || die "SHA256SUMS 缺少文件：$f"
    $SHA256 "$f" >> SHA256SUMS
  done
)

mkdir -p "$OUT_DIR"
TAR_PATH="${OUT_DIR}/${NAME}.tar"
log "组装 ${TAR_PATH}"
tar -cf "$TAR_PATH" -C "$OUT_DIR" "$NAME"

cp "${STAGE}/manifest.json" "${OUT_DIR}/manifest-${NAME}.json"
cp "${STAGE}/SHA256SUMS" "${OUT_DIR}/SHA256SUMS-${NAME}"
[[ "$KEEP_STAGE" -eq 1 ]] || rm -rf "$STAGE"

TAR_SIZE=$(file_size "$TAR_PATH")
PARTS=()
if [[ "$TAR_SIZE" -gt "$BYTES" ]]; then
  log "包大小 ${TAR_SIZE} 超过阈值 ${BYTES}，开始分卷"
  rm -f "${TAR_PATH}".part.* 2>/dev/null || true
  split -b "$BYTES" -d -a 2 "$TAR_PATH" "${TAR_PATH}.part."
  rm -f "$TAR_PATH"
  for p in "${TAR_PATH}".part.*; do PARTS+=("$p"); done
else
  log "包大小 ${TAR_SIZE}，未触发分卷"
  PARTS=("$TAR_PATH")
fi

PARTS_SUM="${OUT_DIR}/SHA256SUMS-${NAME}.parts"
: > "$PARTS_SUM"
for p in "${PARTS[@]}"; do
  ( cd "$OUT_DIR" && $SHA256 "$(basename "$p")" >> "$(basename "$PARTS_SUM")" )
done

log "== 产出 =="
for p in "${PARTS[@]}"; do
  log "  $(basename "$p")  $(file_size "$p") bytes"
done

delivery_args=(--dir "$OUT_DIR" --version "$VERSION" --arch "$ARCH" --docker-dir "$DOCKER_DIR")
[[ "$WITH_GATEWAY" == 0 ]] || delivery_args+=(--with-gateway)
[[ "$DO_PULL" == 1 ]] || delivery_args+=(--no-pull)
bash "$(dirname "${BASH_SOURCE[0]}")/prepare-offline-delivery.sh" "${delivery_args[@]}"
