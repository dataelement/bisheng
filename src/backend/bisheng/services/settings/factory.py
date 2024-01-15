from pathlib import Path

from bisheng.services.factory import ServiceFactory
from bisheng.services.settings.service import SettingsService


class SettingsServiceFactory(ServiceFactory):
    def __init__(self):
        super().__init__(SettingsService)

    def create(self):
        # Here you would have logic to create and configure a SettingsService
        bisheng_dir = Path(__file__).parent.parent.parent
        return SettingsService.load_settings_from_yaml(str(bisheng_dir / 'config.yaml'))
