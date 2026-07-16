from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.errcode.knowledge_space import (
    DepartmentKnowledgeSpaceExistsError,
    SpaceInvalidScopeOwnerError,
)
from bisheng.common.models.space_channel_member import (
    BusinessTypeEnum,
    MembershipStatusEnum,
    SpaceChannelMember,
    UserRoleEnum,
)
from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.knowledge.domain.models.department_knowledge_space import DepartmentKnowledgeSpace
from bisheng.knowledge.domain.models.knowledge_space_scope import (
    KnowledgeSpaceLevelEnum,
    KnowledgeSpaceOwnerTypeEnum,
    KnowledgeSpaceScope,
)
from bisheng.knowledge.domain.repositories.interfaces.department_space_binding_repository import (
    DepartmentSpaceBindingRepository,
    DepartmentSpaceRebindPlan,
)


class DepartmentSpaceBindingRepositoryImpl(
    BaseRepositoryImpl[DepartmentKnowledgeSpace, int],
    DepartmentSpaceBindingRepository,
):
    def __init__(self, session: AsyncSession):
        super().__init__(session, DepartmentKnowledgeSpace)
        self._prepared_binding: DepartmentKnowledgeSpace | None = None

    async def rebind_department(
        self,
        *,
        space_id: int,
        department_id: int,
        operator_id: int,
    ) -> DepartmentKnowledgeSpace:
        await self.prepare_rebind_department(
            space_id=space_id,
            department_id=department_id,
            operator_id=operator_id,
            creator_user_id=operator_id,
            old_admin_user_ids=set(),
            new_admin_user_ids=set(),
            revoke_old_department_viewer=True,
        )
        return await self.commit_prepared_rebind()

    async def prepare_rebind_department(
        self,
        *,
        space_id: int,
        department_id: int,
        operator_id: int,
        creator_user_id: int,
        old_admin_user_ids: set[int],
        new_admin_user_ids: set[int],
        revoke_old_department_viewer: bool = True,
    ) -> DepartmentSpaceRebindPlan:
        try:
            scope_result = await self.session.exec(
                select(KnowledgeSpaceScope)
                .where(KnowledgeSpaceScope.space_id == space_id)
                .with_for_update()
            )
            scope = scope_result.first()
            if (
                scope is None
                or scope.level != KnowledgeSpaceLevelEnum.DEPARTMENT
                or scope.owner_type != KnowledgeSpaceOwnerTypeEnum.DEPARTMENT
            ):
                raise SpaceInvalidScopeOwnerError(msg="仅部门知识库可以修改所属部门")

            target_result = await self.session.exec(
                select(DepartmentKnowledgeSpace)
                .where(DepartmentKnowledgeSpace.department_id == department_id)
                .with_for_update()
            )
            target_binding = target_result.first()
            if target_binding is not None and int(target_binding.space_id) != space_id:
                raise DepartmentKnowledgeSpaceExistsError(msg="该部门已有知识库")

            current_result = await self.session.exec(
                select(DepartmentKnowledgeSpace)
                .where(DepartmentKnowledgeSpace.space_id == space_id)
                .with_for_update()
            )
            current_binding = current_result.first()
            old_department_id = int(
                current_binding.department_id if current_binding is not None else scope.owner_id
            )
            is_noop = old_department_id == department_id

            scope.owner_type = KnowledgeSpaceOwnerTypeEnum.DEPARTMENT
            scope.owner_id = department_id
            self.session.add(scope)

            if current_binding is None:
                current_binding = DepartmentKnowledgeSpace(
                    tenant_id=scope.tenant_id,
                    department_id=department_id,
                    space_id=space_id,
                    created_by=operator_id,
                )
            else:
                # Only update ownership; preserve approval, safety, and creator settings.
                current_binding.department_id = department_id
            self.session.add(current_binding)

            manager_grant_user_ids: list[int] = []
            manager_revoke_user_ids: list[int] = []
            if not is_noop:
                old_only_admin_ids = (
                    {int(user_id) for user_id in old_admin_user_ids}
                    - {int(user_id) for user_id in new_admin_user_ids}
                    - {int(creator_user_id)}
                )
                new_only_admin_ids = (
                    {int(user_id) for user_id in new_admin_user_ids}
                    - {int(user_id) for user_id in old_admin_user_ids}
                    - {int(creator_user_id)}
                )
                impacted_user_ids = sorted(old_only_admin_ids | new_only_admin_ids)
                member_rows_by_user: dict[int, list[SpaceChannelMember]] = {}
                if impacted_user_ids:
                    member_result = await self.session.exec(
                        select(SpaceChannelMember)
                        .where(
                            SpaceChannelMember.business_id == str(space_id),
                            SpaceChannelMember.business_type == BusinessTypeEnum.SPACE,
                            col(SpaceChannelMember.user_id).in_(impacted_user_ids),
                        )
                        .with_for_update()
                    )
                    for member in member_result.all():
                        member_rows_by_user.setdefault(int(member.user_id), []).append(member)

                for user_id in sorted(old_only_admin_ids):
                    member_rows = member_rows_by_user.get(user_id, [])
                    member = next(
                        (row for row in member_rows if row.membership_source == "department_admin"),
                        None,
                    )
                    if member is None:
                        continue
                    previous_role = member.department_admin_promoted_from_role
                    previous_role_value = str(previous_role or "").lower()
                    has_other_manager_membership = any(
                        row is not member
                        and row.user_role in {UserRoleEnum.CREATOR, UserRoleEnum.ADMIN}
                        for row in member_rows
                    )
                    if not has_other_manager_membership and previous_role_value not in {
                        UserRoleEnum.CREATOR.value,
                        UserRoleEnum.ADMIN.value,
                    }:
                        manager_revoke_user_ids.append(user_id)
                    if previous_role:
                        member.user_role = UserRoleEnum(previous_role)
                        member.membership_source = "manual"
                        member.department_admin_promoted_from_role = None
                        member.status = MembershipStatusEnum.ACTIVE
                        self.session.add(member)
                    else:
                        await self.session.delete(member)

                for user_id in sorted(new_only_admin_ids):
                    member_rows = member_rows_by_user.get(user_id, [])
                    if any(
                        member.user_role in {UserRoleEnum.CREATOR, UserRoleEnum.ADMIN}
                        for member in member_rows
                    ):
                        # Existing manual or automatic admins already have a manager tuple.
                        continue
                    member = member_rows[0] if member_rows else None
                    if member is not None:
                        previous_role = getattr(member.user_role, "value", member.user_role)
                        member.department_admin_promoted_from_role = str(previous_role)
                        member.user_role = UserRoleEnum.ADMIN
                        member.status = MembershipStatusEnum.ACTIVE
                        member.membership_source = "department_admin"
                        self.session.add(member)
                    else:
                        member = SpaceChannelMember(
                            business_id=str(space_id),
                            business_type=BusinessTypeEnum.SPACE,
                            user_id=user_id,
                            user_role=UserRoleEnum.ADMIN,
                            status=MembershipStatusEnum.ACTIVE,
                            membership_source="department_admin",
                        )
                        self.session.add(member)
                    manager_grant_user_ids.append(user_id)

            self._prepared_binding = current_binding
            return DepartmentSpaceRebindPlan(
                space_id=space_id,
                old_department_id=old_department_id,
                new_department_id=department_id,
                manager_grant_user_ids=tuple(manager_grant_user_ids),
                manager_revoke_user_ids=tuple(manager_revoke_user_ids),
                revoke_old_department_viewer=revoke_old_department_viewer,
                is_noop=is_noop,
            )
        except Exception:
            await self.session.rollback()
            self._prepared_binding = None
            raise

    async def commit_prepared_rebind(self) -> DepartmentKnowledgeSpace:
        if self._prepared_binding is None:
            raise RuntimeError("Department rebind has not been prepared")
        try:
            await self.session.flush()
            await self.session.commit()
            binding = self._prepared_binding
            self._prepared_binding = None
            return binding
        except IntegrityError as exc:
            await self.session.rollback()
            self._prepared_binding = None
            raise DepartmentKnowledgeSpaceExistsError(
                exception=exc,
                msg="该部门已有知识库",
            ) from exc
        except Exception:
            await self.session.rollback()
            self._prepared_binding = None
            raise

    async def rollback_prepared_rebind(self) -> None:
        await self.session.rollback()
        self._prepared_binding = None
