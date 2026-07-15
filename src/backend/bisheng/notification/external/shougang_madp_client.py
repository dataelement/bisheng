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

                if resp.status_code >= 200 and resp.status_code < 300:
                    logger.info(
                        "wechat_push.result outbox_id=%s success=true elapsed_ms=%s http_status=%s",
                        outbox_id,
                        elapsed_ms,
                        resp.status_code,
                    )
                    return True, None

                body_snippet = (resp.text or "")[:300].replace("\n", " ")
                logger.warning(
                    "wechat_push.result outbox_id=%s success=false elapsed_ms=%s http_status=%s body_snippet=%r",
                    outbox_id,
                    elapsed_ms,
                    resp.status_code,
                    body_snippet,
                )
                return False, f"http_status_{resp.status_code}"
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
