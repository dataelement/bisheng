#!/usr/bin/env bash
# Install the PPTD engine used by the built-in "PPT 制作" skill (bisheng-pptx).
#
# The image build does the same thing (base.Dockerfile + Dockerfile); this script
# is for source deployments. Layout, identical to the image:
#   /opt/pptd-runtime/bin/node           Node (official binary, pinned below)
#   /opt/pptd-runtime/node_modules/      npm deps from package-lock.json
#   /opt/pptd-runtime/engine/            the vendored engine (copy of this directory's dsh-ppt/)
#
# Usage (as root):  bash src/backend/pptd_runtime/install.sh
#   NODE_TARBALL=/path/node-v24.x-linux-x64.tar.xz   use a local tarball (offline sites)
#   NPM_REGISTRY=https://...                         use a mirror for npm ci
# Re-running is safe: Node is replaced only when the version differs, deps are reinstalled
# only when package-lock.json changed, and the engine copy is always refreshed.
set -euo pipefail

NODE_VERSION="${NODE_VERSION:-24.19.0}"
PREFIX="${PPTD_RUNTIME:-/opt/pptd-runtime}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

case "$(uname -m)" in
  x86_64|amd64) ARCH=x64 ;;
  aarch64|arm64) ARCH=arm64 ;;
  *) echo "unsupported architecture: $(uname -m)" >&2; exit 1 ;;
esac

mkdir -p "$PREFIX/bin"

# 1. Node — the code interpreter runs scripts as an unprivileged uid, so Node must live
#    outside /root (nvm installs are unreachable) and be world-readable.
if [ "$("$PREFIX/bin/node" --version 2>/dev/null || true)" != "v$NODE_VERSION" ]; then
  tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
  tarball="${NODE_TARBALL:-}"
  if [ -z "$tarball" ]; then
    tarball="$tmp/node.tar.xz"
    curl -fsSL "https://nodejs.org/dist/v$NODE_VERSION/node-v$NODE_VERSION-linux-$ARCH.tar.xz" -o "$tarball"
  fi
  tar -xJf "$tarball" -C "$tmp"
  rm -rf "$PREFIX/node"
  mv "$tmp"/node-v*-linux-* "$PREFIX/node"
  ln -sf ../node/bin/node "$PREFIX/bin/node"
fi
NODE="$PREFIX/bin/node"
NPM="$PREFIX/node/bin/npm"

# 2. npm deps, pinned by the lock file. The engine stays OUTSIDE node_modules: npm ci
#    deletes anything there that package.json does not list.
if ! cmp -s "$HERE/package-lock.json" "$PREFIX/package-lock.json"; then
  cp "$HERE/package.json" "$HERE/package-lock.json" "$PREFIX/"
  (cd "$PREFIX" && PATH="$PREFIX/node/bin:$PATH" "$NPM" ci --omit=dev --no-audit --no-fund \
      ${NPM_REGISTRY:+--registry "$NPM_REGISTRY"})
fi

# 3. Engine
rm -rf "$PREFIX/engine"
cp -R "$HERE/dsh-ppt" "$PREFIX/engine"
chmod -R a+rX "$PREFIX"

"$NODE" "$PREFIX/engine/lib/bin.js" --help >/dev/null
echo "PPTD engine ready at $PREFIX (node $("$NODE" --version), $ARCH)"
