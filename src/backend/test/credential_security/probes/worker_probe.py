"""AC-51: real Redis broker round trip and actual worker execution, no fake worker."""

import json
import os
import secrets
from pathlib import Path

from celery import Celery

from bisheng.core.config.celery_redis import build_celery_redis_config
from bisheng.core.config.credential_loader import load_config, validate_runtime

EXPECTED_OWNER = os.environ.get("BISHENG_ROTATION_EXPECTED_OWNER", "rotation-acceptance-166")

if (
    os.environ.get("BISHENG_ROTATION_BUSINESS_DISPOSABLE") != "true"
    or EXPECTED_OWNER not in {"rotation-acceptance-166", "rotation-acceptance-166-sealed-v2"}
    or Path("/app/data/.credential-acceptance-owner").read_text().strip() != EXPECTED_OWNER
):
    raise SystemExit("explicit disposable fixture ownership required")

settings = validate_runtime(load_config("/app/bisheng/config.yaml").data)
app = Celery("credential_acceptance")
app.conf.update(build_celery_redis_config(settings.celery_redis_url))
try:
    replies = app.control.ping(timeout=5)
    assert replies and all(v.get("ok") == "pong" for row in replies for v in row.values()), "real worker ping failed"
    task = app.send_task(
        "celery.accumulate",
        args=["credential-acceptance-" + secrets.token_hex(8)],
        queue="celery",
        headers={"tenant_id": 1},
    )
    result = {"ping": True, "workers": len(replies), "task_id": task.id}
    path = Path("/app/data/credential-acceptance/worker-probe.json")
    path.write_text(json.dumps(result))
    path.chmod(0o600)
    print(json.dumps(result))
finally:
    app.close()
