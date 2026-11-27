#!/usr/bin/env bash
# Finish a bundle with its standalone installer, optional Compose Gateway and index.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION=""; ARCH=""; DIR=""; DOCKER_DIR=""; WITH_GATEWAY=0; DO_PULL=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --version) VERSION="${2:?}"; shift 2 ;;
    --arch) ARCH="${2:?}"; shift 2 ;;
    --dir) DIR="${2:?}"; shift 2 ;;
    --docker-dir) DOCKER_DIR="${2:?}"; shift 2 ;;
    --with-gateway) WITH_GATEWAY=1; shift ;;
    --no-pull) DO_PULL=0; shift ;;
    *) echo "未知参数：$1" >&2; exit 1 ;;
  esac
done
[[ "$ARCH" =~ ^(amd64|arm64)$ && -n "$VERSION" && -d "$DIR" && -d "$DOCKER_DIR" ]]
NAME="bisheng-offline-${VERSION}-${ARCH}"
cp "$ROOT/deploy.sh" "$DIR/deploy.sh"

if [[ "$WITH_GATEWAY" == 1 ]]; then
  # Resolve the tag's actual Compose configuration, including .env.example defaults.
  # No platform-version substitution or guessed -arm64 suffix for Gateway.
  gateway="$(docker compose --env-file "$DOCKER_DIR/.env.example" \
    -f "$DOCKER_DIR/docker-compose.yml" --profile gateway config --format json \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["services"]["gateway"]["image"])')"
  [[ -n "$gateway" && "$gateway" != *[[:space:]]* ]]
  if [[ "$DO_PULL" == 1 ]]; then docker pull --platform "linux/$ARCH" "$gateway"; fi
  actual="$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$gateway")"
  [[ "$actual" == "linux/$ARCH" ]] || { echo "Gateway 镜像架构为 ${actual}，需要 linux/${ARCH}：${gateway}" >&2; exit 1; }
  repo="${gateway%@*}"
  if [[ "$repo" == "$gateway" && "${repo##*/}" == *:* ]]; then repo="${repo%:*}"; fi
  digest="$(docker image inspect --format '{{range .RepoDigests}}{{println .}}{{end}}' "$gateway" \
    | awk -v prefix="${repo}@" 'index($0,prefix)==1 {sub(/^[^@]*@/, ""); print; exit}')"
  [[ "$digest" == sha256:* ]] || { echo "Gateway 缺少匹配仓库的 RepoDigest" >&2; exit 1; }
  mkdir -p "$DIR/gateway-addon"
  temporary="$(mktemp -d "$DIR/.gateway.XXXXXX")"
  trap 'rm -rf -- "$temporary"' EXIT
  docker save -o "$temporary/images.tar" "$gateway"
  zstd -q -f -T0 -10 "$temporary/images.tar" -o "$DIR/gateway-addon/images.tar.zst"
  python3 - "$DIR/gateway-addon/manifest.json" "$gateway" "$ARCH" "$digest" <<'PY'
import json, sys
with open(sys.argv[1], 'w', encoding='utf-8') as handle:
    json.dump(dict(image=sys.argv[2], arch=sys.argv[3], digest=sys.argv[4]), handle, indent=2)
    handle.write('\n')
PY
fi

python3 - "$DIR" "$VERSION" "$ARCH" "$WITH_GATEWAY" <<'PY'
import hashlib, json, pathlib, re, sys
root, version, arch, gateway = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4] == '1'
if not re.fullmatch(r'[0-9][A-Za-z0-9._-]*', version):
    raise SystemExit('版本号格式无效')
bundle = 'bisheng-offline-%s-%s' % (version, arch)
parts_sum = root / ('SHA256SUMS-%s.parts' % bundle)
files = []

def add(name, path, component):
    source = root / name
    digest = hashlib.sha256()
    with source.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    files.append(dict(name=name, path=path, component=component,
                      size=source.stat().st_size, sha256=digest.hexdigest()))

add('deploy.sh', 'deploy.sh', 'base')
for line in parts_sum.read_text().splitlines():
    expected, filename = line.split(None, 1)
    filename = filename.lstrip('*')
    if '/' in filename or not filename.startswith(bundle + '.tar'):
        raise SystemExit('分卷校验清单文件名无效')
    add(filename, 'packages/' + filename, 'base')
    if files[-1]['sha256'] != expected:
        raise SystemExit('归档已变化：' + filename)
payload = dict(schema_version=1, product='bisheng', version=version, arch=arch, bundle=bundle, files=files)
if gateway:
    for name in ('images.tar.zst', 'manifest.json'):
        add('gateway-addon/' + name, 'gateway-addon/' + name, 'gateway')
    payload['gateway'] = json.loads((root / 'gateway-addon/manifest.json').read_text())
temporary = root / '.download.json.tmp'
temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
temporary.replace(root / 'download.json')
PY
