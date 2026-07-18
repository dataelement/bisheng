"""F041: revoke v2.5.1 F017 default Root→Child business-resource sharing.

v2.5.1 F017 fanned Root-created knowledge_space / workflow / assistant / channel
/ tool out to every active Child via OpenFGA ``shared_with → tenant:{cid}``
tuples plus a mirror ``{table}.is_shared = 1`` column. v2.6.0-beta2 retires
this default-sharing path (owners grant access through ReBAC). This migration
purges the stale tuples + flips the mirror column so existing installations
match the new behavior right after ``alembic upgrade head``.

Core logic lives in ``scripts/revoke_business_resource_share.py`` (also
runnable on its own for maintenance windows / re-runs). The migration is a
thin wrapper around ``revoke()`` so the wrapper and the standalone script
share one code path.

Failure handling: the wrapper logs and *swallows* any exception from the
script — OpenFGA may not be reachable from the alembic host (e.g. when
upgrading before the OpenFGA service is started). The operator can rerun
``python -m scripts.revoke_business_resource_share`` afterward; the script is
idempotent.

No schema change. ``is_shared`` column itself stays — it still backs llm_server
sharing and may be reused by future per-resource ReBAC features.

Revision ID: f041_revoke_business_resource_share
Revises: f040_tag_library_owner_knowledge
Create Date: 2026-05-24
"""

from __future__ import annotations

import asyncio
import logging
from typing import Sequence, Union

revision: str = 'f041_revoke_business_resource_share'
down_revision: Union[str, Sequence[str], None] = 'f040_tag_library_owner_knowledge'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_logger = logging.getLogger(__name__)


def upgrade() -> None:
    try:
        from scripts.revoke_business_resource_share import (
            RETIRED_SHAREABLE_TYPES,
            revoke,
        )
    except Exception as exc:  # pragma: no cover - import-time guard
        _logger.warning(
            '[F041] could not import revoke script (%s); skipping. '
            'Run `python -m scripts.revoke_business_resource_share` manually '
            'after the upgrade completes.', exc,
        )
        return

    try:
        rc = asyncio.run(revoke(types_filter=RETIRED_SHAREABLE_TYPES, dry_run=False))
    except Exception as exc:
        _logger.warning(
            '[F041] revoke step failed (%s); upgrade continues. '
            'Run `python -m scripts.revoke_business_resource_share` manually '
            'to retry.', exc,
        )
        return

    if rc != 0:
        _logger.warning('[F041] revoke returned non-zero (%s); see prior log lines.', rc)


def downgrade() -> None:
    # No-op: the F017 default-share behavior is removed from the codebase,
    # so re-creating the tuples on downgrade would be inconsistent with the
    # downgraded code. Operators who need to roll back the data side can
    # re-enable share_default_to_children on the Root tenant and recreate
    # resources, or write the tuples by hand.
    pass
