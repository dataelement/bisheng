"""HTTP client for 中粮 E+ 消息中心 textcard interface."""
import json
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

        conf = settings.get_cofco_forwarding_conf()
        # api_base may already include /v2/message/send — tolerate both
        # `.../qwmsg-ui` and `.../qwmsg-ui/v2/message/send`.
        base = conf.api_base.rstrip("/")
        url = base if base.endswith("/v2/message/send") else f"{base}/v2/message/send"
        # Some internal gateways filter on User-Agent / Accept; mirror curl
        # defaults so the response shape matches what we test against.
        headers = {
            "appId": conf.app_id,
            "secret": conf.secret,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "BiSheng-Notification/1.0",
        }
        body: dict = {
            "touser": "|".join(touser),
            "msgtype": "textcard",
            "textcard": textcard,
            "enable_duplicate_check": conf.enable_duplicate_check,
            "duplicate_check_interval": conf.duplicate_check_interval,
        }
        if conf.agentid is not None:
            body["agentid"] = conf.agentid

        # Serialize body ourselves with ensure_ascii=False — sends literal UTF-8
        # bytes for Chinese (e.g. 测试/去查看) the same way curl -d '...' does.
        # httpx's `json=` default escapes them as \uXXXX which some backends choke on.
        body_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")

        # Emit attempt log BEFORE firing — `url` lets ops correlate to the
        # ConfigMap `api_base` value when troubleshooting.
        logger.info(
            "forward.attempt message_id=%s action_code=%s recipient=%s url=%s",
            message_id, action_code, "|".join(touser), url,
        )

        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=conf.timeout_seconds) as client:
                resp = await client.post(url, content=body_bytes, headers=headers)
                elapsed_ms = int((time.monotonic() - started) * 1000)
                http_status = resp.status_code

                try:
                    data = resp.json()
                except Exception as parse_exc:
                    # Got HTTP response but body isn't JSON — keep status, content-type,
                    # and a short body snippet so ops can spot gateway pages / wrong path.
                    body_snippet = (resp.text or "")[:300].replace("\n", " ")
                    content_type = resp.headers.get("content-type", "")
                    logger.warning(
                        "forward.result message_id=%s code=non_json_response "
                        "elapsed_ms=%s http_status=%s content_type=%s "
                        "body_snippet=%r parse_err=%s",
                        message_id, elapsed_ms, http_status, content_type,
                        body_snippet, parse_exc,
                    )
                    return

                code = str(data.get("code"))
                msg = data.get("msg", "")

                if code == "0":
                    logger.info(
                        "forward.result message_id=%s code=0 elapsed_ms=%s msg=%s",
                        message_id, elapsed_ms, msg,
                    )
                else:
                    logger.warning(
                        "forward.result message_id=%s code=%s elapsed_ms=%s "
                        "http_status=%s msg=%s",
                        message_id, code, elapsed_ms, http_status, msg,
                    )
        except Exception as exc:  # broad catch: fire-and-forget contract
            elapsed_ms = int((time.monotonic() - started) * 1000)
            # Surface the concrete exception class so ops can map symptoms:
            #   ConnectError / ConnectTimeout → IP/port/firewall (TCP-level fail)
            #   ReadTimeout                  → server hung after accepting connection
            #   RemoteProtocolError          → server closed mid-response
            logger.warning(
                "forward.result message_id=%s code=exception "
                "elapsed_ms=%s exc_type=%s msg=%s",
                message_id, elapsed_ms, type(exc).__name__, exc, exc_info=True,
            )
