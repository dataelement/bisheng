"""Wake up a registered manager; all authoritative inputs remain in platform SQL."""

import httpx

from bisheng.app_runtime.domain.services.runtime_protocol import canonical_json, signed_headers
from bisheng.common.errcode.app_factory import AppOrchestratorUnavailableError
from bisheng.common.services.config_service import settings


class RuntimeControlClient:
    async def wakeup(self, operation_id):
        cfg = settings.app_runtime
        path = "/v2/operations"
        body = canonical_json({"operation_id": operation_id})
        headers = signed_headers(
            "POST", path, body, key_id=cfg.runtime_control_key_id, secret=cfg.runtime_control_secret
        )
        headers["Content-Type"] = "application/json"
        try:
            async with httpx.AsyncClient(timeout=15, trust_env=False, follow_redirects=False) as client:
                response = await client.post(cfg.manager_base_url.rstrip("/") + path, content=body, headers=headers)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            # No replay of the command: manager's durable node-plan polling also wakes it.
            raise AppOrchestratorUnavailableError(msg="运行管理器暂不可用, 操作已登记, 可查询后重试") from exc

    async def inventory(self):
        cfg = settings.app_runtime
        path = "/v2/upgrade/inventory"
        headers = signed_headers("GET", path, b"", key_id=cfg.runtime_control_key_id, secret=cfg.runtime_control_secret)
        async with httpx.AsyncClient(timeout=30, trust_env=False, follow_redirects=False) as client:
            response = await client.get(cfg.manager_base_url.rstrip("/") + path, headers=headers)
        response.raise_for_status()
        return response.json()
