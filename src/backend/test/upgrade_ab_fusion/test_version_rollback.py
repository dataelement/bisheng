"""冻结目录检查 / 存储副本指纹."""

from pathlib import Path

from test.upgrade_ab_fusion._packutil import ensure_pack_path

ensure_pack_path()
from fusion.freeze_storage import (
    STORAGE_KEYS,
    storage_gaps,
    tree_inventory,
    write_manifest,
)
from fusion.version_rollback import (
    compose_backend_image,
    dump_has_alembic_revision,
    inspect_freeze_dir,
    pick_freeze_dir,
    sha256_hex,
)


def _write_mysql_freeze(tmp_path: Path, *, dump: str, compose: str, sha: str | None) -> Path:
    root = tmp_path / "20260911124114"
    root.mkdir()
    dump_path = root / "mysql-bisheng.sql"
    dump_path.write_text(dump, encoding="utf-8")
    (root / "docker-compose.yml").write_text(compose, encoding="utf-8")
    (root / "TODO-storage.txt").write_text("need minio\n", encoding="utf-8")
    if sha is None:
        sha = sha256_hex(dump_path)
    (root / "mysql-bisheng.sql.sha256").write_text(sha + "\n", encoding="utf-8")
    return root


def _add_complete_storage(root: Path) -> None:
    storage = {}
    for key in STORAGE_KEYS:
        d = root / "storage" / key
        d.mkdir(parents=True)
        (d / "obj.bin").write_bytes(b"x")
        inv = tree_inventory(d)
        storage[key] = {
            "container": f"c-{key}",
            "container_dest": "/data",
            "live_host": f"/data/{key}",
            "backup_rel": f"storage/{key}",
            "bytes": inv["bytes"],
            "files": inv["files"],
            "list_sha256": inv["list_sha256"],
        }
    write_manifest(
        root,
        {
            "stamp": root.name,
            "complete_storage": True,
            "storage": storage,
        },
    )
    todo = root / "TODO-storage.txt"
    if todo.exists():
        todo.unlink()


_COMPOSE_24 = """
services:
  mysql:
    image: mysql:8.0
  backend:
    image: dataelement/bisheng-backend:v2.4.0
  frontend:
    image: dataelement/bisheng-frontend:v2.4.0
"""

_COMPOSE_22 = """
services:
  backend:
    image: harbor.shougang.com.cn/llmplat/bisheng-backend:v2.2sgv260402-JiTuan
  frontend:
    image: harbor.shougang.com.cn/llmplat/bisheng-frontend:v2.2sgv260402-JiTuan-bak
"""

_DUMP_24 = """
CREATE DATABASE /*!32312 IF NOT EXISTS*/ `bisheng`;
USE `bisheng`;
CREATE TABLE `assistant` (id int);
CREATE TABLE `alembic_version` (`version_num` varchar(32));
LOCK TABLES `assistant` WRITE;
INSERT INTO `assistant` VALUES (1);
UNLOCK TABLES;
"""


def test_pick_requires_stamp(tmp_path: Path):
    try:
        pick_freeze_dir(tmp_path, "")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
    root = tmp_path / "20260911124114"
    root.mkdir()
    assert pick_freeze_dir(tmp_path, "20260911124114") == root.resolve()


def test_inspect_ok_2_4_incomplete(tmp_path: Path):
    root = _write_mysql_freeze(tmp_path, dump=_DUMP_24, compose=_COMPOSE_24, sha=None)
    info = inspect_freeze_dir(root)
    assert info["errors"] == []
    assert info["sha_ok"] is True
    assert info["backend_image"] == "dataelement/bisheng-backend:v2.4.0"
    assert info["has_create_db"] is True
    assert info["complete_storage"] is False
    assert info["incomplete_storage"] is True


def test_inspect_jituan_image_ok_without_v24(tmp_path: Path):
    root = _write_mysql_freeze(tmp_path, dump=_DUMP_24, compose=_COMPOSE_22, sha=None)
    info = inspect_freeze_dir(root)
    assert info["errors"] == []
    assert "v2.2sgv260402-JiTuan" in str(info["backend_image"])
    assert info["complete_storage"] is False


def test_inspect_rejects_bad_sha(tmp_path: Path):
    root = _write_mysql_freeze(
        tmp_path,
        dump=_DUMP_24,
        compose=_COMPOSE_24,
        sha="0" * 64,
    )
    info = inspect_freeze_dir(root)
    assert any("sha256" in e for e in info["errors"])


def test_dump_alembic_revision_detected():
    text = (
        "CREATE DATABASE `bisheng`;\nINSERT INTO `alembic_version` (version_num) VALUES ('f106_fulltext_reconcile');\n"
    )
    assert dump_has_alembic_revision(text) is True
    assert dump_has_alembic_revision(_DUMP_24) is False


def test_compose_backend_image_stops_at_next_service():
    text = """
services:
  backend:
    image: dataelement/bisheng-backend:v2.4.0
  backend_worker:
    image: dataelement/bisheng-backend:v2.5.0-sg
"""
    assert compose_backend_image(text) == "dataelement/bisheng-backend:v2.4.0"


def test_complete_storage_manifest(tmp_path: Path):
    root = _write_mysql_freeze(tmp_path, dump=_DUMP_24, compose=_COMPOSE_22, sha=None)
    _add_complete_storage(root)
    info = inspect_freeze_dir(root)
    assert info["errors"] == []
    assert info["complete_storage"] is True
    assert info["storage_gaps"] == []
    assert storage_gaps(root, None) != []


def test_storage_gap_when_file_count_changes(tmp_path: Path):
    root = _write_mysql_freeze(tmp_path, dump=_DUMP_24, compose=_COMPOSE_22, sha=None)
    _add_complete_storage(root)
    (root / "storage" / "minio" / "extra.bin").write_bytes(b"yy")
    info = inspect_freeze_dir(root)
    assert info["complete_storage"] is False
    assert any("minio" in g for g in info["storage_gaps"])
