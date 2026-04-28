"""Dataclasses used by F006 permission migration scripts."""

from dataclasses import asdict, dataclass, field


@dataclass
class MigrationStats:
    step1_super_admin: int = 0
    step2_user_group: int = 0
    step3_role_access: int = 0
    step3_raw: int = 0
    step4_space_channel: int = 0
    step5_resource_owners: int = 0
    step5_by_type: dict = field(default_factory=dict)
    step6_folder_hierarchy: int = 0
    step6_folders: int = 0
    step6_files: int = 0
    step7_department_membership: int = 0
    step8_group_resources: int = 0
    total: int = 0
    by_object_type: dict = field(default_factory=dict)
    by_relation: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class VerifyReport:
    total: int = 0
    match: int = 0
    regression: int = 0
    expansion: int = 0
