"""Register the runtime-delivery persistence graph before tenant discovery."""

from .runtime_delivery import RUNTIME_TABLES
from .runtime_kubernetes import KUBERNETES_TABLES

__all__ = ["KUBERNETES_TABLES", "RUNTIME_TABLES"]
