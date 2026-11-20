#!/usr/bin/env bash
# Exercise the offline bundle scripts without a registry or Nexus.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
pass() { printf 'PASS: %s\n' "$*"; }
TMP="$(mktemp -d "${TMPDIR:-/tmp}/offline-bundle.XXXXXX")"
trap 'rm -rf -- "$TMP"' EXIT

lines="$(bash "$ROOT/scripts/collect-images.sh" --arch amd64 --version v3.1.0 --env-example "$ROOT/docker/.env.example")"
[[ "$(printf '%s\n' "$lines" | grep -c .)" -eq 13 ]] || fail 'amd64 image list is not 13 lines'
printf '%s\n' "$lines" | awk 'NF != 3 { exit 1 }' || fail 'image list is not three columns'
printf '%s\n' "$lines" | grep -q 'BISHENG_BACKEND_IMAGE backend cr.dataelem.com/dataelement/bisheng-backend:v3.1.0$' || fail 'amd64 backend ref'
printf '%s\n' "$lines" | grep -q 'DOCKER_SOCKET_PROXY_IMAGE docker-socket-proxy cr.dataelem.com/tecnativa/docker-socket-proxy:0.3.0$' || fail 'amd64 socket proxy'
printf '%s\n' "$lines" | grep -q 'gateway\|onlyoffice\|BISHENG_FT_IMAGE' && fail 'optional image included' || true
arm="$(bash "$ROOT/scripts/collect-images.sh" --arch arm64 --version v3.1.0 --env-example "$ROOT/docker/.env.example")"
printf '%s\n' "$arm" | grep -q 'bisheng-backend:v3.1.0-arm64$' || fail 'arm64 backend suffix'
printf '%s\n' "$arm" | grep -q 'docker-socket-proxy:0.3.0-arm64$' || fail 'arm64 socket proxy'
mysql_amd64="$(printf '%s\n' "$lines" | awk '$1=="MYSQL_IMAGE"{print $3}')"
mysql_arm64="$(printf '%s\n' "$arm" | awk '$1=="MYSQL_IMAGE"{print $3}')"
[[ "$mysql_amd64" == "$mysql_arm64" && -n "$mysql_amd64" ]] || fail 'middleware tag changed between architectures'
pass 'collect-images writes the default 13 refs'

printf 'backend only-two-columns\n' > "$TMP/bad.txt"
if bash "$ROOT/scripts/make-bundle.sh" --version 3.1.0 --arch amd64 --images-file "$TMP/bad.txt" --docker-dir "$ROOT/docker" --out "$TMP/out" --dry-run >"$TMP/bad.err" 2>&1; then
  fail 'two-column images.txt was accepted'
fi
grep -q '三列' "$TMP/bad.err" || fail 'column error was not reported'
pass 'make-bundle rejects a row that is not env, service, ref'

mkdir -p "$TMP/bin" "$TMP/docker"
printf 'install\n' > "$TMP/docker/install.sh"
printf '%s backend cr.dataelem.com/dataelement/bisheng-backend:v3.1.0\n' BISHENG_BACKEND_IMAGE > "$TMP/images.txt"
cat > "$TMP/bin/docker" <<'EOF'
#!/bin/bash
set -euo pipefail
if [[ "$1" == pull ]]; then exit 0; fi
if [[ "$1" == image && "$2" == inspect ]]; then
  ref="${@: -1}"
  repo="${ref%:*}"
  if [[ "$4" == *RepoDigests* ]]; then
    if [[ "${FAKE_DIGESTS:-}" == none ]]; then exit 0; fi
    printf 'mirror.example/other@sha256:wrong\n'
    printf '%s@sha256:right\n' "$repo"
    exit 0
  fi
  printf '%s\n' "${FAKE_ARCH:-linux/amd64}"
  exit 0
fi
if [[ "$1" == save && "$2" == -o ]]; then printf 'saved\n' > "$3"; exit 0; fi
printf 'unexpected docker %s\n' "$*" >&2
exit 9
EOF
cat > "$TMP/bin/zstd" <<'EOF'
#!/bin/bash
out=""
prev=""
for arg in "$@"; do
  if [[ "$prev" == -o ]]; then out="$arg"; fi
  prev="$arg"
done
for arg in "$@"; do
  [[ "$arg" == -* || "$arg" == "$out" ]] && continue
  cp "$arg" "$out"
  exit 0
done
exit 1
EOF
chmod +x "$TMP/bin/docker" "$TMP/bin/zstd"

PATH="$TMP/bin:$PATH" GIT_COMMIT=abc123 GIT_REF=refs/tags/v3.1.0 CI_PROVIDER=local \
  bash "$ROOT/scripts/make-bundle.sh" --version 3.1.0 --arch amd64 \
  --images-file "$TMP/images.txt" --docker-dir "$TMP/docker" --out "$TMP/dist" --compress zstd --split-size 2G
