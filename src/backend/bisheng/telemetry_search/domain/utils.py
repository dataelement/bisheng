from bisheng.common.services.config_service import settings


def is_commercial() -> bool:
    """Determine if the current version is a commercial version"""
    return settings.get_system_login_method().dashboard_pro
