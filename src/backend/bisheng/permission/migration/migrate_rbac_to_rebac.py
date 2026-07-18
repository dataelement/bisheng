"""Compatibility entry point for F006 RBAC to ReBAC permission migration.

The implementation is split across focused modules:
  - f006_constants.py: mapping constants and batch/checkpoint settings
  - f006_schemas.py: migration result dataclasses
  - f006_migrator.py: migration pipeline implementation
  - f006_cli.py: command-line entry point
"""

from bisheng.permission.migration.f006_cli import main
from bisheng.permission.migration.f006_constants import (
    ACCESS_TYPE_MAPPING,
    FLOW_TYPE_MAPPING,
    GROUP_RESOURCE_TYPE_MAPPING,
    KNOWLEDGE_LEGACY_TYPES,
    RELATION_PRIORITY,
    SCM_ROLE_MAPPING,
    SCM_TYPE_MAPPING,
    _BATCH_SIZE,
    _CHECKPOINT_FILENAME,
)
from bisheng.permission.migration.f006_migrator import RBACToReBACMigrator
from bisheng.permission.migration.f006_schemas import MigrationStats, VerifyReport

__all__ = [
    'ACCESS_TYPE_MAPPING',
    'FLOW_TYPE_MAPPING',
    'GROUP_RESOURCE_TYPE_MAPPING',
    'KNOWLEDGE_LEGACY_TYPES',
    'MigrationStats',
    'RBACToReBACMigrator',
    'RELATION_PRIORITY',
    'SCM_ROLE_MAPPING',
    'SCM_TYPE_MAPPING',
    'VerifyReport',
    '_BATCH_SIZE',
    '_CHECKPOINT_FILENAME',
    'main',
]


if __name__ == '__main__':
    main()
