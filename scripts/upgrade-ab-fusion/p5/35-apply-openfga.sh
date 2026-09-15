#!/usr/bin/env bash
# 把本批 owner / 组 manager / 角色 / 部门授权 Tuple 写入 A 的 OpenFGA. 不改 A 原空间 Tuple.
set -euo pipefail
STEP="p5.35-openfga"
APPLY="${APPLY:-0}"
ACTION="${ACTION:-write}"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
load_env
# shellcheck disable=SC1091
source "${PACK_ROOT}/lib/fusion_remote.sh"

: "${A_OPENFGA_URL:=http://127.0.0.1:8080}"
: "${OPENFGA_STORE_NAME:=bisheng}"

tuples="${LOG_DIR}/p5/openfga.tuples.json"
[[ -f "${tuples}" ]] || die "缺少 ${tuples}, 先跑 p5/30-apply.sh"

count="$(
  python3 - "${tuples}" "${PACK_ROOT}" <<'PY'
import json, sys
from pathlib import Path
pack = Path(sys.argv[2])
sys.path.insert(0, str(pack))
from fusion.openfga_tuples import assert_no_a_space_objects
rows = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
spaces = set()
p = Path(sys.argv[1]).parent / "a-space-ids.txt"
if p.exists():
    for ln in p.read_text(encoding="utf-8").split():
        try:
            spaces.add(int(ln))
        except ValueError:
            pass
assert_no_a_space_objects(rows, spaces)
print(len(rows))
PY
)"
log "OpenFGA tuples=${count} action=${ACTION} APPLY=${APPLY}"

if [[ "${count}" == "0" ]]; then
  ledger "${STEP}" "OK" "empty"
  echo "OK ${STEP} tuples=0"
  exit 0
fi

if [[ "${APPLY}" != "1" ]]; then
  ledger "${STEP}" "OK" "APPLY=0 tuples=${count}"
  echo "OK ${STEP} APPLY=0 tuples=${count}"
  exit 0
fi

store_json="$(fusion_ssh_a curl -fsS "${A_OPENFGA_URL}/stores")" \
  || die "读 A OpenFGA /stores 失败, 检查 A_OPENFGA_URL=${A_OPENFGA_URL}"
store_id="$(python3 -c "
import json,sys
data=json.loads(sys.argv[1])
name=sys.argv[2]
stores=data.get('stores') or []
hit=next((s for s in stores if s.get('name')==name), None)
if not hit:
    raise SystemExit('no store '+name)
print(hit['id'])
" "${store_json}" "${OPENFGA_STORE_NAME}")"
[[ -n "${store_id}" ]] || die "A OpenFGA 没有 store ${OPENFGA_STORE_NAME}"

models_json="$(fusion_ssh_a curl -fsS "${A_OPENFGA_URL}/stores/${store_id}/authorization-models")"
model_id="$(python3 -c "
import json,sys
data=json.loads(sys.argv[1])
models=data.get('authorization_models') or data.get('authorizationModels') or []
if not models:
    raise SystemExit('no authorization model')
print(models[0]['id'])
" "${models_json}")"

python3 - "${tuples}" "${PACK_ROOT}" "${ACTION}" "${model_id}" <<'PY'
import json, sys
from pathlib import Path
pack = Path(sys.argv[2])
sys.path.insert(0, str(pack))
from fusion.openfga_tuples import chunk_tuples, delete_body, write_body
rows = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
action = sys.argv[3]
model_id = sys.argv[4]
fn = delete_body if action == "delete" else write_body
outdir = Path(sys.argv[1]).parent / "openfga-chunks"
if outdir.exists():
    for old in outdir.glob("*.json"):
        old.unlink()
outdir.mkdir(parents=True, exist_ok=True)
for i, chunk in enumerate(chunk_tuples(rows), start=1):
    (outdir / f"{i:04d}.json").write_text(
        json.dumps(fn(chunk, model_id), ensure_ascii=False), encoding="utf-8"
    )
print(outdir)
PY

chunk_dir="${LOG_DIR}/p5/openfga-chunks"
shopt -s nullglob
for f in "${chunk_dir}"/*.json; do
  fusion_scp_to_a "${f}" /tmp/fusion-fga-chunk.json
  fusion_ssh_a curl -fsS -X POST \
    -H "Content-Type: application/json" \
    --data-binary @/tmp/fusion-fga-chunk.json \
    "${A_OPENFGA_URL}/stores/${store_id}/write" \
    >/dev/null \
    || die "OpenFGA ${ACTION} 失败 store=${store_id} file=$(basename "${f}")"
done

ledger "${STEP}" "OK" "APPLY=1 action=${ACTION} tuples=${count} store=${store_id}"
echo "OK ${STEP} action=${ACTION} tuples=${count} store=${store_id}"
