"""T532: root inventory has a real identity even before its first saved version.

覆盖 AC: AC-68, AC-71, AC-87, AC-88, AC-89
"""

import pytest
from sqlmodel import Session

from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.resource_reference.application.contracts import SourceRootKey
from bisheng.resource_reference.domain.models.business_resource_reference import BusinessResourceReference
from bisheng.resource_reference.domain.repositories.reference_repository import ReferenceRepository
from test.knowledge_unification import test_ref_repo as fixtures

tenant_events = fixtures.tenant_events
engine = fixtures.engine


def test_empty_draft_root_inventory_does_not_invent_a_source_version(engine):
    root = SourceRootKey(101, "hosted_app_version", "draft-app")
    assert not hasattr(root, "source_version")
    with Session(engine) as session:
        repo = ReferenceRepository()
        assert repo.list_source_sets_for_root(session, root, for_update=True) == ()
        assert repo.list_source_references_for_root(session, root, for_update=True) == ()
        assert not session.new and not session.dirty


def test_root_inventory_still_finds_orphan_raw_without_any_saved_version(engine):
    with Session(engine) as session:
        session.add(
            BusinessResourceReference(
                tenant_id=101,
                source_type="hosted_app_version",
                source_id="draft-app",
                source_version="lost-real-version",
                slot_key="model",
                target_type="model",
                target_id="11",
                target_tenant_id=101,
                source_revision=1,
            )
        )
        session.commit()
        root = SourceRootKey(101, "hosted_app_version", "draft-app")
        repo = ReferenceRepository()
        assert repo.list_source_sets_for_root(session, root) == ()
        rows = repo.list_source_references_for_root(session, root, for_update=True)
        assert len(rows) == 1 and rows[0].source_version == "lost-real-version"


def test_root_inventory_does_not_relax_current_tenant_scope(engine):
    with Session(engine) as session, pytest.raises(ResourceReferenceInvalidError):
        ReferenceRepository().list_source_references_for_root(
            session, SourceRootKey(202, "hosted_app_version", "draft-app")
        )


@pytest.mark.parametrize(
    "tenant_id,source_type,source_id",
    [(0, "knowledge", "1"), (True, "knowledge", "1"), (101, "unknown", "1"), (101, "knowledge", "")],
)
def test_root_identity_has_the_same_strict_shape_as_saved_sources(tenant_id, source_type, source_id):
    with pytest.raises(ValueError):
        SourceRootKey(tenant_id, source_type, source_id)
