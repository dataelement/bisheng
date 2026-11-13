"""Bucket check used by the site entrance before it proxies an object request.

The entrance sends the bucket in ``X-Object-Bucket``. This route does not
require a login: the entrance calls it on every image, including anonymous
knowledge images, and a login challenge would refuse all of them.
"""

from fastapi import APIRouter, Request, Response

from bisheng.common.services.config_service import settings
from bisheng.core.storage.browser_object_path import browser_bucket_allowed

router = APIRouter(tags=["Storage"])


@router.get("/storage/browser-bucket")
async def browser_bucket(request: Request) -> Response:
    conf = settings.get_minio_conf()
    bucket = request.headers.get("x-object-bucket", "")
    if browser_bucket_allowed(bucket, conf.public_bucket if conf else None, conf.tmp_bucket if conf else None):
        return Response(status_code=204)
    return Response(status_code=403)
