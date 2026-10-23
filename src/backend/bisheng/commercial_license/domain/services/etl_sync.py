from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlparse

from loguru import logger

from bisheng.commercial_license.domain.mappers import map_etl_payload
from bisheng.commercial_license.domain.repositories.license_info_repository import LicenseInfoRepository
from bisheng.commercial_license.domain.services.upsert import keep_previous_on_fetch_failure, upsert_mapped
from bisheng.common.services.config_service import settings
from bisheng.core.external.http_client.client import AsyncHttpClient, ResponseData

HttpGet = Callable[[str], Awaitable[ResponseData]]

ETL_FETCH_TIMEOUT_SECONDS = 3


def etl_license_info_url(etl4lm_url: str | None) -> str | None:
    if not etl4lm_url or not str(etl4lm_url).strip():
        return None
    parsed = urlparse(str(etl4lm_url).strip())
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}/api/license_info"


async def _default_http_get(url: str) -> ResponseData:
    client = AsyncHttpClient(timeout=ETL_FETCH_TIMEOUT_SECONDS)
    return await client.get(url, destroy_session=True)


def _payload_from_body(body: Any) -> dict | None:
    if not isinstance(body, dict):
        return None
    if body.get("status") == "fail":
        return None
    if isinstance(body.get("data"), dict):
        return body["data"]
    return body


async def sync_etl_license(
    repo: LicenseInfoRepository,
    *,
    etl_url: str | None = None,
    http_get: HttpGet | None = None,
) -> None:
    if etl_url is None:
        etl_url = settings.get_knowledge().etl4lm.url
    license_url = etl_license_info_url(etl_url)
    if license_url is None:
        logger.info("etl license url is empty; skip fetch")
        return
    getter = http_get or _default_http_get
    try:
        response = await getter(license_url)
    except Exception:
        logger.warning("etl license fetch failed license_code={}", "etl")
        keep_previous_on_fetch_failure("etl")
        return
    if response.status_code != 200 or response.error:
        logger.warning(
            "etl license fetch returned status={} license_code={}",
            response.status_code,
            "etl",
        )
        keep_previous_on_fetch_failure("etl")
        return
    payload = _payload_from_body(response.body)
    if payload is None:
        keep_previous_on_fetch_failure("etl")
        return
    try:
        mapped = map_etl_payload(payload)
    except (TypeError, ValueError):
        logger.warning("etl license payload invalid license_code={}", "etl")
        keep_previous_on_fetch_failure("etl")
        return
    await upsert_mapped(repo, mapped)
