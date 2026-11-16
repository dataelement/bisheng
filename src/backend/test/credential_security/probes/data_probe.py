"""AC-52: controlled sentinel records using the actual backend runtime config."""

import io
import os
from pathlib import Path

from sqlalchemy import text

from bisheng.core.config import credential_rotation_native as n
from bisheng.core.config.credential_loader import load_config, validate_runtime

EXPECTED_OWNER = os.environ.get("BISHENG_ROTATION_EXPECTED_OWNER", "rotation-acceptance-166")

if (
    os.environ.get("BISHENG_ROTATION_BUSINESS_DISPOSABLE") != "true"
    or EXPECTED_OWNER not in {"rotation-acceptance-166", "rotation-acceptance-166-sealed-v2"}
    or Path("/app/data/.credential-acceptance-owner").read_text().strip() != EXPECTED_OWNER
):
    raise SystemExit("explicit disposable fixture ownership required")

s = validate_runtime(load_config("/app/bisheng/config.yaml").data)
mode = os.environ.get("MODE", "verify")
with n._mysql(s) as c:
    if mode == "seed":
        c.execute(text("CREATE TABLE IF NOT EXISTS rotation_acceptance (id INT PRIMARY KEY, marker VARCHAR(64))"))
        c.execute(
            text(
                "INSERT INTO rotation_acceptance VALUES (1,'preserved-record') ON DUPLICATE KEY UPDATE marker='preserved-record'"
            )
        )
        c.commit()
    assert c.execute(text("SELECT marker FROM rotation_acceptance WHERE id=1")).scalar_one() == "preserved-record"
with n._redis(s) as c:
    if mode == "seed":
        c.set("rotation-acceptance", "preserved-record")
    assert c.get("rotation-acceptance") == b"preserved-record"
with n._minio(s) as c:
    if mode == "seed":
        if not c.bucket_exists("rotation-acceptance"):
            c.make_bucket("rotation-acceptance")
        c.put_object("rotation-acceptance", "record", io.BytesIO(b"preserved-record"), 16)
    r = c.get_object("rotation-acceptance", "record")
    try:
        assert r.read() == b"preserved-record"
    finally:
        r.close()
        r.release_conn()
with n._es(s, "elasticsearch") as c:
    if mode == "seed":
        c.index(index="rotation-acceptance", id="1", document={"marker": "preserved-record"}, refresh=True)
    assert c.get(index="rotation-acceptance", id="1")["_source"]["marker"] == "preserved-record"
with n._milvus(s) as c:
    if mode == "seed":
        if not c.has_collection("rotation_acceptance"):
            c.create_collection(collection_name="rotation_acceptance", dimension=2)
        c.insert(
            collection_name="rotation_acceptance", data=[{"id": 1, "vector": [0.1, 0.2], "marker": "preserved-record"}]
        )
        c.flush(collection_name="rotation_acceptance")
    rows = c.query(
        collection_name="rotation_acceptance", filter="id == 1", output_fields=["marker"], consistency_level="Strong"
    )
    assert rows[0]["marker"] == "preserved-record"
print("all five sentinel records preserved")
