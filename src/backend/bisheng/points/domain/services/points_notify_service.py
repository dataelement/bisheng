"""积分变动的尽力通知服务。"""

import logging

from bisheng.points.domain.constants.notify_templates import NOTIFY_TEMPLATES, POINTS_CHANGED_ACTION_CODE

logger = logging.getLogger(__name__)


def _notify_enabled() -> bool:
    """读取 points.notify_enabled；缺省为 True。"""
    try:
        from bisheng.common.services.config_service import settings

        return bool(getattr(getattr(settings, "points", None), "notify_enabled", True))
    except Exception:
        return True


def build_points_notify_content(*, template_code: str, message: str, values: dict) -> list[dict]:
    """构造与站内信约定一致的积分通知 content。

    system_text 必须是 action_code（供前端 i18n/路由），完整文案放在 metadata，
    避免被当成未知 action 回退成「给你发送了一条通知」。
    """
    return [
        {
            "type": "system_text",
            "content": POINTS_CHANGED_ACTION_CODE,
            "metadata": {
                "template_code": template_code,
                "points_message": message,
                "data": {
                    "points_change": {
                        "template_code": template_code,
                        "message": message,
                        **{k: values[k] for k in values},
                    }
                },
            },
        }
    ]


async def build_points_notify_service(session) -> "PointsNotifyService":
    """在 Worker / 旁路路径构造带 MessageService 的通知服务。

    Args:
        session: 当前异步 DB 会话；站内信写入依赖该会话，调用方负责 commit。

    Returns:
        已注入 MessageService 的 PointsNotifyService。
    """
    from bisheng.message.api.dependencies import get_message_service

    message_service = await get_message_service(session)
    return PointsNotifyService(message_service=message_service)


class PointsNotifyService:
    """渲染代码模板并委托消息模块发送，不影响已提交的积分账本。"""

    def __init__(self, message_service=None):
        self.message_service = message_service

    async def notify(self, *, user_id: int, template_code: str, **values) -> None:
        """发送积分变动站内信；消息依赖故障只记录，不回滚积分。

        Args:
            user_id: 接收人用户 ID。
            template_code: NOTIFY_TEMPLATES 中的键。
            **values: 模板 format 参数（如 delta、rule_name）。
        """
        if not self.message_service:
            logger.warning("积分通知跳过：未注入 message_service user_id=%s", user_id)
            return
        if not _notify_enabled():
            logger.info("积分通知跳过：notify_enabled=false user_id=%s", user_id)
            return
        try:
            message = NOTIFY_TEMPLATES[template_code].format(**values)
            await self.message_service.send_generic_notify(
                sender=0,
                receiver_user_ids=[user_id],
                content_item_list=build_points_notify_content(
                    template_code=template_code,
                    message=message,
                    values=values,
                ),
                action_code=POINTS_CHANGED_ACTION_CODE,
            )
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("积分通知模板渲染失败：%s", exc)
        except Exception:
            # 通知是账本提交后的旁路，不允许消息系统故障影响积分变动。
            logger.exception("积分通知发送失败")
