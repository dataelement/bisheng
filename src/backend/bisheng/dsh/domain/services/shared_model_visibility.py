"""Public DSH boundary for explicitly frozen new shared-model defaults.

The authenticated model owner supplies its original request guard and native
transaction. This entry only initializes absent policies; it never widens an
administrator's existing restriction or modifies credits.
"""

from bisheng.common.errcode.dsh import DshOperationConflictError
from bisheng.dsh.domain.repositories.shared_model_visibility import SharedModelVisibilityRepository


async def initialize_shared_model_visibility(session, *, child_ids, model_ids, actor_user_id, plan_id, guard):
    guard()
    if type(actor_user_id) is not int or actor_user_id <= 0 or not isinstance(plan_id, str) or not plan_id:
        raise DshOperationConflictError()
    if any(type(value) is not int or value <= 1 for value in child_ids) or any(
        type(value) is not int or value <= 0 for value in model_ids
    ):
        raise DshOperationConflictError()
    if child_ids and model_ids:
        await SharedModelVisibilityRepository().ainitialize(
            session, child_ids=child_ids, model_ids=model_ids, actor_user_id=actor_user_id, plan_id=plan_id, guard=guard
        )
    guard()
