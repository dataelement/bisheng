#!/usr/bin/env bash
# Native CI release builder. Runtime revisions must never overwrite existing tags.
set -euo pipefail
: "${RUNTIME_RELEASE:?set a new release identifier}"
: "${TARGET_ARCH:?amd64 or arm64}"
[[ "$RUNTIME_RELEASE" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]+$ ]] || exit 64
[[ "$TARGET_ARCH" == amd64 || "$TARGET_ARCH" == arm64 ]] || exit 64
mkdir -p dist
inventory="dist/runtime-images-${TARGET_ARCH}.json"
printf '{"schema_version":1,"platform":"linux/%s","release":"%s","images":{}}\n' "$TARGET_ARCH" "$RUNTIME_RELEASE" >"$inventory"

build_one() {
  local name="$1" dockerfile="$2" context="$3" target="${4:-}" image metadata args=()
  image="dataelement/bisheng-${name}:${RUNTIME_RELEASE}-${TARGET_ARCH}"
  metadata="dist/${name}-${TARGET_ARCH}.json"
  if docker buildx imagetools inspect "$image" >"$metadata.existing" 2>"$metadata.error"; then
    echo "Refusing to overwrite published image: $image" >&2; exit 1
  elif ! rg -qi 'manifest unknown|not found|no such manifest' "$metadata.error"; then
    cat "$metadata.error" >&2; exit 1
  fi
  if [[ -n "$target" ]]; then args+=(--target "$target"); fi
  docker buildx build --platform "linux/$TARGET_ARCH" --provenance=false --load --file "$dockerfile" --tag "$image" "${args[@]}" "$context"
  if [[ "$name" == app-python ]]; then
    docker run --rm --network none --read-only --tmpfs /tmp "$image" python -c 'import bisheng_sdk,fastapi,uvicorn'
  elif [[ "$name" == app-node ]]; then
    docker run --rm --network none --read-only --tmpfs /tmp "$image" node -e 'if(process.versions.node.split(".")[0]!=="20")process.exit(1)'
  elif [[ "$name" == app-static ]]; then
    docker run --rm --network none --read-only --tmpfs /tmp "$image" nginx -t
    docker run --rm --user 0:0 --network none --read-only --tmpfs /tmp --tmpfs /var/cache/nginx --tmpfs /var/run \
      --add-host backend:127.0.0.1 --add-host minio:127.0.0.1 \
      --mount "type=bind,src=$PWD/docker/nginx/conf.d/default.conf,dst=/etc/nginx/conf.d/default.conf,readonly" \
      --entrypoint nginx "$image" -t
  elif [[ "$name" == runtime-manager ]]; then
    docker run --rm --network none --read-only --tmpfs /tmp "$image" python -c 'import runtime_manager.main,runtime_manager.egress_proxy'
  elif [[ "$name" == app-proxy ]]; then
    docker run --rm --network none --read-only --tmpfs /tmp "$image" python -c 'import app_proxy.main'
  fi
  docker push "$image"
  docker image inspect "$image" >"$metadata"
  python3 - "$inventory" "$name" "$image" "$metadata" <<'PY'
import json,sys
path,name,tag,metadata=sys.argv[1:]
doc=json.load(open(path)); image=json.load(open(metadata))[0]
digests=image.get('RepoDigests') or []
if not digests:raise SystemExit('published image digest missing')
doc['images'][name]={'image':digests[0],'image_id':image['Id'],'tag':tag,'platform':doc['platform']}
with open(path,'w') as output:json.dump(doc,output,indent=2)
PY
}

build_one runtime-manager src/runtime-manager/Dockerfile src/runtime-manager
build_one app-proxy src/app-proxy/Dockerfile src/app-proxy
build_one app-python src/app-runtime/python3.11/Dockerfile . runtime
build_one app-python-preparer src/app-runtime/python3.11/Dockerfile . preparer
build_one app-node src/app-runtime/node20/Dockerfile . runtime
build_one app-node-preparer src/app-runtime/node20/Dockerfile . preparer
build_one app-static src/app-runtime/static/Dockerfile . runtime
