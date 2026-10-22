#!/usr/bin/env bash
# Native release builder. Publishing requires an explicit opt-in and a new tag.
set -euo pipefail
: "${RUNTIME_RELEASE:?set a new release identifier}"
: "${TARGET_ARCH:?amd64 or arm64}"
RUNTIME_PUBLISH="${RUNTIME_PUBLISH:-0}"
RUNTIME_IMAGE_NAMESPACE="${RUNTIME_IMAGE_NAMESPACE:-dataelement}"
[[ "$RUNTIME_RELEASE" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,100}$ ]] || exit 64
[[ "$TARGET_ARCH" == amd64 || "$TARGET_ARCH" == arm64 ]] || exit 64
[[ "$RUNTIME_PUBLISH" == 0 || "$RUNTIME_PUBLISH" == 1 ]] || exit 64
[[ "$RUNTIME_IMAGE_NAMESPACE" =~ ^[A-Za-z0-9][A-Za-z0-9./:_-]+$ ]] || exit 64
if [[ "$RUNTIME_PUBLISH" == 1 && -n "$(git status --porcelain)" ]]; then
  echo 'Publishing requires a clean checkout at the recorded source revision' >&2; exit 1
fi
source_revision="$(git rev-parse HEAD)"
case "$(uname -m)" in x86_64|amd64) host_arch=amd64;; aarch64|arm64) host_arch=arm64;; *) exit 64;; esac
engine="$(docker info --format '{{.OSType}}/{{.Architecture}}')"
case "$engine" in linux/x86_64|linux/amd64) engine_arch=amd64;; linux/aarch64|linux/arm64) engine_arch=arm64;; *) echo 'A native Linux Engine is required' >&2; exit 1;; esac
if [[ "$host_arch" != "$TARGET_ARCH" || "$engine_arch" != "$TARGET_ARCH" ]]; then
  echo 'Refusing cross-architecture or emulated release evidence' >&2; exit 1
fi
# Context-named Docker builders share the Engine verified above and its local images.
# Hard-coding "default" breaks native Engines exposed through OrbStack or Desktop.
native_builder="$(docker context show)"
builder_driver="$(docker buildx inspect "$native_builder" | sed -n 's/^Driver:[[:space:]]*//p')"
[[ "$builder_driver" == docker ]] || {
  echo 'The active context must use its native Docker driver builder' >&2; exit 1
}
metadata_dir="dist/runtime-metadata-${TARGET_ARCH}"
inventory="dist/runtime-images-${TARGET_ARCH}.json"
mkdir -p "$metadata_dir"
names=(runtime-manager app-proxy runtime-helper runtime-assembler app-python app-python-preparer app-node app-node-preparer app-static)
image_for() { printf '%s/bisheng-%s:%s-%s' "$RUNTIME_IMAGE_NAMESPACE" "$1" "$RUNTIME_RELEASE" "$TARGET_ARCH"; }
if [[ "$RUNTIME_PUBLISH" == 1 ]]; then
  for name in "${names[@]}"; do
    image="$(image_for "$name")"
    if docker buildx imagetools inspect "$image" >"$metadata_dir/$name.existing" 2>"$metadata_dir/$name.error"; then
      echo "Refusing to overwrite published image: $image" >&2; exit 1
    elif ! grep -Eqi 'manifest unknown|not found|no such manifest' "$metadata_dir/$name.error"; then
      echo "Cannot establish tag absence for $name; publication refused" >&2; exit 1
    fi
  done
fi
build_one() {
  local name="$1" dockerfile="$2" context="$3"
  shift 3
  # The native daemon builder can consume the just-built local manager/helper base.
  docker buildx build --builder "$native_builder" --platform "linux/$TARGET_ARCH" --provenance=false --load \
    --label "org.opencontainers.image.revision=$source_revision" \
    --label "org.opencontainers.image.version=$RUNTIME_RELEASE" \
    --file "$dockerfile" --tag "$(image_for "$name")" "$@" "$context"
}
build_one runtime-manager src/runtime-manager/Dockerfile src/runtime-manager
build_one app-proxy src/app-proxy/Dockerfile src/app-proxy
build_one app-python src/app-runtime/python3.11/Dockerfile . --target runtime
build_one app-python-preparer src/app-runtime/python3.11/Dockerfile . --target preparer
build_one app-node src/app-runtime/node20/Dockerfile . --target runtime
build_one app-node-preparer src/app-runtime/node20/Dockerfile . --target preparer
build_one app-static src/app-runtime/static/Dockerfile . --target runtime
build_one runtime-helper src/runtime-manager/Dockerfile.helper . \
  --build-arg MANAGER_IMAGE="$(image_for runtime-manager)" \
  --build-arg NODE_IMAGE="$(image_for app-node)" \
  --build-arg PYTHON_PREPARER_IMAGE="$(image_for app-python-preparer)"
