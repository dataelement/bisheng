"""积分变动的尽力通知服务。"""

import logging

from bisheng.points.domain.constants.notify_templates import NOTIFY_TEMPLATES, POINTS_CHANGED_ACTION_CODE

logger = logging.getLogger(__name__)


class PointsNotifyService:
    """渲染代码模板并委托消息模块发送，不影响已提交的积分账本。"""

    def __init__(self, message_service=None):
        self.message_service = message_service

    async def notify(self, *, user_id: int, template_code: str, **values) -> None:
        """发送积分变动站内信；消息依赖故障只记录，不回滚积分。"""
        if not self.message_service:
            return
        try:
            content = NOTIFY_TEMPLATES[template_code].format(**values)
            await self.message_service.send_generic_notify(
                sender=0, receiver_user_ids=[user_id],
                content_item_list=[{"type": "system_text", "content": content}],
                action_code=POINTS_CHANGED_ACTION_CODE,
            )
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("积分通知模板渲染失败：%s", exc)
        except Exception:
            # 通知是账本提交后的旁路，不允许消息系统故障影响积分变动。
            logger.exception("积分通知发送失败")
