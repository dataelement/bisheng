from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.models.space_channel_member import SpaceChannelMember, BusinessTypeEnum, UserRoleEnum
from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.common.repositories.interfaces.space_channel_member_repository import SpaceChannelMemberRepository


class SpaceChannelMemberRepositoryImpl(BaseRepositoryImpl[SpaceChannelMember, str], SpaceChannelMemberRepository):
    """SpaceChannelMember repository implementation for managing space and channel memberships."""

    def __init__(self, session: AsyncSession):
        super().__init__(session, SpaceChannelMember)

    async def add_member(self, business_id: str, business_type: BusinessTypeEnum, user_id: int, role: UserRoleEnum,
                         status: bool = True) -> SpaceChannelMember:
        """Add a member to a space or channel."""
        new_member = SpaceChannelMember(
            business_id=business_id,
            business_type=business_type,
            user_id=user_id,
            user_role=role,
            status=status
        )
        new_member = await self.save(new_member)
        return new_member
