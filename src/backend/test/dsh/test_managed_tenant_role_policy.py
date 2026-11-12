"""DSH inherits the same current E and home-only department support."""

from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.dsh.domain.repositories.subject_policy import DshSubjectPolicyRepository
from test.fixtures.managed_tenant import managed_db as managed_db
from test.role.test_effective_roles import policy_db as policy_db


async def test_dsh_role_and_department_scopes_match_current_home(policy_db):
    with tenant_execution_scope(2), policy_db.sync_sessions() as session:
        repo = DshSubjectPolicyRepository(session)
        assert repo._role_ids(77) == {2, 3}
        assert repo._department_ancestor_ids(77, []) == {20, 30}
        assert {row.id for row in repo._departments()} == {20, 30}
