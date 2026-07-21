"""HTTP client for Shougang MADC enterprise WeChat push API."""

import json
import logging
import time

import httpx

from bisheng.common.services.config_service import settings

logger = logging.getLogger(__name__)


class ShougangMADPClient:
    """Thin wrapper over POST /madp/qywxPush-api/pushMessage.

    All errors are swallowed and logged; callers decide whether to retry.

    Logging contract (keyed by outbox_id for grep):
      INFO  wechat_push.attempt  outbox_id=<id> users=<count>
      INFO  wechat_push.result    outbox_id=<id> success=true elapsed_ms=<ms>
      WARN  wechat_push.result    outbox_id=<id> success=false ...
    """

    @staticmethod
    def _check_business_success(http_status: int, body_text: str) -> tuple[bool, str | None]:
        """Return (is_success, error_message).

        Falls back to HTTP status when the body is empty or not JSON.  Recognises
        common gateway conventions: ``code``/``errcode``/``status``/``success``.
        Also unwraps a JSON-string ``data`` field, because the Shougang MADP
        gateway wraps the real enterprise-WeChat response there.
        """
        if http_status < 200 or http_status >= 300:
            return False, None

        if not body_text:
            return True, None

        try:
            payload = json.loads(body_text)
        except json.JSONDecodeError:
            # Non-JSON 2xx body: trust HTTP status but surface the snippet in logs.
            return True, None

        candidates = [payload]
        # Some gateways embed the real third-party response as a JSON string
        # under the ``data`` key (e.g. Shougang MADP).
        if isinstance(payload, dict):
            data_field = payload.get("data")
            if isinstance(data_field, str):
                try:
                    candidates.append(json.loads(data_field))
                except json.JSONDecodeError:
                    pass
            elif isinstance(data_field, dict):
                candidates.append(data_field)

        for data in candidates:
            if not isinstance(data, dict):
                continue

            # errcode / code: 0 usually means success; non-zero means failure.
            if "errcode" in data:
                code = data["errcode"]
                if code not in (0, "0"):
                    errmsg = data.get("errmsg") or data.get("error_msg") or ""
                    error = f"errcode={code}"
                    if errmsg:
                        error += f" errmsg={errmsg}"
                    return False, error
            if "code" in data:
                code = data["code"]
                if code not in (0, "0", 200, "200", "ok", "OK", "success", "SUCCESS"):
                    msg = data.get("msg") or data.get("message") or ""
                    error = f"code={code}"
                    if msg:
                        error += f" msg={msg}"
                    return False, error

            # status / success boolean flags
            status = data.get("status")
            if status is not None and str(status).lower() not in ("success", "ok", "true", "1"):
                return False, f"status={status}"

            success = data.get("success")
            if success is False:
                return False, "success=false"

        return True, None

    async def push_text_message(
        self,
        *,
        outbox_id: int,
        user_ids: list[str],
        body: str,
    ) -> tuple[bool, str | None]:
        """Push a text message to the given enterprise WeChat users.

        Args:
            outbox_id: Outbox record ID for logging.
            user_ids: Enterprise WeChat user IDs (MADC ``users`` field).
            body: Rendered message body.

        Returns:
            (success, error_message). error_message is None on success.
        """
        if not user_ids:
            logger.debug("wechat_push skipped: empty user_ids outbox_id=%s", outbox_id)
            return False, "empty_user_ids"

        conf = settings.get_shougang_wechat_message_push_conf()
        url = conf.api_url
        payload = {
            "id": conf.id,
            "agentid": conf.agentid,
            "body": {"content": body},
            "key": conf.key,
            "msgType": conf.msg_type,
            "sysId": conf.sys_id,
            "users": user_ids,
        }

        body_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "BiSheng-WeChat-Push/1.0",
        }

        logger.info(
            "wechat_push.attempt outbox_id=%s users=%s url=%s",
            outbox_id,
            ",".join(user_ids),
            url,
        )

        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=conf.timeout_seconds) as client:
                resp = await client.post(url, content=body_bytes, headers=headers)
                elapsed_ms = int((time.monotonic() - started) * 1000)
                body_text = (resp.text or "").strip()
                body_snippet = body_text[:500].replace("\n", " ")

                # Many push gateways return HTTP 200 with a JSON body that carries the
                # real business result. Parse it so we do not mark "sent" when the
                # downstream actually rejected the message.
                business_ok, business_error = self._check_business_success(
                    resp.status_code, body_text
                )

                if business_ok:
                    logger.info(
                        "wechat_push.result outbox_id=%s success=true elapsed_ms=%s http_status=%s body_snippet=%r",
                        outbox_id,
                        elapsed_ms,
                        resp.status_code,
                        body_snippet,
                    )
                    return True, None

                logger.warning(
                    "wechat_push.result outbox_id=%s success=false elapsed_ms=%s http_status=%s business_error=%s body_snippet=%r",
                    outbox_id,
                    elapsed_ms,
                    resp.status_code,
                    business_error,
                    body_snippet,
                )
                return False, business_error or f"http_status_{resp.status_code}"
        except httpx.TimeoutException as exc:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            logger.warning(
                "wechat_push.result outbox_id=%s success=false elapsed_ms=%s error=timeout %s",
                outbox_id,
                elapsed_ms,
                exc,
            )
            return False, "timeout"
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            logger.warning(
                "wechat_push.result outbox_id=%s success=false elapsed_ms=%s exc_type=%s msg=%s",
                outbox_id,
                elapsed_ms,
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            return False, f"exception_{type(exc).__name__}"
