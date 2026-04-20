from fastapi import Depends

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.share_link.api.dependencies import header_share_token_parser
from bisheng.share_link.domain.models.share_link import ShareLink

LoginUserDep = Depends(UserPayload.get_login_user)
AdminUserDep = Depends(UserPayload.get_admin_user)
ShareLinkDep = Depends(header_share_token_parser)

__all__ = ['LoginUserDep', 'AdminUserDep', 'ShareLink', 'ShareLinkDep', 'UserPayload']
