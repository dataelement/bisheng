from loguru import logger

from bisheng.api.services.invite_code.code_validator import VoucherGenerator
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.linsight import InviteCodeBindError, InviteCodeInvalidError
from bisheng.database.models.invite_code import InviteCode, InviteCodeDao
from bisheng.utils import generate_uuid


class InviteCodeService:

    @classmethod
    async def use_invite_code(cls, user_id: int) -> bool:
        """
        using referral code
        :param user_id: UsersID
        :return: Invitation code results
        """
        logger.debug(f"use_invite_code {user_id}")

        codes = await InviteCodeDao.get_user_bind_code(user_id)
        for one in codes:
            flag = await InviteCodeDao.use_invite_code(user_id, one.code)
            if flag:
                logger.debug(f"use_invite_code {user_id}, {one.code} success")
                return True

        return False

    @classmethod
    async def revoke_invite_code(cls, user_id: int) -> bool:
        """
        Revoke Invitation Code
        :param user_id: UsersID
        :return: Invitation code revocation result
        """
        logger.debug(f"revoke_invite_code {user_id}")

        codes = await InviteCodeDao.get_user_all_code(user_id)
        for one in codes:
            # Description is a brand new invite code and has not been used
            if one.used <= 0:
                continue
            flag = await InviteCodeDao.revoke_invite_code_used(user_id, one.code)
            if flag:
                logger.debug(f"revoke_invite_code {user_id}, {one.code} success")
                return True

        return False

    @classmethod
    async def create_batch_invite_codes(cls, login_user: UserPayload, name: str, num: int, limit: int) -> list[str]:
        """
        Bulk create invite codes
        :param login_user: Action user information
        :param name: Invitation code name
        :param num: How many codes
        :param limit: Number of uses per invite code
        :return: Invitation code list created
        """
        generator = VoucherGenerator()
        code_list = []
        batch_id = generate_uuid()
        for i in range(num):
            code_list.append(InviteCode(
                code=generator.generate_voucher(),
                batch_id=batch_id,
                batch_name=name,
                limit=limit,
                created_id=login_user.user_id,
            ))
        # Check if the generated invite code is a duplicate
        unique_codes = []
        for code in code_list:
            if code.code in unique_codes:
                raise ValueError(f"Duplicate invite code found: {code.code}")
            unique_codes.append(code.code)

        # Call the database operation to save the invite code
        await InviteCodeDao.insert_invite_code(code_list)
        return unique_codes

    @classmethod
    async def get_invite_code_num(cls, login_user: UserPayload) -> int:
        """
        Get the number of times a user can use an invite code
        :param login_user: Action user information
        :return: Invitation code usage
        """
        nums = 0
        codes = await InviteCodeDao.get_user_bind_code(login_user.user_id)
        for one in codes:
            nums += one.limit - one.used
        return nums

    @classmethod
    async def bind_invite_code(cls, login_user: UserPayload, code: str) -> bool:
        """
        Binding Invitation Code
        :param login_user: Action user information
        :param code: Invitation Code
        :return: Binding Results
        """
        generator = VoucherGenerator()
        flag, _ = generator.validate_voucher(code)
        if not flag:
            raise InviteCodeInvalidError()
        codes = await InviteCodeDao.get_user_bind_code(login_user.user_id)
        if codes:
            raise InviteCodeBindError()

        flag = await InviteCodeDao.bind_invite_code(login_user.user_id, code)
        if not flag:
            raise InviteCodeInvalidError()
        return flag
