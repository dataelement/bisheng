"""Expose the authenticated public identity without adding business grants."""

from bisheng.public_endpoints.domain.context import get_current_public_api_principal

__all__ = ["get_current_public_api_principal"]
