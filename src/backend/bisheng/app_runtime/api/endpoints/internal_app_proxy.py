"""Internal endpoints app-proxy calls, plus the fallback page nginx falls back to.

``POST /api/v1/internal/app-proxy/authorize`` is the whole permission surface of
the ``/apps`` entry. Three things about it are deliberate:

* **It is registered in ``TENANT_CHECK_EXEMPT_PATHS``** and the handler runs
  under ``bypass_tenant_filter``. There is no JWT on this request — the session
  token arrives *inside the body* as data to be judged — so the tenant
  ContextVar is unset, and any DAO touching a tenant-aware table would raise.
  The service establishes the tenant from the resolved ``app`` row instead.
* **The answer carries no upstream address.** Where the app is running is
  runtime-manager's answer, on its own cache clock (D5.1): authorisation follows
  permission changes (seconds), routing follows releases. One response carrying
  both would make "revoke access" and "switch version" invalidate each other.
* **A business verdict is always HTTP 200.** ``forbidden`` / ``stopped`` /
  ``not_found`` are answers, not transport failures; only a rejected *signature*
  is a 401, and app-proxy relies on that distinction to tell "this visitor may
  not enter" from "our own deployment is misconfigured".

``GET /api/v1/apps/_unavailable`` is what nginx's ``error_page`` falls back to
when app-proxy itself is down. Serving one static HTML page from backend does
not violate K1 — there is no orchestration in a string.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from bisheng.app_runtime.domain.services.entry_authz_service import authorize_entry
from bisheng.app_runtime.domain.services.hmac_auth import verify_proxy_hmac
from bisheng.common.schemas.api import UnifiedResponseModel, resp_200
from bisheng.core.context.tenant import bypass_tenant_filter

router = APIRouter(tags=["AppRuntime Internal"])

#: Rendered when the runtime layer is not installed *or* app-proxy is down. Kept
#: deliberately dependency-free (no SPA, no fonts, no scripts): it is the page
#: shown precisely when something is broken.
_UNAVAILABLE_PAGE = """<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>应用暂时不可用</title>
<style>
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
background:#f6f7f9;color:#1f2329;font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{max-width:32rem;padding:2rem;text-align:center}
h1{font-size:1.25rem;margin:0 0 .75rem}p{margin:.25rem 0;color:#646a73}
</style></head>
<body><main>
<h1>应用暂时不可用</h1>
<p>本环境的应用工场运行时层未部署或正在恢复中。</p>
<p>请稍后重试或联系平台管理员确认运行环境状态。</p>
</main></body></html>
"""


class AuthorizeRequest(BaseModel):
    """What app-proxy sends. ``access_token`` is the visitor's session, verbatim."""

    slug: str
    access_token: str | None = None
    request_id: str = ""
    client_ip: str | None = None


@router.post(
    "/internal/app-proxy/authorize",
    response_model=UnifiedResponseModel[dict],
    summary="Entry verdict + identity material for app-proxy (HMAC-signed)",
)
async def authorize(payload: AuthorizeRequest, _: None = Depends(verify_proxy_hmac)):
    with bypass_tenant_filter():
        verdict = await authorize_entry(
            slug=payload.slug,
            access_token=payload.access_token,
            request_id=payload.request_id,
            client_ip=payload.client_ip,
        )
    return resp_200(data=verdict)


@router.get("/apps/_unavailable", response_class=HTMLResponse, summary="Fallback page for nginx error_page")
async def unavailable_page() -> HTMLResponse:
    return HTMLResponse(content=_UNAVAILABLE_PAGE, status_code=200)
