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

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from bisheng.app_runtime.domain.services.entry_authz_service import authorize_entry, authorize_preview_entry
from bisheng.app_runtime.domain.services.hmac_auth import verify_proxy_hmac
from bisheng.common.schemas.api import UnifiedResponseModel, resp_200
from bisheng.core.context.tenant import bypass_tenant_filter

router = APIRouter(tags=["AppRuntime Internal"])

#: Rendered when the runtime layer is not installed *or* app-proxy is down. Kept
#: deliberately dependency-free (no SPA, no fonts, no scripts): it is the page
#: shown precisely when something is broken.
#: Artwork and layout snapshot: src/app-proxy/app_proxy/recovery_appearance.py.
#: Kept inline so this fallback also works when app-proxy is not deployed.
_UNAVAILABLE_PAGE = """<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>应用暂时不可用</title>
<style>
:root {
  color-scheme: light dark;
  --bg-page: 255 255 255;
  --text-1: 29 33 41;
  --text-3: 137 143 156;
  --border-base: 229 230 233;
  --illus-100: 190 218 255;
  --illus-300: 106 161 255;
  --illus-500: 22 93 255;
  --illus-face: 255 255 255;
  --brand-500: 22 93 255;
}
* { box-sizing: border-box; }
body {
  margin: 0; min-height: 100vh; min-height: 100dvh;
  display: flex; align-items: center; justify-content: center;
  padding: 32px 24px; background: rgb(var(--bg-page)); color: rgb(var(--text-1));
  font: 14px/22px -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
        "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
}
.card { width: 100%; max-width: 400px; text-align: center; }
.mark { width: 120px; height: 120px; margin: 0 auto 16px; }
.mark svg { display: block; width: 100%; height: 100%; }
h1 { margin: 0 0 4px; font-size: 16px; line-height: 24px; font-weight: 500; }
p { margin: 0; color: rgb(var(--text-3)); overflow-wrap: anywhere; }
.actions { margin-top: 16px; }
a.button {
  display: inline-flex; align-items: center; justify-content: center;
  min-height: 32px; padding: 4px 16px; border-radius: 6px;
  background: rgb(var(--brand-500)); color: #fff;
  font-size: 14px; line-height: 22px; text-decoration: none;
}
a.button:focus-visible { outline: 2px solid rgb(var(--brand-500)); outline-offset: 2px; }
.hint {
  margin-top: 32px; padding-top: 16px; border-top: 1px solid rgb(var(--border-base));
  font-size: 12px; line-height: 20px; overflow-wrap: anywhere;
}
@media (max-width: 768px) {
  body { font-size: 16px; line-height: 24px; }
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg-page: 18 18 18;
    --text-1: 246 246 246;
    --text-3: 146 146 147;
    --border-base: 72 72 73;
    --illus-face: var(--illus-100);
  }
}
</style></head>
<body><main class="card">
<div class="mark"><svg width="120" height="120" viewBox="0 0 120 120" fill="none" aria-hidden="true" style="color:rgb(var(--bg-page))">
<g transform="translate(20.791 19.51)">
<circle cx="40.2841" cy="44.1724" r="33.2104" style="fill:rgb(var(--illus-100))" />
<ellipse cx="40.3575" cy="77.4911" rx="35.2662" ry="2.53031" style="fill:rgb(var(--illus-100))" />
<path d="M60.8431 52.8487C63.2217 60.8538 63.7922 68.4341 64.1642 76.2541H19.7255L18.6185 67.5561L13.5579 69.2957C7.82567 68.906 6.20299 66.9832 5.49253 61.2303C5.79936 55.2088 8.30262 52.5029 18.6185 49.3695C24.361 44.9092 28.1884 42.9875 39.3355 43.6763C51.1378 43.6208 56.6693 44.7471 60.8431 52.8487Z" style="fill:rgb(var(--illus-500));stroke:rgb(var(--illus-500))" stroke-width="0.316289" />
<path d="M47.2427 57.4566C43.0865 62.4493 39.2591 64.1324 27.1583 62.9916L24.4699 71.6896C36.8527 75.0328 43.8536 76.2176 57.2058 63.7824" style="stroke:rgb(var(--illus-100))" stroke-width="1.89774" stroke-linecap="round" />
<circle cx="42.4292" cy="29.554" r="23.6526" style="fill:rgb(var(--illus-face));stroke:rgb(var(--illus-500))" stroke-width="1.89774" />
<path d="M12.237 31.1817C11.6525 29.5941 12.987 27.9472 14.6706 28.2159L14.6715 28.2149C14.8871 28.2491 15.1013 28.2915 15.3112 28.339L15.3102 28.3399C16.0938 28.5143 16.8674 28.7714 17.6208 29.1163C23.4114 31.767 25.9618 38.6441 23.3043 44.4356L23.3053 44.4366C22.968 45.1735 22.5597 45.8614 22.0934 46.4923L22.0944 46.4933C21.9846 46.6422 21.9448 46.8364 21.9879 47.0206L22.0114 47.0987L22.027 47.1388L22.0397 47.1808L29.7711 73.3868C30.3193 74.9176 30.2027 76.5335 29.5739 77.9073C28.9359 79.3011 27.7654 80.4607 26.2155 81.0382C24.6654 81.6156 23.022 81.5041 21.6286 80.8663C20.2351 80.2284 19.0766 79.0576 18.5006 77.5069L18.486 77.4659L18.4733 77.4239L10.7633 51.2892C10.6816 51.0937 10.5139 50.9526 10.317 50.9083C9.55057 50.739 8.79097 50.4877 8.05044 50.1524C2.23335 47.5193 -0.346392 40.6276 2.31313 34.8175C2.65872 34.0625 3.07622 33.3604 3.5563 32.7149C3.6834 32.5429 3.81776 32.372 3.95767 32.2061C5.02397 30.9379 7.02078 31.2546 7.68032 32.7188L7.73989 32.8634V32.8643L10.2819 39.713L10.3756 39.9317C10.6177 40.4264 11.0196 40.8199 11.5368 41.0567C12.1284 41.3275 12.7754 41.3499 13.3688 41.129C13.9622 40.9079 14.438 40.4672 14.7096 39.8741C14.9827 39.2776 15.0051 38.6294 14.7848 38.0362L12.2379 31.1856L12.237 31.1817Z" style="fill:rgb(var(--illus-500))" stroke="currentColor" stroke-width="2.53031" />
<circle cx="23.8373" cy="66.1545" r="6.95836" fill="currentColor" style="stroke:rgb(var(--illus-100))" stroke-width="1.58145" />
<circle cx="17.1952" cy="64.573" r="6.95836" fill="currentColor" style="stroke:rgb(var(--illus-100))" stroke-width="1.58145" />
<path d="M55.8637 3.9663C68.2802 10.0967 70.9643 24.0879 67.561 34.9999C64.7606 31.2684 60.6109 27.7843 55.8637 24.7829C43.8116 17.1632 27.9076 12.6552 20.4491 15.1113C14.4695 12.9324 17.0687 9.18294 25.4852 9.73155C33.3147 1.69381 43.4472 -2.16408 55.8637 3.9663Z" style="fill:rgb(var(--illus-500))" />
<path d="M25.4852 9.73155C33.3147 1.69381 43.4472 -2.16408 55.8637 3.9663C68.2802 10.0967 70.9643 24.0879 67.561 34.9999C64.7606 31.2684 60.6109 27.7843 55.8637 24.7829M25.4852 9.73155C17.0687 9.18294 14.4695 12.9324 20.4491 15.1113C27.9076 12.6552 43.8116 17.1632 55.8637 24.7829M25.4852 9.73155C45.4981 12.1173 52.3212 17.9861 55.8637 24.7829" style="stroke:rgb(var(--illus-100))" stroke-width="1.89774" stroke-linecap="round" stroke-linejoin="round" />
<ellipse cx="32.0119" cy="27.2021" rx="1.58145" ry="2.37217" transform="rotate(10.0939 32.0119 27.2021)" style="fill:rgb(var(--illus-500))" />
<ellipse cx="47.6078" cy="30.0813" rx="1.58145" ry="2.37217" transform="rotate(8.53515 47.6078 30.0813)" style="fill:rgb(var(--illus-500))" />
<path d="M43.3981 37.592C39.4348 38.3137 37.4544 37.9148 34.1674 36.397C34.1674 36.397 34.1184 41.9966 38.6506 42.3041C43.1828 42.6116 43.3981 37.592 43.3981 37.592Z" style="fill:rgb(var(--illus-500));stroke:rgb(var(--illus-500))" stroke-width="1.26516" stroke-linejoin="round" />
<path d="M51.8029 36.6694L51.163 38.2744M49.621 36.5435L49.1405 37.9307M53.6458 37.3498L53.2461 38.2611" style="stroke:rgb(var(--illus-300))" stroke-width="1.20677" stroke-linecap="round" stroke-linejoin="round" />
<path d="M26.0587 31.5815L25.4188 33.1865M27.9016 32.2619L27.5019 33.1732" style="stroke:rgb(var(--illus-300))" stroke-width="1.20677" stroke-linecap="round" stroke-linejoin="round" />
</g>
</svg></div>
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
async def authorize(payload: AuthorizeRequest, request: Request, _: None = Depends(verify_proxy_hmac)):
    if payload.access_token and payload.access_token.startswith("bs-view-"):
        from bisheng.app_runtime.domain.services.desktop_entry_service import authorize_desktop_entry
        from bisheng.dsh.access_runtime import get_runtime, get_settings

        runtime = await get_runtime(request, get_settings())
        verdict = await authorize_desktop_entry(
            slug=payload.slug,
            access_token=payload.access_token,
            runtime=runtime,
            request_id=payload.request_id,
            client_ip=payload.client_ip,
        )
        return resp_200(data=verdict)
    with bypass_tenant_filter():
        verdict = await authorize_entry(
            slug=payload.slug,
            access_token=payload.access_token,
            request_id=payload.request_id,
            client_ip=payload.client_ip,
        )
    return resp_200(data=verdict)


class AuthorizePreviewRequest(BaseModel):
    """What app-proxy sends for ``/apps/preview/{session}`` (F054 T090, F055 AC-26)."""

    session: str
    access_token: str | None = None
    request_id: str = ""
    client_ip: str | None = None


@router.post(
    "/internal/app-proxy/authorize-preview",
    response_model=UnifiedResponseModel[dict],
    summary="Entry verdict for an approval-time preview instance (HMAC-signed)",
)
async def authorize_preview(payload: AuthorizePreviewRequest, _: None = Depends(verify_proxy_hmac)):
    """A second endpoint rather than a flag on ``authorize``.

    The two verdicts share the session checks and nothing else: one resolves a
    slug and asks the permission engine about the visible scope, the other
    resolves a preview session and asks whether the visitor *is* the approver
    it was raised for. Folding them into one handler with a branch would put
    the two access rules one typo away from each other, on the endpoint where
    that mistake means "anyone can open an unpublished application".
    """
    with bypass_tenant_filter():
        verdict = await authorize_preview_entry(
            session=payload.session,
            access_token=payload.access_token,
            request_id=payload.request_id,
            client_ip=payload.client_ip,
        )
    return resp_200(data=verdict)


@router.get("/apps/_unavailable", response_class=HTMLResponse, summary="Fallback page for nginx error_page")
async def unavailable_page() -> HTMLResponse:
    return HTMLResponse(content=_UNAVAILABLE_PAGE, status_code=200)


class DesktopRedeemRequest(BaseModel):
    slug: str
    ticket: str


@router.post("/internal/app-proxy/desktop-session")
async def desktop_session(payload: DesktopRedeemRequest, request: Request, _: None = Depends(verify_proxy_hmac)):
    from bisheng.app_runtime.domain.services.desktop_entry_service import redeem_desktop_ticket
    from bisheng.dsh.access_runtime import get_runtime, get_settings

    runtime = await get_runtime(request, get_settings())
    return resp_200(data=await redeem_desktop_ticket(payload.ticket, payload.slug, runtime))
