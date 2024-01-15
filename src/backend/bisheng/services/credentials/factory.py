from typing import TYPE_CHECKING

from bisheng.services.credentials.service import CredentialService
from bisheng.services.factory import ServiceFactory

if TYPE_CHECKING:
    from bisheng.services.settings.service import SettingsService


class CredentialServiceFactory(ServiceFactory):
    def __init__(self):
        super().__init__(CredentialService)

    def create(self, settings_service: 'SettingsService'):
        return CredentialService(settings_service)