build_one runtime-assembler src/runtime-manager/Dockerfile.assembler . --build-arg HELPER_IMAGE="$(image_for runtime-helper)"

shadow="$(mktemp -d)"
trap 'rm -rf "$shadow"' EXIT
printf 'raise RuntimeError("application shadow must not be imported")\n' >"$shadow/runtime_manager.py"
for name in "${names[@]}"; do
  image="$(image_for "$name")"
  machine="$(docker run --rm --network none --read-only --tmpfs /tmp --entrypoint uname "$image" -m)"
  case "$machine" in x86_64|amd64) image_arch=amd64;; aarch64|arm64) image_arch=arm64;; *) exit 1;; esac
  [[ "$image_arch" == "$TARGET_ARCH" ]] || { echo 'Native image execution mismatch' >&2; exit 1; }
  common=(--rm --network none --read-only --tmpfs /tmp:rw,nosuid,nodev,size=256m --cap-drop ALL --security-opt no-new-privileges:true)
  case "$name" in
    runtime-helper|runtime-assembler)
      docker run "${common[@]}" --workdir /smoke --env PYTHONPATH=/smoke \
        --mount "type=bind,src=$shadow,dst=/smoke,readonly" --entrypoint python "$image" -I -c \
        'import os,sys,sysconfig,importlib,pathlib,tempfile; assert sys.flags.isolated == 1 and os.getuid() == 10001; modules=[importlib.import_module("runtime_manager."+name) for name in ("k8s_helper","k8s_prepare","k8s_data_helper","k8s_capabilities","oci_assembler")]; assert all(pathlib.Path(m.__file__).is_relative_to(sysconfig.get_paths()["purelib"]) for m in modules); from runtime_manager.k8s_capabilities import storage_checks; assert all(storage_checks("/tmp", require_filesystem=False).values()); assert not os.access("/",os.W_OK)'
      # Exercise the production fixed-path resolver, not just import/version checks.
      # No credential, application execution or network is allowed in this smoke.
      docker run "${common[@]}" -i --entrypoint python "$image" -I - <<'PY_RESOLVE'
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from runtime_manager.k8s_helper import resolve_download

