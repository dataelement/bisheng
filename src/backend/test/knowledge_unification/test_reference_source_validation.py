"""T281: source validity is stricter than allowing an original invalid slot to save.

覆盖 AC: AC-37, AC-68, AC-89, AC-91, AC-92
This checks existing runtime behavior with real index transactions; cross-tenant
execution scopes are deliberately not inferred from the management view.
"""

import pytest
from sqlmodel import Session

from bisheng.common.errcode.knowledge import ReferenceCoverageNotReadyError, ResourceReferenceInvalidError
from bisheng.resource_reference.application.contracts import ReferenceSpec, TargetKey
from test.knowledge_unification import test_binding_write_runtime as fixture

engine = fixture.engine
tenant_events = fixture.tenant_events


def test_ready_source_matches_actual_business_configuration(engine):
    rt, owner = fixture.runtime()
    with Session(engine) as session, session.begin():
        rt.apply_source_bindings(session, fixture.prepare(rt, owner, session))
        rt.require_source_valid(session, fixture.KEY, references=(fixture.MODEL,))
        with pytest.raises(ReferenceCoverageNotReadyError):
            rt.require_source_valid(session, fixture.KEY, references=(ReferenceSpec("model", TargetKey("model", "2")),))


@pytest.mark.parametrize("state", ["invalid_deleted", "deleting"])
def test_remaining_invalid_target_blocks_execution_without_rewriting_config(engine, state):
    rt, owner = fixture.runtime()
    with Session(engine) as session, session.begin():
        rt.apply_source_bindings(session, fixture.prepare(rt, owner, session))
        owner.state = state
        with pytest.raises(ResourceReferenceInvalidError):
            rt.require_source_valid(session, fixture.KEY, references=(fixture.MODEL,))
        assert rt.repository.get_source_set(session, fixture.KEY).source_revision == 1
        assert [row.target_id for row in rt.repository.list_source_references(session, fixture.KEY)] == ["1"]


def test_unindexed_and_inactive_sources_do_not_execute(engine):
    rt, owner = fixture.runtime()
    with Session(engine) as session, session.begin():
        with pytest.raises(ReferenceCoverageNotReadyError):
            rt.require_source_valid(session, fixture.KEY)
        rt.apply_source_bindings(session, fixture.prepare(rt, owner, session))
        terminal = fixture.prepare(rt, owner, session, new_source=False, references=(), effective=False)
        rt.apply_source_bindings(session, terminal)
        with pytest.raises(ResourceReferenceInvalidError):
            rt.require_source_valid(session, fixture.KEY, references=())


def test_ready_zero_reference_source_is_valid(engine):
    rt, owner = fixture.runtime()
    with Session(engine) as session, session.begin():
        rt.apply_source_bindings(session, fixture.prepare(rt, owner, session, references=()))
        rt.require_source_valid(session, fixture.KEY, references=())
