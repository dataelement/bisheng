from .base import BaseErrorCode


# Return error code related to user module, function module code:106
class UserValidateError(BaseErrorCode):
    Code: int = 10600
    Msg: str = 'Account or password error'


class UserPasswordExpireError(BaseErrorCode):
    Code: int = 10601
    Msg: str = 'Your password has expired, please change it in time'


class UserNotPasswordError(BaseErrorCode):
    Code: int = 10602
    Msg: str = 'The user has not set a password, please contact the administrator to reset the password first'


class UserPasswordError(BaseErrorCode):
    Code: int = 10603
    Msg: str = 'wrong current password'


class UserLoginOfflineError(BaseErrorCode):
    Code: int = 10604
    Msg: str = "Your account is logged in on another device and the session on this device has been logged out.\nIf this wasn't you, please change your account password as soon as possible."


class UserNameAlreadyExistError(BaseErrorCode):
    Code: int = 10605
    Msg: str = 'User Name already exist'


class UserNeedGroupAndRoleError(BaseErrorCode):
    Code: int = 10606
    Msg: str = 'User group and role cannot be empty'


class CaptchaError(BaseErrorCode):
    Code: int = 10607
    Msg: str = 'Kode verifikasi salah'


class UserNameTooLongError(BaseErrorCode):
    Code: int = 10608
    Msg: str = 'Username length cannot exceed30characters'


class UserGroupNotDeleteError(BaseErrorCode):
    Code: int = 10610
    Msg: str = 'There are still users in the user group and cannot be deleted'


class UserForbiddenError(BaseErrorCode):
    Code: int = 10620
    Msg: str = 'The user is disabled, please contact the administrator'


class UserPasswordMaxTryError(BaseErrorCode):
    Code: int = 10621
    Msg: str = 'The account has been automatically disabled due to too many failed login attempts, please contact your administrator'


class UserGroupEmptyError(BaseErrorCode):
    Code: int = 10630
    Msg: str = 'User group cannot be empty'


class AdminUserUpdateForbiddenError(BaseErrorCode):
    Code: int = 10640
    Msg: str = 'Administrator user information cannot be modified'
