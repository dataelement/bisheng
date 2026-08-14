from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GrantSubjectDepartment:
    department_id: int
    dept_id: str
    name: str
    parent_id: int | None
    path: str
    short_name: str | None = None


@dataclass(frozen=True)
class GrantSubjectUserCandidate:
    user_id: int
    user_name: str
    external_id: str | None


@dataclass(frozen=True)
class GrantSubjectUserDepartmentLink:
    user_id: int
    department_id: int
    is_primary: bool


@dataclass(frozen=True)
class GrantSubjectDepartmentMembership:
    department_id: int
    dept_id: str
    name: str
    path: str
    is_primary: bool
    short_name: str | None = None
    display_name: str | None = None
    display_path: str | None = None

    def to_dict(self) -> dict:
        return {
            "department_id": self.department_id,
            "dept_id": self.dept_id,
            "name": self.name,
            "short_name": self.short_name,
            "display_name": self.display_name or self.name,
            "path": self.path,
            "display_path": self.display_path or self.path,
            "is_primary": self.is_primary,
        }


@dataclass(frozen=True)
class GrantSubjectUser:
    user_id: int
    user_name: str
    external_id: str | None
    department_memberships: tuple[GrantSubjectDepartmentMembership, ...]

    def to_dict(self) -> dict:
        department_paths = [membership.path for membership in self.department_memberships]
        department_display_paths = [
            membership.display_path or membership.path
            for membership in self.department_memberships
        ]
        primary_path = next(
            (membership.path for membership in self.department_memberships if membership.is_primary),
            None,
        )
        return {
            "user_id": self.user_id,
            "user_name": self.user_name,
            "external_id": self.external_id,
            "primary_department_path": primary_path,
            "department_paths": department_paths,
            "department_display_paths": department_display_paths,
            "department_memberships": [
                membership.to_dict() for membership in self.department_memberships
            ],
        }
