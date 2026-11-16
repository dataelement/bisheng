"""Local API aliases; shared admission is exported through application."""

from bisheng.open_api.application.kunlian_http import (
    KunlianApiRoute,
    get_kunlian_request_user,
    kunlian_capability,
)

__all__ = ["KunlianApiRoute", "get_kunlian_request_user", "kunlian_capability"]
