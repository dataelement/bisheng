from typing import TYPE_CHECKING

from bisheng.services.factory import ServiceFactory
from bisheng.services.store.service import StoreService

if TYPE_CHECKING:
    from bisheng.services.settings.service import SettingsService


class StoreServiceFactory(ServiceFactory):
    def __init__(self):
        super().__init__(StoreService)

    def create(self, settings_service: 'SettingsService'):
        return StoreService(settings_service)
