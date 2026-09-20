#!/usr/bin/env bash
# 方案 §16.1: 停写入后冻 MySQL + MinIO + Milvus + ES + etcd + compose/config.
# 缺任何一块都 FAIL, 不再用 TODO-storage 当成功.
# hop 靠 logs/p2/current-freeze.txt / BACKUP_STAMP 认这份冻结.
set -euo pipefail
STEP="p2.01-backup"
: "${BACKEND_CONTAINER:=bisheng-backend}"
: "${WORKER_CONTAINER:=bisheng-backend-worker}"
: "${FRONTEND_CONTAINER:=bisheng-frontend}"
: "${GATEWAY_CONTAINER:=bisheng-gateway}"
: "${BEAT_CONTAINER:=bisheng-backend-beat}"
: "${MYSQL_CONTAINER:=bisheng-mysql}"
: "${MYSQL_DB:=bisheng}"
: "${BACKUP_DIR:=/data/upgrade-backups}"
: "${BACKUP_OPERATOR:=}"
# shellcheck disable=SC1091
source "$(cd "$(dirname "$0")/.." && pwd)/lib/common.sh"
# shellcheck source=../lib/freeze_storage.sh
source "$(cd "$(dirname "$0")/.." && pwd)/lib/freeze_storage.sh"
load_env
discover_deployment
preflight_report
assert_data_dir_nonempty "${MYSQL_CONTAINER}" /var/lib/mysql
ledger "${STEP}" "START" ""

stamp="$(date +%Y%m%d%H%M%S)"
dest="${BACKUP_DIR}/${stamp}"
mkdir -p "${dest}/storage"
mkdir -p "${LOG_DIR}/p2"

minio_c="$(find_storage_container minio "bisheng-milvus-minio bisheng-minio" || true)"
es_c="$(find_storage_container elasticsearch "bisheng-es bisheng-elasticsearch" || true)"
etcd_c="$(find_storage_container etcd "bisheng-milvus-etcd" || true)"
milvus_c="$(find_storage_container milvus "bisheng-milvus-standalone" || true)"

[[ -n "${minio_c}" ]] || die "找不到 minio 容器"
[[ -n "${es_c}" ]] || die "找不到 elasticsearch 容器"
[[ -n "${etcd_c}" ]] || die "找不到 etcd 容器"
[[ -n "${milvus_c}" ]] || die "找不到 milvus 容器"

minio_pair="$(storage_host_path "${minio_c}" /minio_data /data /export || true)"
es_pair="$(storage_host_path "${es_c}" /bitnami/elasticsearch/data /usr/share/elasticsearch/data || true)"
etcd_pair="$(storage_host_path "${etcd_c}" /etcd || true)"
milvus_pair="$(storage_host_path "${milvus_c}" /var/lib/milvus || true)"

[[ -n "${minio_pair}" ]] || die "minio 没有可拷的数据目录"
[[ -n "${es_pair}" ]] || die "elasticsearch 没有可拷的数据目录"
[[ -n "${etcd_pair}" ]] || die "etcd 没有可拷的数据目录"
[[ -n "${milvus_pair}" ]] || die "milvus 没有可拷的数据目录"

minio_src="${minio_pair%%$'\t'*}"
minio_dest="${minio_pair#*$'\t'}"
es_src="${es_pair%%$'\t'*}"
es_dest="${es_pair#*$'\t'}"
etcd_src="${etcd_pair%%$'\t'*}"
etcd_dest="${etcd_pair#*$'\t'}"
milvus_src="${milvus_pair%%$'\t'*}"
milvus_dest="${milvus_pair#*$'\t'}"

need=0
for src in "${minio_src}" "${es_src}" "${etcd_src}" "${milvus_src}"; do
  b="$(dir_bytes "${src}")"
  [[ -n "${b}" ]] || die "du 失败: ${src}"
  need=$((need + b))
done
# dump + 余量
need=$((need + 2 * 1024 * 1024 * 1024))
assert_backup_disk "${BACKUP_DIR}" "${need}"

backend_image="$(docker inspect "${BACKEND_CONTAINER}" --format '{{.Config.Image}}' 2>/dev/null || true)"
frontend_image="$(docker inspect "${FRONTEND_CONTAINER}" --format '{{.Config.Image}}' 2>/dev/null || true)"

log "1) 停 API 写入 (mysql 保持; 存储稍后再停)"
docker stop "${FRONTEND_CONTAINER}" "${GATEWAY_CONTAINER}" \
  "${BACKEND_CONTAINER}" "${WORKER_CONTAINER}" "${BEAT_CONTAINER}" 2>/dev/null || true
docker ps --format '{{.Names}} {{.Status}}' | tee "${dest}/containers-after-stop.txt"

log "2) mysqldump"
docker exec "${MYSQL_CONTAINER}" sh -c \
  'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqldump -uroot --single-transaction --routines --triggers --databases '"${MYSQL_DB}" \
  >"${dest}/mysql-${MYSQL_DB}.sql"
