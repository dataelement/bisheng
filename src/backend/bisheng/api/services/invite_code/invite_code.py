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
        使用邀请码
        :param user_id: 用户ID
        :return: 邀请码使用结果
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
        撤销邀请码
        :param user_id: 用户ID
        :return: 邀请码撤销结果
        """
        logger.debug(f"revoke_invite_code {user_id}")

        codes = await InviteCodeDao.get_user_all_code(user_id)
        for one in codes:
            # 说明是崭新的邀请码，未被使用
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
        批量创建邀请码
        :param login_user: 操作用户信息
        :param name: 邀请码名称
        :param num: 邀请码数量
        :param limit: 每个邀请码的使用次数
        :return: 创建的邀请码列表
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
        # 检查生成的邀请码是否重复
        unique_codes = []
        for code in code_list:
            if code.code in unique_codes:
                raise ValueError(f"Duplicate invite code found: {code.code}")
            unique_codes.append(code.code)

        # 调用数据库操作来保存邀请码
        await InviteCodeDao.insert_invite_code(code_list)
        return unique_codes

    @classmethod
    async def get_invite_code_num(cls, login_user: UserPayload) -> int:
        """
        获取用户可用的邀请码的使用次数
        :param login_user: 操作用户信息
        :return: 邀请码使用次数
        """
        nums = 0
        codes = await InviteCodeDao.get_user_bind_code(login_user.user_id)
        for one in codes:
            nums += one.limit - one.used
        return nums

    @classmethod
    async def bind_invite_code(cls, login_user: UserPayload, code: str) -> bool:
        """
        绑定邀请码
        :param login_user: 操作用户信息
        :param code: 邀请码
        :return: 绑定结果
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
