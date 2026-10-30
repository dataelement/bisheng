#!/usr/bin/env bash
# Mirror the exact native images already verified by the release builder.
set -euo pipefail
: "${RUNTIME_RELEASE:?set the release identifier}"
: "${TARGET_ARCH:?amd64 or arm64}"
[[ "$TARGET_ARCH" == amd64 || "$TARGET_ARCH" == arm64 ]] || exit 64
metadata_dir="dist/runtime-metadata-cr-${TARGET_ARCH}"
mkdir -p "$metadata_dir" dist/cr
PYTHONPATH=src/runtime-manager python3 - > "$metadata_dir/targets.tsv" <<'PY'
import json
import os
import subprocess
from pathlib import Path
from runtime_manager.image_catalog import DIGEST, IMAGE_NAMES, RELEASE

release, arch = os.environ['RUNTIME_RELEASE'], os.environ['TARGET_ARCH']
assert RELEASE.fullmatch(release)
inventory = json.loads(Path(f'dist/runtime-images-{arch}.json').read_text())
assert inventory['schema_version'] == 2 and inventory['native_arch'] == arch
assert inventory['state'] == 'published-native-verified'
assert inventory['release'] == release and inventory['platform'] == f'linux/{arch}'
assert inventory['source_revision'] == subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
assert set(inventory['images']) == set(IMAGE_NAMES)
for name in IMAGE_NAMES:
    image = inventory['images'][name]
    tag = f'dataelement/bisheng-{name}:{release}-{arch}'
    assert image['tag'] == tag and image['native_smoke'] and image['platform'] == f'linux/{arch}'
    assert DIGEST.fullmatch(image['image_id'])
    assert image['image'].startswith(tag.split(':')[0] + '@sha256:')
    print(name, image['image_id'], 'cr.dataelem.com/' + tag, sep='\t')
PY
# Refuse existing tags or registry/authentication uncertainty before any CR push.
while IFS=$'\t' read -r name image_id target; do
  if docker buildx imagetools inspect "$target" > "$metadata_dir/$name.existing" 2> "$metadata_dir/$name.error"; then
    echo "Refusing to overwrite published image: $target" >&2; exit 1
  elif grep -Eqi 'unauthorized|forbidden|denied|authentication|authorization' "$metadata_dir/$name.error" || \
    ! grep -Eqi 'manifest unknown|not found|no such manifest' "$metadata_dir/$name.error"; then
    echo "Cannot establish tag absence for $target; publication refused" >&2; exit 1
  fi
done < "$metadata_dir/targets.tsv"
while IFS=$'\t' read -r name image_id target; do
  # Use the frozen local image ID, never rebuild or resolve a mutable source tag.
  docker tag "$image_id" "$target"
  docker push "$target"
  docker image inspect "$target" | python3 -c '
import json,sys
metadata=json.load(sys.stdin)
# The image has both Hub and CR tags; inventory must select only this registry.
metadata[0]["RepoTags"]=[sys.argv[1]]
json.dump(metadata,sys.stdout)
' "$target" > "$metadata_dir/$name.json"
done < "$metadata_dir/targets.tsv"
cp "dist/runtime-metadata-${TARGET_ARCH}/native-smoke.json" "$metadata_dir/native-smoke.json"
python3 src/runtime-manager/runtime_manager/image_catalog.py inventory \
  --metadata-dir "$metadata_dir" --platform "linux/$TARGET_ARCH" --native-arch "$TARGET_ARCH" \
  --release "$RUNTIME_RELEASE" --source-revision "$(git rev-parse HEAD)" --published \
  --output "dist/cr/runtime-images-${TARGET_ARCH}.json"