sha256_file "${dest}/mysql-${MYSQL_DB}.sql" >"${dest}/mysql-${MYSQL_DB}.sql.sha256"

log "3) 复制 compose 与 config"
for f in ${COMPOSE_CONFIG_FILES[@]+"${COMPOSE_CONFIG_FILES[@]}"}; do
  cp -a "${f}" "${dest}/$(basename "${f}")"
done
resolve_host_file_optional "${BACKEND_CONTAINER}" cfg_host "${CONFIG_YAML_DESTS[@]}"
if [[ -n "${cfg_host}" ]]; then
  cp -a "${cfg_host}" "${dest}/config.yaml"
else
  log "WARN config.yaml 非 bind mount, 冻结目录没有 config.yaml"
fi

docker images --format '{{.Repository}}:{{.Tag}} {{.ID}} {{.Digest}}' \
  >"${dest}/docker-images.txt" || true

log "4) 停 MinIO/Milvus/ES/etcd 后拷数据目录"
docker stop "${milvus_c}" "${minio_c}" "${etcd_c}" "${es_c}" 2>/dev/null || true
copy_tree "${minio_src}" "${dest}/storage/minio"
copy_tree "${milvus_src}" "${dest}/storage/milvus"
copy_tree "${es_src}" "${dest}/storage/elasticsearch"
copy_tree "${etcd_src}" "${dest}/storage/etcd"

meta="${dest}/storage-meta.tsv"
printf 'key\tcontainer\tcontainer_dest\tlive_host\n' >"${meta}"
printf 'minio\t%s\t%s\t%s\n' "${minio_c}" "${minio_dest}" "${minio_src}" >>"${meta}"
printf 'milvus\t%s\t%s\t%s\n' "${milvus_c}" "${milvus_dest}" "${milvus_src}" >>"${meta}"
printf 'elasticsearch\t%s\t%s\t%s\n' "${es_c}" "${es_dest}" "${es_src}" >>"${meta}"
printf 'etcd\t%s\t%s\t%s\n' "${etcd_c}" "${etcd_dest}" "${etcd_src}" >>"${meta}"

python3 - "${PACK_ROOT}" "${dest}" "${stamp}" "${backend_image}" "${frontend_image}" "${BACKUP_OPERATOR}" "${meta}" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

pack, root_s, stamp, be, fe, operator, meta = sys.argv[1:8]
sys.path.insert(0, pack)
from fusion.freeze_storage import STORAGE_KEYS, tree_inventory, write_manifest

root = Path(root_s)
storage = {}
with Path(meta).open(encoding="utf-8") as fh:
    header = fh.readline()
    for line in fh:
        parts = line.rstrip("\n").split("\t")
        if len(parts) != 4:
            continue
        key, container, container_dest, live_host = parts
        rel = f"storage/{key}"
        inv = tree_inventory(root / rel)
        storage[key] = {
            "container": container,
            "container_dest": container_dest,
            "live_host": live_host,
            "backup_rel": rel,
            "bytes": inv["bytes"],
            "files": inv["files"],
            "list_sha256": inv["list_sha256"],
        }
missing = [k for k in STORAGE_KEYS if k not in storage]
if missing:
    raise SystemExit(f"MANIFEST 缺存储项: {missing}")
payload = {
    "stamp": stamp,
    "ts": datetime.now(timezone.utc).astimezone().isoformat(),
    "operator": operator,
    "backend_image": be,
    "frontend_image": fe,
    "mysql_dump": "mysql-bisheng.sql",
    "complete_storage": True,
    "storage": storage,
}
write_manifest(root, payload)
print(json.dumps({"complete_storage": True, "stamp": stamp}, ensure_ascii=False))
PY

inspect_rc=0
python3 - "${PACK_ROOT}" "${dest}" <<'PY' || inspect_rc=$?
import json
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from fusion.version_rollback import inspect_freeze_dir

info = inspect_freeze_dir(Path(sys.argv[2]))
Path(sys.argv[2], "inspect.json").write_text(
    json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
if info["errors"] or not info["complete_storage"]:
    print(json.dumps(info, ensure_ascii=False, indent=2), file=sys.stderr)
    raise SystemExit("冻结自检失败")
print("freeze_ok")
PY

log "5) 再拉起存储, 方便后续 hop"
docker start "${etcd_c}" "${minio_c}" "${es_c}" "${milvus_c}" 2>/dev/null || true
[[ "${inspect_rc}" -eq 0 ]] || die "冻结自检失败, 见 ${dest}/inspect.json"

printf '%s\n' "${stamp}" >"${LOG_DIR}/p2/current-freeze.txt"
ledger "${STEP}" "OK" "${dest}"
log "备份目录 ${dest}"
log "完整冻结 stamp=${stamp} (已写入 ${LOG_DIR}/p2/current-freeze.txt)"
echo "OK ${STEP} stamp=${stamp} dir=${dest}"
