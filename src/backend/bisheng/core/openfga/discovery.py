"""OpenFGA Store and authorization-model discovery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from bisheng.common.errcode.permission import AuthorizationModelMismatchError
from bisheng.core.config.openfga import OpenFGAConf
from bisheng.core.openfga.authorization_model_f048 import (
    authorization_model_checksum,
)


@dataclass(frozen=True, slots=True)
class OpenFGARuntimePin:
    """One concrete Store/model pair resolved from the OpenFGA API."""

    store_id: str
    model_id: str
    model_checksum: str


def normalize_authorization_model(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize get-model responses before calculating the release checksum."""

    raw_model = payload.get("authorization_model", payload)
    model = {
        "schema_version": raw_model.get("schema_version"),
        "type_definitions": raw_model.get("type_definitions"),
    }
    if raw_model.get("conditions"):
        model["conditions"] = raw_model["conditions"]
    if not model["schema_version"] or not isinstance(
        model["type_definitions"],
        list,
    ):
        raise AuthorizationModelMismatchError(
            msg="OpenFGA authorization model payload is incomplete"
        )
    return model


async def discover_openfga_runtime(
    config: OpenFGAConf,
    *,
    expected_model: dict[str, Any] | None,
    allow_bootstrap: bool,
    required_store_id: str | None = None,
    required_model_id: str | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> OpenFGARuntimePin:
    """Resolve the unique named Store and one concrete authorization model.

    Online processes select the newest model, then validate its checksum
    against the model shipped with the service. Migration resume/verify calls
    may instead require the source Store/model persisted in the durable run.
    """

    owned_client = http_client is None
    client = http_client or httpx.AsyncClient(
        base_url=config.api_url,
        timeout=httpx.Timeout(config.timeout),
    )
    try:
        store_id = await _resolve_store(
            client,
            config=config,
            allow_bootstrap=allow_bootstrap,
        )
        if required_store_id and required_store_id != store_id:
            raise AuthorizationModelMismatchError(
                msg="Discovered OpenFGA Store does not match the migration run"
            )

        model_id = await _resolve_model(
            client,
            config=config,
            store_id=store_id,
            expected_model=expected_model,
            allow_bootstrap=allow_bootstrap,
            required_model_id=required_model_id,
        )
        payload = await _get_json(
            client,
            f"/stores/{store_id}/authorization-models/{model_id}",
            error_message="Unable to load the discovered OpenFGA authorization model",
        )
        model = normalize_authorization_model(payload)
        checksum = authorization_model_checksum(model)
        if (
            expected_model is not None
            and checksum != authorization_model_checksum(expected_model)
        ):
            raise AuthorizationModelMismatchError(
                msg="Discovered OpenFGA authorization model does not match F048"
            )
        return OpenFGARuntimePin(
            store_id=store_id,
            model_id=model_id,
            model_checksum=checksum,
        )
    finally:
        if owned_client:
            await client.aclose()


async def _resolve_store(
    client: httpx.AsyncClient,
    *,
    config: OpenFGAConf,
    allow_bootstrap: bool,
) -> str:
    stores = await _list_pages(
        client,
        "/stores",
        result_key="stores",
        error_message="Unable to list OpenFGA Stores",
    )
    matches = [
        row
        for row in stores
        if isinstance(row, dict) and row.get("name") == config.store_name
    ]
    if len(matches) > 1:
        raise AuthorizationModelMismatchError(
            msg=f"Multiple OpenFGA Stores use the configured name: {config.store_name}"
        )
    if matches:
        store_id = str(matches[0].get("id") or "")
        if store_id:
            return store_id
        raise AuthorizationModelMismatchError(
            msg="Discovered OpenFGA Store has no ID"
        )
    if not allow_bootstrap:
        raise AuthorizationModelMismatchError(
            msg=f"OpenFGA Store does not exist: {config.store_name}"
        )
    payload = await _post_json(
        client,
        "/stores",
        body={"name": config.store_name},
        error_message="Unable to create the development OpenFGA Store",
    )
    store_id = str(payload.get("id") or "")
    if not store_id:
        raise AuthorizationModelMismatchError(
            msg="OpenFGA Store creation returned no ID"
        )
    return store_id


async def _resolve_model(
    client: httpx.AsyncClient,
    *,
    config: OpenFGAConf,
    store_id: str,
    expected_model: dict[str, Any] | None,
    allow_bootstrap: bool,
    required_model_id: str | None,
) -> str:
    models = await _list_pages(
        client,
        f"/stores/{store_id}/authorization-models",
        result_key="authorization_models",
        extra_result_key="authorization_model_ids",
        error_message="Unable to list OpenFGA authorization models",
    )
    model_ids = sorted(
        {
            str(row.get("id") or row.get("authorization_model_id") or "")
            if isinstance(row, dict)
            else str(row)
            for row in models
        }
        - {""}
    )
    if required_model_id:
        if required_model_id not in model_ids:
            raise AuthorizationModelMismatchError(
                msg="OpenFGA authorization model from the migration run does not exist"
            )
        return required_model_id
    if config.force_write_model:
        if not allow_bootstrap:
            raise ValueError(
                "OpenFGA production runtime cannot auto-write an authorization model"
            )
        return await _write_model(client, store_id, expected_model)
    if model_ids:
        return model_ids[-1]
    if not allow_bootstrap:
        raise AuthorizationModelMismatchError(
            msg="The discovered OpenFGA Store has no authorization model"
        )
    return await _write_model(client, store_id, expected_model)


async def _write_model(
    client: httpx.AsyncClient,
    store_id: str,
    expected_model: dict[str, Any] | None,
) -> str:
    if expected_model is None:
        raise AuthorizationModelMismatchError(
            msg="No authorization model is available for OpenFGA bootstrap"
        )
    payload = await _post_json(
        client,
        f"/stores/{store_id}/authorization-models",
        body=expected_model,
        error_message="Unable to write the development OpenFGA authorization model",
    )
    model_id = str(payload.get("authorization_model_id") or "")
    if not model_id:
        raise AuthorizationModelMismatchError(
            msg="OpenFGA authorization model creation returned no ID"
        )
    return model_id


async def _list_pages(
    client: httpx.AsyncClient,
    path: str,
    *,
    result_key: str,
    error_message: str,
    extra_result_key: str | None = None,
) -> list[Any]:
    rows: list[Any] = []
    continuation_token: str | None = None
    while True:
        params: dict[str, Any] = {"page_size": 100}
        if continuation_token:
            params["continuation_token"] = continuation_token
        payload = await _get_json(
            client,
            path,
            params=params,
            error_message=error_message,
        )
        rows.extend(payload.get(result_key) or [])
        if extra_result_key:
            rows.extend(payload.get(extra_result_key) or [])
        continuation_token = (
            payload.get("continuation_token")
            or payload.get("continuationToken")
        )
        if not continuation_token:
            return rows


async def _get_json(
    client: httpx.AsyncClient,
    path: str,
    *,
    error_message: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        response = await client.get(path, params=params)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        raise AuthorizationModelMismatchError(
            exception=exc,
            msg=error_message,
        ) from exc
    if not isinstance(payload, dict):
        raise AuthorizationModelMismatchError(msg=error_message)
    return payload


async def _post_json(
    client: httpx.AsyncClient,
    path: str,
    *,
    body: dict[str, Any],
    error_message: str,
) -> dict[str, Any]:
    try:
        response = await client.post(path, json=body)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
        raise AuthorizationModelMismatchError(
            exception=exc,
            msg=error_message,
        ) from exc
    if not isinstance(payload, dict):
        raise AuthorizationModelMismatchError(msg=error_message)
    return payload
