import secrets
from pathlib import Path
from typing import Optional

from bisheng.services.settings.constants import DEFAULT_SUPERUSER, DEFAULT_SUPERUSER_PASSWORD
from bisheng.services.settings.utils import read_secret_from_file, write_secret_to_file
from loguru import logger
from passlib.context import CryptContext
from pydantic import Field, field_validator
from pydantic_settings import SettingsConfigDict, BaseSettings


class AuthSettings(BaseSettings):
    # Login settings
    CONFIG_DIR: str
    SECRET_KEY: str = Field(
        default='',
        description='Secret key for JWT. If not provided, a random one will be generated.',
        frozen=False,
    )
    ALGORITHM: str = 'HS256'
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 12 * 7

    # API Key to execute /process endpoint
    API_KEY_SECRET_KEY: Optional[str] = 'b82818e0ad4ff76615c5721ee21004b07d84cd9b87ba4d9cb42374da134b841a'
    API_KEY_ALGORITHM: str = 'HS256'
    API_V1_STR: str = '/api/v1'

    # If AUTO_LOGIN = True
    # > The application does not request login and logs in automatically as a super user.
    AUTO_LOGIN: bool = True
    NEW_USER_IS_ACTIVE: bool = False
    SUPERUSER: str = DEFAULT_SUPERUSER
    SUPERUSER_PASSWORD: str = DEFAULT_SUPERUSER_PASSWORD

    pwd_context: CryptContext = CryptContext(schemes=['bcrypt'], deprecated='auto')
    model_config = SettingsConfigDict(validate_assignment=True, extra='ignore', env_prefix='bisheng_')

    def reset_credentials(self):
        self.SUPERUSER = DEFAULT_SUPERUSER
        self.SUPERUSER_PASSWORD = DEFAULT_SUPERUSER_PASSWORD

    @field_validator('SECRET_KEY', mode='before')
    @classmethod
    def get_secret_key(cls, value, values):
        config_dir = values.get('CONFIG_DIR')

        if not config_dir:
            logger.debug('No CONFIG_DIR provided, not saving secret key')
            return value or secrets.token_urlsafe(32)

        secret_key_path = Path(config_dir) / 'secret_key'

        if value:
            logger.debug('Secret key provided')
            write_secret_to_file(secret_key_path, value)
        else:
            logger.debug('No secret key provided, generating a random one')

            if secret_key_path.exists():
                value = read_secret_from_file(secret_key_path)
                logger.debug('Loaded secret key')
                if not value:
                    value = secrets.token_urlsafe(32)
                    write_secret_to_file(secret_key_path, value)
                    logger.debug('Saved secret key')
            else:
                value = secrets.token_urlsafe(32)
                write_secret_to_file(secret_key_path, value)
                logger.debug('Saved secret key')

        return value
