"""Frozen business boundary for the browser organization directory."""

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class DirectoryScope:
    tenant_id: int
    storage_tenant_id: int
    root_id: int
    root_path: str
    excluded_paths: tuple[str, ...]

    def contains(self, path):
        return bool(
            path
            and path.startswith(self.root_path)
            and not any(path.startswith(excluded) for excluded in self.excluded_paths)
        )


current_directory_scope = ContextVar("current_directory_scope", default=None)


@dataclass(frozen=True)
class DepartmentDisplayRecord:
    id: int
    name: str
    business_tenant_id: int
    storage_tenant_id: int
    status: str
