"""HTTP client for 中粮 E+ 消息中心 textcard interface."""
import logging
import time

import httpx

from bisheng.common.services.config_service import settings

logger = logging.getLogger(__name__)


class CofcoEPlusClient:
    """Thin wrapper over POST /v2/message/send.

    All errors (HTTP-level, non-zero response code, exceptions) are
    swallowed and logged as WARNING. Callers MUST NOT rely on this method
    succeeding in order to gate business logic (fire-and-forget).

    Logging contract (two lines per call, keyed by message_id for grep):
      INFO  forward.attempt  message_id=<id> action_code=<code> recipient=<eids>
      INFO  forward.result   message_id=<id> code=0 elapsed_ms=<ms> msg=<...>
      WARN  forward.result   message_id=<id> code=<n> elapsed_ms=<ms> msg=<...>  (non-zero or exception)
    """

    async def send_textcard(
        self,
        *,
        message_id: int,
        action_code: str,
        touser: list[str],
        textcard: dict,
    ) -> None:
        """POST a textcard message to E+ for one or more employee IDs.

        Silently returns (after DEBUG log) when touser is empty.
        """
        if not touser:
            logger.debug(
                "cofco_eplus send_textcard skipped: empty touser message_id=%s", message_id
            )
            return

        conf = settings.in_app_message_forwarding.cofco
        url = f"{conf.api_base.rstrip('/')}/v2/message/send"
        headers = {"appId": conf.app_id, "secret": conf.secret}
        body: dict = {
            "touser": "|".join(touser),
            "msgtype": "textcard",
            "textcard": textcard,
            "enable_duplicate_check": conf.enable_duplicate_check,
            "duplicate_check_interval": conf.duplicate_check_interval,
        }
        if conf.agentid is not None:
            body["agentid"] = conf.agentid

        # Emit attempt log before firing — allows grep for message_id to find the pair
        logger.info(
            "forward.attempt message_id=%s action_code=%s recipient=%s",
            message_id, action_code, "|".join(touser),
        )

        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=conf.timeout_seconds) as client:
                resp = await client.post(url, json=body, headers=headers)
                data = resp.json()
                elapsed_ms = int((time.monotonic() - started) * 1000)
                code = str(data.get("code"))
                msg = data.get("msg", "")

                if code == "0":
                    logger.info(
                        "forward.result message_id=%s code=%s elapsed_ms=%s msg=%s",
                        message_id, code, elapsed_ms, msg,
                    )
                else:
                    logger.warning(
                        "forward.result message_id=%s code=%s elapsed_ms=%s msg=%s",
                        message_id, code, elapsed_ms, msg,
                    )
        except Exception as exc:  # broad catch: fire-and-forget contract
            elapsed_ms = int((time.monotonic() - started) * 1000)
            logger.warning(
                "forward.result message_id=%s code=exception elapsed_ms=%s msg=%s",
                message_id, elapsed_ms, exc, exc_info=True,
            )
