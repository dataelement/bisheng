"""Bounded read-only model discovery for the production batch CLI.

OpenFGA lists models newest first. Request only page_size=1, never model history.
Protocol: https://github.com/openfga/openfga/blob/main/pkg/storage/storage.go
"""

from bisheng.common.services.config_service import settings
from bisheng.core.openfga.authorization_model_f048 import authorization_model_checksum, build_authorization_model_f048
from bisheng.core.openfga.discovery import OpenFGARuntimePin, normalize_authorization_model
from bisheng.permission.domain.services.department_recovery_plan import RecoveryRuntimeError


async def discover_batch_model(client, cache):
    async def read(path, params=None):
        response = await client.get(path, params=params)
        response.raise_for_status()
        if len(response.content) > 8 * 1024 * 1024:
            raise RecoveryRuntimeError("MODEL_DISCOVERY_RESPONSE_TOO_LARGE")
        value = response.json()
        if not isinstance(value, dict):
            raise RecoveryRuntimeError("MODEL_DISCOVERY_RESPONSE_INVALID")
        return value

    configuration = settings.openfga
    if configuration.force_write_model:
        raise RecoveryRuntimeError("MODEL_AUTO_WRITE_FORBIDDEN")
    payload = await read("/stores", {"name": configuration.store_name, "page_size": 2})
    matches = [row for row in payload.get("stores", []) if row.get("name") == configuration.store_name]
    if len(matches) != 1 or not matches[0].get("id"):
        raise RecoveryRuntimeError("BATCH_STORE_MISSING_OR_AMBIGUOUS")
    store = matches[0]["id"]
    payload = await read(f"/stores/{store}/authorization-models", {"page_size": 1})
    models = payload.get("authorization_models", payload.get("authorization_model_ids", []))
    if not isinstance(models, list) or len(models) != 1:
        raise RecoveryRuntimeError("BATCH_LATEST_MODEL_RESPONSE_INVALID")
    latest = models[0]
    identity = latest.get("id", latest.get("authorization_model_id")) if isinstance(latest, dict) else latest
    if not isinstance(identity, str) or not identity:
        raise RecoveryRuntimeError("BATCH_LATEST_MODEL_ID_INVALID")
    key = store, identity
    if isinstance(latest, dict) and "type_definitions" in latest:
        model = normalize_authorization_model(latest)
    elif key in cache:
        model = cache[key]
    else:
        model = normalize_authorization_model(await read(f"/stores/{store}/authorization-models/{identity}"))
    digest = authorization_model_checksum(model)
    if digest != authorization_model_checksum(build_authorization_model_f048()):
        raise RecoveryRuntimeError("BATCH_LATEST_MODEL_CHECKSUM_MISMATCH")
    cache.clear()
    cache[key] = model
    return OpenFGARuntimePin(store_id=store, model_id=identity, model_checksum=digest)