python3 - "$TMP/dist/manifest-bisheng-offline-3.1.0-amd64.json" <<'PY'
import json, sys
manifest = json.load(open(sys.argv[1], encoding="utf-8"))
image = manifest["images"][0]
assert image["env"] == "BISHENG_BACKEND_IMAGE", image
assert image["service"] == "backend", image
assert image["ref"].endswith(":v3.1.0"), image
assert image["digest"] == "sha256:right", image
assert manifest["git_commit"] == "abc123"
assert "tar xzf docker.tar.gz" in manifest["notes"]
assert manifest["files"][0]["name"] == "images.tar.zst"
PY
tar -tf "$TMP/dist/bisheng-offline-3.1.0-amd64.tar" | grep -qx 'bisheng-offline-3.1.0-amd64/images.tar.zst'
tar -tf "$TMP/dist/bisheng-offline-3.1.0-amd64.tar" | grep -qx 'bisheng-offline-3.1.0-amd64/docker.tar.gz'
pass 'make-bundle records the matching RepoDigest and packs one image archive'

if PATH="$TMP/bin:$PATH" FAKE_ARCH=linux/arm64 bash "$ROOT/scripts/make-bundle.sh" --version 3.1.0 --arch amd64 \
  --images-file "$TMP/images.txt" --docker-dir "$TMP/docker" --out "$TMP/arch" --compress zstd >"$TMP/arch.err" 2>&1; then
  fail 'architecture mismatch was accepted'
fi
grep -q '架构' "$TMP/arch.err" || fail 'architecture mismatch was not explained'
pass 'make-bundle fails when the pulled image architecture differs'

mkdir -p "$TMP/upload"
printf 'bundle-v1\n' > "$TMP/upload/bisheng-offline-3.1.0-amd64.tar"
printf '{}\n' > "$TMP/upload/manifest-bisheng-offline-3.1.0-amd64.json"
printf 'abc  images.tar.zst\n' > "$TMP/upload/SHA256SUMS-bisheng-offline-3.1.0-amd64"
printf 'parts\n' > "$TMP/upload/SHA256SUMS-bisheng-offline-3.1.0-amd64.parts"
python3 - "$TMP/store" "$TMP/port" <<'PY' &
import os, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
store, portfile = sys.argv[1], sys.argv[2]
os.makedirs(store, exist_ok=True)

class Handler(BaseHTTPRequestHandler):
    def path_file(self):
        marker = "/repository/raw-hosted/"
        rel = self.path.split(marker, 1)[1]
        return os.path.join(store, rel)

    def do_GET(self):
        path = self.path_file()
        if not os.path.isfile(path):
            self.send_response(404)
            self.end_headers()
            return
        data = open(path, "rb").read()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_PUT(self):
        path = self.path_file()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        size = int(self.headers.get("Content-Length", "0"))
        data = self.rfile.read(size)
        open(path, "wb").write(data)
        with open(os.path.join(store, "puts.log"), "a") as handle:
            handle.write(self.path + "\n")
        self.send_response(201)
        self.end_headers()

    def log_message(self, fmt, *args):
        return

server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
with open(portfile, "w") as handle:
    handle.write(str(server.server_address[1]))
server.serve_forever()
PY
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true; rm -rf -- "$TMP"' EXIT
for _ in 1 2 3 4 5 6 7 8 9 10; do
  [[ -s "$TMP/port" ]] && break
  sleep 0.1
done
port="$(cat "$TMP/port")"
[[ -n "$port" ]] || fail 'upload server did not start'
upload() {
  NEXUS_USER=ci NEXUS_PASS=secret bash "$ROOT/scripts/nexus-upload.sh" \
    --dir "$TMP/upload" --version 3.1.0 --arch amd64 \
    --base-url "http://127.0.0.1:${port}" --repo raw-hosted \
    --method put --verify sha256 --update-latest
}
upload
python3 - "$TMP/upload/latest-amd64.json" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert "tar xzf docker.tar.gz" in payload["usage"]
assert any(item["name"] == "bisheng-offline-3.1.0-amd64.tar" for item in payload["files"])
assert not any(item["name"].endswith(".parts") for item in payload["files"])
PY
puts="$(grep -c 'bisheng-offline-3.1.0-amd64.tar$' "$TMP/store/puts.log")"
[[ "$puts" -eq 1 ]] || fail "first upload wrote the tar ${puts} times"
upload
puts="$(grep -c 'bisheng-offline-3.1.0-amd64.tar$' "$TMP/store/puts.log")"
[[ "$puts" -eq 1 ]] || fail 'identical sha256 was uploaded again'
cp "$TMP/upload/latest-amd64.json" "$TMP/latest-before"
printf 'bundle-v2\n' > "$TMP/upload/bisheng-offline-3.1.0-amd64.tar"
if upload >"$TMP/mismatch.err" 2>&1; then fail 'different sha256 was allowed to overwrite'; fi
grep -q '不覆盖' "$TMP/mismatch.err" || fail 'overwrite refusal was not explained'
cmp "$TMP/store/deploy/bisheng/3.1.0/amd64/bisheng-offline-3.1.0-amd64.tar" <(printf 'bundle-v1\n') || fail 'remote tar changed'
cmp "$TMP/upload/latest-amd64.json" "$TMP/latest-before" || fail 'latest pointer changed after a rejected upload'
pass 'nexus upload skips an identical file and refuses a different sha256'

if NEXUS_USER=ci NEXUS_PASS=secret bash "$ROOT/scripts/notify-lark.sh" >"$TMP/notify.err" 2>&1; then
  grep -q '未配置' "$TMP/notify.err" || fail 'missing webhook was silent'
else
  fail 'notify-lark changed the job result'
fi
pass 'notify-lark does not fail the job when the webhook is unset'

printf '\noffline bundle checks passed.\n'
