"""合成目录与正文、供 Mock 开发和验证。"""

import asyncio

from bisheng.common.errcode.flow import (
    PlatformKnowledgeConfigurationError,
    PlatformKnowledgePermissionError,
    PlatformKnowledgeResourceError,
    PlatformKnowledgeUpstreamError,
)


class MockPlatformKnowledgeProvider:
    # TODO [F120][EXT-01] 真实目录由正式资源适配器提供。
    titles = {
        "mock:maintenance": "设备维护示例",
        "mock:policy": "制度查询示例",
        "mock:private": "私有知识示例",
        "mock:error": "检索失败场景",
        "mock:timeout": "检索超时场景",
        "mock:invalid": "来源异常场景",
        "mock:unavailable": "已失效知识库",
    }

    def __init__(self, config):
        self.config = config

    def subject(self, actor):
        # TODO [F120][EXT-02] 模拟标签仅用于裁剪合成内容、待接真实外部授权。
        if not self.config.mock_subjects:
            return "B"
        return self.config.mock_subjects.get(f"{actor.tenant_id}:{actor.user_id}", "C")

    async def check_use(self, actor, resource_id):
        if self.subject(actor) == "C" or (resource_id == "mock:private" and self.subject(actor) != "A"):
            raise PlatformKnowledgePermissionError()
        if resource_id not in self.titles or resource_id == "mock:unavailable":
            raise PlatformKnowledgeResourceError()

    async def get_knowledge(self, actor, resource_id):
        await self.check_use(actor, resource_id)
        return self._item(resource_id)

    def _item(self, resource_id):
        return {
            "resource_id": resource_id,
            "name": self.titles[resource_id],
            "status": "active",
            "provider_mode": "mock",
        }

    async def list_knowledge(self, actor, cursor, name):
        subject = self.subject(actor)
        ids = [
            key
            for key, title in self.titles.items()
            if subject != "C"
            and key != "mock:unavailable"
            and (key != "mock:private" or subject == "A")
            and (not name or name in title)
        ]
        if cursor is not None and cursor not in ids:
            raise PlatformKnowledgeConfigurationError()
        start = ids.index(cursor) + 1 if cursor else 0
        page = ids[start : start + 5]
        return {
            "items": [self._item(key) for key in page],
            "next_cursor": page[-1] if start + len(page) < len(ids) else None,
        }

    async def retrieve(self, actor, resource_id, query, top_k, call_id):
        await self.check_use(actor, resource_id)
        if resource_id == "mock:timeout":
            await asyncio.sleep(self.config.retrieve_timeout_seconds + 1)
        if resource_id == "mock:error":
            raise PlatformKnowledgeUpstreamError()
        if resource_id == "mock:invalid":
            return [{"text": "故障样例"}]
        # TODO [F120][EXT-03] 通过正式检索适配器替换合成片段与故障样例。
        fixtures = {
            "mock:maintenance": ("轴承", "模拟设备维护手册", "优先检查润滑和负载、按设备规程处理温度异常。"),
            "mock:policy": ("制度", "模拟制度手册", "按制度登记并由负责人审核。"),
            "mock:private": ("设备", "模拟私有规程", "联系维护主管确认设备检查范围。"),
        }
        keyword, title, text = fixtures.get(resource_id, ("", "", ""))
        if not keyword or keyword not in query:
            return []
        rows = [
            {
                "resource_id": resource_id,
                "document_id": "mock:doc-001",
                "chunk_id": "mock:chunk-001",
                "document_name": title,
                "location": "第 12 页",
                "text": text,
                "score": 0.91,
            }
        ]
        if resource_id == "mock:maintenance" and self.subject(actor) == "A":
            rows.append(
                {
                    **rows[0],
                    "document_id": "mock:doc-002",
                    "chunk_id": "mock:chunk-002",
                    "document_name": "模拟维护负责人手册",
                    "text": "由维护负责人登记复核记录。",
                }
            )
        return rows[:top_k]
