from bisheng.services.auth.service import AuthService
from bisheng.services.factory import ServiceFactory


class AuthServiceFactory(ServiceFactory):
    name = 'auth_service'

    def __init__(self):
        super().__init__(AuthService)

    def create(self, settings_service):
        return AuthService(settings_service)