os.environ.update({"PIP_NO_INDEX": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1", "UV_OFFLINE": "1", "npm_config_offline": "true"})
assert Path("/opt/bisheng/prepare.py").is_file()
assert list(Path("/opt/bisheng/wheelhouse").glob("bisheng_sdk-0.1.1-*.whl"))
assert Path("/usr/share/licenses/node/Node.LICENSE").is_file()
assert Path("/usr/share/licenses/node/npm.LICENSE").is_file()

with TemporaryDirectory(prefix="native-resolve-") as temporary:
    root = Path(temporary)

    def resolve(name, language):
        source, offline, output = [root / name / kind for kind in ("source", "offline", "output")]
        source.mkdir(parents=True)
        offline.mkdir()
        document = {"profile": {"language": language}, "delivery": {"dependencies": {}}}
        return document, source, offline, output

    document, source, offline, output = resolve("requirements", "python3.11")
    (source / "requirements.txt").write_text("bisheng-sdk==0.1.1\nfastapi==0.115.14\nuvicorn==0.35.0\n")
    resolve_download(document, source, offline, output)
    assert list((output / "wheels").glob("bisheng_sdk-0.1.1-*.whl"))
    assert list((output / "wheels").glob("httpx-*.whl"))

    document, source, offline, output = resolve("uv-lock", "python3.11")
    (source / "pyproject.toml").write_text('[project]\nname="resolve-smoke"\nversion="0.0.0"\nrequires-python=">=3.11"\ndependencies=[]\n')
    (source / "uv.lock").write_text('version = 1\nrevision = 2\nrequires-python = ">=3.11"\n[[package]]\nname = "resolve-smoke"\nversion = "0.0.0"\nsource = { virtual = "." }\n')
    resolve_download(document, source, offline, output)
    assert (output / "uv-requirements.txt").is_file()

    for language in ("node20", "static"):
        document, source, offline, output = resolve(language, language)
        project = source if language == "node20" else source / "frontend"
        project.mkdir(exist_ok=True)
        marker = root / (language + "-application-executed")
        hook = "node -e " + json.dumps("require('fs').writeFileSync(" + json.dumps(str(marker)) + ", 'unsafe')")
        (project / "package.json").write_text(json.dumps({
            "name": "resolve-smoke", "version": "0.0.0", "private": True,
            "scripts": dict.fromkeys(("preinstall", "install", "postinstall"), hook),
            "dependencies": {},
        }))
        resolve_download(document, source, offline, output)
        location = "root" if language == "node20" else "frontend"
        assert (output / "npm" / location / "package-lock.json").is_file()
        assert not marker.exists()
PY_RESOLVE
      if [[ "$name" == runtime-assembler ]]; then
        docker run "${common[@]}" --entrypoint crane "$image" version | grep -Fx 'v0.22.1'
        docker run "${common[@]}" --entrypoint python "$image" -I -c \
          'from pathlib import Path; p=Path("/usr/share/licenses/crane"); assert (p/"Go.LICENSE").is_file() and (p/"go.sum").is_file() and (p/"modules.json").is_file(); assert list((p/"modules").rglob("LICENSE*"))'
      fi;;
    runtime-manager)
      docker run "${common[@]}" --entrypoint python "$image" -c 'import runtime_manager.main,runtime_manager.egress_proxy,runtime_manager.k8s_admission';;
    app-proxy)
      docker run "${common[@]}" --entrypoint python "$image" -c 'import app_proxy.main';;
    app-python)
      docker run "${common[@]}" --entrypoint python "$image" -c 'import os,bisheng_sdk,fastapi,uvicorn; assert os.getuid()==10001';;
    app-python-preparer)
      docker run "${common[@]}" --entrypoint python "$image" -c 'import os,venv; from pathlib import Path; assert os.getuid()==10001; assert (Path("/opt/bisheng/prepare.py")).is_file(); assert list(Path("/opt/bisheng/wheelhouse").glob("hatchling-*.whl"))';;
    app-node)
      docker run "${common[@]}" --entrypoint node "$image" -e 'if(process.versions.node.split(".")[0]!=="20"||process.getuid()!==10001)process.exit(1)';;
    app-node-preparer)
      docker run "${common[@]}" --entrypoint python "$image" -c 'import os; from pathlib import Path; assert os.getuid()==10001; assert Path("/opt/bisheng/prepare.py").is_file()';;
    app-static)
      docker run "${common[@]}" "$image" nginx -t
      # Keep the existing platform nginx configuration compatibility smoke.
      docker run --rm --user 0:0 --network none --read-only --tmpfs /tmp --tmpfs /var/cache/nginx --tmpfs /var/run \
        --add-host backend:127.0.0.1 --add-host minio:127.0.0.1 \
        --mount "type=bind,src=$PWD/docker/nginx/conf.d/default.conf,dst=/etc/nginx/conf.d/default.conf,readonly" \
        --entrypoint nginx "$image" -t;;
  esac
done
python3 - "$metadata_dir/native-smoke.json" "${names[@]}" <<'PY'
import json,sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps(sys.argv[2:]))
PY
# No image is published until every native build and isolated smoke has succeeded.
for name in "${names[@]}"; do
  image="$(image_for "$name")"
  if [[ "$RUNTIME_PUBLISH" == 1 ]]; then docker push "$image"; fi
  docker image inspect "$image" >"$metadata_dir/$name.json"
done
write_inventory() {
  python3 src/runtime-manager/runtime_manager/image_catalog.py inventory \
    --metadata-dir "$metadata_dir" --platform "linux/$TARGET_ARCH" --native-arch "$engine_arch" \
    --release "$RUNTIME_RELEASE" --source-revision "$source_revision" --output "$inventory" "$@"
}
if [[ "$RUNTIME_PUBLISH" == 1 ]]; then write_inventory --published; else write_inventory; fi
printf 'Native inventory: %s (published=%s)\n' "$inventory" "$RUNTIME_PUBLISH"
