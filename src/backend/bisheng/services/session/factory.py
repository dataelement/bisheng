from typing import TYPE_CHECKING

from bisheng.services.factory import ServiceFactory
from bisheng.services.session.service import SessionService

if TYPE_CHECKING:
    from bisheng.services.cache.service import BaseCacheService


class SessionServiceFactory(ServiceFactory):
    def __init__(self):
        super().__init__(SessionService)

    def create(self, cache_service: 'BaseCacheService'):
        return SessionService(cache_service)
