"""Resolve display-only knowledge snapshots through existing authorization."""

from loguru import logger


class KnowledgeStepMetadataResolver:
    def __init__(self, *, load_rows=None, check_actions=None):
        self._load_rows = load_rows
        self._check_actions = check_actions

    async def resolve(self, login_user, candidates: list) -> dict[str, dict]:
        if login_user is None or not getattr(login_user, "tenant_id", None):
            return {}
        ids = {int(row.id) for row in candidates if str(getattr(row, "id", "")).isdigit()}
        if not ids:
            return {}
        try:
            loader = self._load_rows
            check = self._check_actions
            if loader is None:
                from bisheng.knowledge.domain.models.knowledge import KnowledgeDao

                loader = KnowledgeDao.aget_list_by_ids
            if check is None:
                from bisheng.permission.application.business_authorization import batch_check_business_actions

                check = batch_check_business_actions
            rows = await loader(sorted(ids))
            # Candidate selection is not visibility evidence. Re-read canonical
            # rows; the knowledge adapter verifies the real container binding.
            rows = [row for row in rows if row.id in ids and row.tenant_id == login_user.tenant_id]
            targets = {}
            for resource_type, kinds, kind in (
                ("knowledge_library", (0, 1), "knowledge_base"),
                ("knowledge_space", (3,), "space"),
            ):
                group = [row for row in rows if row.type in kinds]
                if not group:
                    continue
                visible = await check(
                    login_user,
                    resource_type=resource_type,
                    resource_ids=[str(row.id) for row in group],
                    actions=("visible",),
                )
                for row in group:
                    if "visible" in visible.get(str(row.id), set()):
                        target = {"version": 1, "knowledge_id": str(row.id), "kind": kind}
                        if isinstance(row.name, str) and 0 < len(row.name) <= 512:
                            target["name"] = row.name
                        targets[str(row.id)] = target
            for row in rows:
                if row.type == 2 and row.user_id == login_user.user_id:
                    targets[str(row.id)] = {"version": 1, "knowledge_id": str(row.id), "kind": "personal"}
            return targets
        except Exception as exc:
            # Display enrichment fails closed without changing retrieval policy.
            logger.warning("Knowledge step display metadata unavailable: {}", type(exc).__name__)
            return {}
