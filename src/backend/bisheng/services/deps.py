from typing import TYPE_CHECKING

from bisheng.services import ServiceType, service_manager

if TYPE_CHECKING:
    from bisheng.services.session.service import SessionService
    from bisheng.services.task.service import TaskService
    # from sqlmodel import Session

# def get_credential_service() -> "CredentialService":
#     return service_manager.get(ServiceType.CREDENTIAL_SERVICE)  # type: ignore

# def get_plugins_service() -> "PluginService":
#     return service_manager.get(ServiceType.PLUGIN_SERVICE)  # type: ignore

# def get_settings_service() -> "SettingsService":
#     try:
#         # type: ignore
#         return service_manager.get(ServiceType.SETTINGS_SERVICE)
#     except ValueError:
#         # initialize settings service
#         from langflow.services.manager import initialize_settings_service

#         initialize_settings_service()
#         # type: ignore
#         return service_manager.get(ServiceType.SETTINGS_SERVICE)

# def get_db_service() -> "DatabaseService":
#     return service_manager.get(ServiceType.DATABASE_SERVICE)  # type: ignore

# def get_session() -> Generator["Session", None, None]:
#     db_service = get_db_service()
#     yield from db_service.get_session()

# def get_cache_service() -> "BaseCacheService":
#     return service_manager.get(ServiceType.CACHE_SERVICE)  # type: ignore


def get_session_service() -> 'SessionService':
    return service_manager.get(ServiceType.SESSION_SERVICE)  # type: ignore


def get_task_service() -> 'TaskService':
    return service_manager.get(ServiceType.TASK_SERVICE)  # type: ignore


# def get_chat_service() -> "ChatService":
#     return service_manager.get(ServiceType.CHAT_SERVICE)  # type: ignore

# def get_store_service() -> "StoreService":
#     return service_manager.get(ServiceType.STORE_SERVICE)  # type: ignore
