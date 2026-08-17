# ruff: noqa: RUF002
"""审批中心运行时 handler：转公开业务仍由 PublishService 执行，这里只满足注册契约。"""

from __future__ import annotations

from bisheng.qa_expert.domain.publish_approval_bridge import QA_PUBLISH_SCENARIO


class QaQuestionPublishHandler:
    """待办决策已在 decide_task 里转调 PublishService，本 handler 不改问题状态。"""

    scenario_code = QA_PUBLISH_SCENARIO

    async def validate(self, req, login_user) -> None:
        return None

    async def build_title(self, req) -> str:
        return req.business_name

    async def build_detail(self, req) -> dict:
        payload = req.payload_snapshot or {}
        return {
            "question_title": req.business_name,
            "expire_at": payload.get("expire_at"),
            "duration_days": payload.get("duration_days"),
        }

    async def build_business_link(self, req) -> dict:
        return {"question_id": (req.payload_snapshot or {}).get("question_id")}

    async def resolve_approvers(self, node_config: dict, req) -> list[int]:
        ids = (req.payload_snapshot or {}).get("approver_user_ids") or []
        return [int(uid) for uid in ids]

    async def on_approved(self, instance_id: int, payload_snapshot: dict) -> dict:
        return {"status": "delegated"}

    async def on_rejected(self, instance_id: int, payload_snapshot: dict, reason: str | None) -> None:
        return None

    async def on_withdrawn(self, instance_id: int, payload_snapshot: dict, reason: str | None) -> None:
        return None
