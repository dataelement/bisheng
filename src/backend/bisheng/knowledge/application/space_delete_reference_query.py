"""Optional whole-space impact, using actual current file membership."""

from bisheng.knowledge.application.direct_delete_reference_query import DirectDeleteReferenceQuery
from bisheng.knowledge.domain.repositories.space_delete_scope_repository import SpaceDeleteScopeRepository
from bisheng.resource_reference.application.contracts import TargetKey, TargetType
from bisheng.resource_reference.domain.repositories.reference_hint_repository import ReferenceHintRepository


class SpaceDeleteReferenceQuery(DirectDeleteReferenceQuery):
    def __init__(self, *, runtime=None, coverage_factory=None):
        super().__init__(scope_repository=SpaceDeleteScopeRepository())

    async def acollect_space(self, session, *, space_id, operation_id=None):
        self._context(session, space_id, ())
        scope = await self.scope.aread_space_scope(session, space_id=space_id)
        rows = await ReferenceHintRepository().aread(
            session, (TargetKey(TargetType.KNOWLEDGE_SPACE, str(space_id)),), space_id=space_id
        )
        return self.facts(scope, rows, {})
