"""Decide how a stored training or validation file reaches the FT host.

FT normally downloads a presigned storage link (pull). When the FT host cannot reach object storage —
separate networks, NAT, or a storage address that only resolves inside the platform — the platform
streams the bytes to FT instead (push), so a one-way platform-to-FT connection is enough. A version
imported from FTP / SFTP / S3 is a small plan: FT downloads its files from that source directly.
"""

import asyncio
import json

from loguru import logger

from bisheng.common.errcode.finetune import FinetuneDatasetSourceError, FinetuneDatasetTransferError
from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync

from ..sft_backend import SFTBackend

PUSH_SCHEME = "ft-file://"
CHUNK_BYTES = 1024 * 1024
SECRET_FIELDS = ("password", "access_key", "secret_key", "session_token")


async def _object_chunks(object_name: str):
    storage = get_minio_storage_sync()
    response = await asyncio.to_thread(storage.download_object_sync, None, object_name)
    try:
        while chunk := await asyncio.to_thread(response.read, CHUNK_BYTES):
            yield chunk
    finally:
        response.close()
        response.release_conn()


async def _pull_link(host: str, object_name: str) -> str | None:
    """Return a storage link FT has confirmed it can download, or None when FT must receive a push."""
    try:
        link = get_minio_storage_sync().get_share_link_sync(object_name, clear_host=False)
    except Exception:
        logger.exception("cannot sign a storage link for {}; pushing it to FT instead", object_name)
        return None
    try:
        success, data = await SFTBackend.probe_url(host, link)
    except Exception:
        logger.exception("FT probe at {} failed; pushing {} instead", host, object_name)
        return None
    if success and isinstance(data, dict) and data.get("reachable"):
        return link
    if not success and isinstance(data, dict) and data.get("http_status") == 404:
        # FT builds without the probe endpoint can only pull; keep their previous behaviour.
        return link
    logger.info("FT at {} cannot download storage links ({}); pushing {}", host, data, object_name)
    return None


async def reference_for(host: str, object_name: str, sha256: str) -> tuple[str, str]:
    """Return the reference FT should read and the transfer mode that produced it ("pull" or "push")."""
    if link := await _pull_link(host, object_name):
        return link, "pull"
    try:
        success, data = await SFTBackend.push_file(host, sha256, _object_chunks(object_name))
    except Exception as exc:
        logger.exception("pushing {} to FT at {} failed", object_name, host)
        raise FinetuneDatasetTransferError() from exc
    if not success:
        logger.error("FT at {} rejected pushed file {}: {}", host, object_name, data)
        raise FinetuneDatasetTransferError()
    return PUSH_SCHEME + sha256, "push"


def remote_source(remote: dict, credentials) -> dict:
    """Join the version's stored connection facts with the secrets typed for this job; nothing here is persisted."""
    source = {key: value for key, value in remote.items() if key not in {"layout", "path"}}
    for field in SECRET_FIELDS:
        secret = getattr(credentials, field, None) if credentials else None
        if secret is not None and secret.get_secret_value():
            source[field] = secret.get_secret_value()
    if source["type"] == "sftp" and not source.get("password"):
        raise FinetuneDatasetSourceError(msg="Enter the SFTP password for this training job")
    return source


async def check_source(host: str, source: dict) -> None:
    """Fail before the job exists when FT cannot log in to the source or read its first file."""
    try:
        success, data = await SFTBackend.check_source(host, source, source["probe"])
    except Exception as exc:
        # The request carries secrets; log only where it was going.
        logger.error("dataset source check on FT {} failed: {}", host, type(exc).__name__)
        raise FinetuneDatasetSourceError(msg="Cannot reach the training service to check the data source") from None
    if success:
        return
    status = data.get("http_status") if isinstance(data, dict) else None
    if status == 404:
        raise FinetuneDatasetSourceError(
            msg="This training service cannot read data sources directly; upgrade it or upload the dataset instead"
        )
    try:
        detail = json.loads(data["detail"])["detail"]
    except (TypeError, KeyError, ValueError):
        detail = f"HTTP {status}"
    raise FinetuneDatasetSourceError(msg=f"The training service cannot read the data source: {str(detail)[:500]}")
