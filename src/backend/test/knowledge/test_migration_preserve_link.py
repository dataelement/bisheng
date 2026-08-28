"""F099: migrating with a link left behind is a publish, so it follows publish's rules.

The wizard's new mode does not invent a placement rule of its own — it reuses
the level ladder that publishing already enforces, because the two operations
produce the same result. These tests pin that equivalence down: if the publish
ladder ever changes, the migration rule has to move with it.
"""

from __future__ import annotations

import pytest

from bisheng.approval.domain.services.shougang_approval_handler import (
    FILE_PUBLISH_TARGET_LEVELS,
)
from bisheng.common.errcode.knowledge_migration import (
    MigrationPreserveLinkPublicSourceError,
    MigrationPreserveLinkSourceLevelMixedError,
    MigrationPreserveLinkTargetLevelError,
)
from bisheng.knowledge.domain.models.knowledge_space_scope import KnowledgeSpaceLevelEnum
from bisheng.knowledge.domain.services.migration_preserve_link_rules import (
    PRESERVE_LINK_PARENT_LEVELS,
    parent_levels_for,
    validate_preserve_link_levels,
)

PERSONAL = KnowledgeSpaceLevelEnum.PERSONAL
TEAM = KnowledgeSpaceLevelEnum.TEAM
TEAM_KS = KnowledgeSpaceLevelEnum.TEAM_KS
DEPARTMENT = KnowledgeSpaceLevelEnum.DEPARTMENT
PUBLIC = KnowledgeSpaceLevelEnum.PUBLIC


def test_parent_level_mapping_matches_publish():
    """The two ladders must stay identical, or the same move gets two answers."""
    assert PRESERVE_LINK_PARENT_LEVELS == FILE_PUBLISH_TARGET_LEVELS


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (PERSONAL, {TEAM, TEAM_KS}),
        (TEAM, {DEPARTMENT}),
        (TEAM_KS, {DEPARTMENT}),
        (DEPARTMENT, {PUBLIC}),
        (PUBLIC, set()),
    ],
)
def test_parent_level_mapping(source, expected):
    assert parent_levels_for(source) == expected


@pytest.mark.parametrize("level_input", ["personal", PERSONAL])
def test_parent_levels_accepts_raw_and_enum(level_input):
    assert parent_levels_for(level_input) == {TEAM, TEAM_KS}


def test_public_source_rejected():
    """A public space has nowhere to publish up to, so say that rather than 'invalid'."""
    with pytest.raises(MigrationPreserveLinkPublicSourceError):
        validate_preserve_link_levels(source_levels=[PUBLIC], target_level=PUBLIC)


def test_cross_level_source_rejected():
    with pytest.raises(MigrationPreserveLinkSourceLevelMixedError):
        validate_preserve_link_levels(
            source_levels=[PERSONAL, DEPARTMENT],
            target_level=TEAM,
        )


def test_target_must_be_parent_level():
    with pytest.raises(MigrationPreserveLinkTargetLevelError):
        validate_preserve_link_levels(source_levels=[PERSONAL], target_level=PUBLIC)


@pytest.mark.parametrize("target", [TEAM, TEAM_KS])
def test_personal_source_accepts_either_team_flavour(target):
    """The portal shows one 团队/科室 option; both back it, and both are valid."""
    validate_preserve_link_levels(source_levels=[PERSONAL, PERSONAL], target_level=target)


def test_department_to_public_is_allowed():
    validate_preserve_link_levels(source_levels=[DEPARTMENT], target_level=PUBLIC)


def test_empty_source_is_rejected_as_mixed():
    """No source level at all cannot be validated against a ladder."""
    with pytest.raises(MigrationPreserveLinkSourceLevelMixedError):
        validate_preserve_link_levels(source_levels=[], target_level=PUBLIC)


# ── Execution routing ────────────────────────────────────────────────


class _FakePublishService:
    def __init__(self, recorder: list):
        self.recorder = recorder

    async def publish_approved(self, command):
        self.recorder.append(command)


class _FakePublishServiceFactory:
    def __init__(self):
        self.commands: list = []

    def __call__(self):
        return self

    async def __aenter__(self):
        return _FakePublishService(self.commands)

    async def __aexit__(self, *exc_info):
        return False


def _unit(unit_id: int = 1):
    from bisheng.knowledge.domain.services.file_migration.executor import (
        MigrationExecutionUnit,
    )

    return MigrationExecutionUnit(
        unit_id=unit_id,
        attempt_id=7,
        execution_token="token",
    )


def _operations(context: dict):
    from bisheng.knowledge.domain.services.migration_preserve_link_operations import (
        PreserveLinkMigrationOperations,
    )

    factory = _FakePublishServiceFactory()

    async def loader(_unit_id: int) -> dict:
        return context

    return (
        PreserveLinkMigrationOperations(
            publish_service_factory=factory,
            context_loader=loader,
        ),
        factory,
    )


def _context(**overrides):
    base = {
        "tenant_id": 1,
        "document_id": 91,
        "source_entry_id": 100,
        "target_space_id": 20,
        "target_file_level_path": "/8",
        "target_level": 1,
        "target_document_id": None,
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    "step",
    [
        "create_target_rows",
        "copy_target_objects",
        "build_target_indexes",
        "write_target_permissions",
        "verify_target",
        "cleanup_source_external",
        "cleanup_source_rows",
        "cleanup_new_target",
    ],
)
async def test_copy_steps_do_nothing_in_preserve_link_mode(step):
    """Publishing owns the target side; the source row stays put as the shortcut."""
    operations, factory = _operations(_context())

    await getattr(operations, step)(_unit())

    assert factory.commands == []


async def test_switch_publishes_the_unit():
    operations, factory = _operations(_context())

    await operations.switch_database(_unit())

    assert len(factory.commands) == 1
    command = factory.commands[0]
    assert command.document_id == 91
    assert command.source_entry_id == 100
    assert command.target_space_id == 20
    assert command.target_file_level_path == "/8"
    assert command.target_level == 1
    assert command.target_document_id is None
    # Negative so it can never collide with a real approval instance.
    assert command.approval_instance_id < 0


async def test_switch_merges_when_preflight_reserved_a_target():
    operations, factory = _operations(_context(target_document_id=555))

    await operations.switch_database(_unit())

    assert factory.commands[0].target_document_id == 555


async def test_publish_instance_id_is_deterministic_and_negative():
    from bisheng.knowledge.domain.services.migration_preserve_link_operations import (
        preserve_link_instance_id,
    )

    first = preserve_link_instance_id(100, 20)
    assert first == preserve_link_instance_id(100, 20)
    assert first < 0
    assert first != preserve_link_instance_id(100, 21)


@pytest.mark.parametrize(
    ("path", "expected"),
    [(None, 0), ("", 0), ("/8", 1), ("/8/900", 2)],
)
def test_target_level_counts_folder_depth(path, expected):
    from bisheng.knowledge.domain.services.migration_preserve_link_operations import (
        _target_level_from_path,
    )

    assert _target_level_from_path(path) == expected


class _RecordingOperations:
    def __init__(self, label: str, log: list):
        self.label = label
        self.log = log

    def __getattr__(self, name):
        async def _record(*_args, **_kwargs):
            self.log.append((self.label, name))

        return _record


async def test_dispatcher_routes_by_batch_mode():
    from bisheng.knowledge.domain.services.migration_preserve_link_operations import (
        PreserveLinkAwareOperations,
    )

    log: list = []
    preserve_link_units = {2}

    async def lookup(unit_id: int) -> bool:
        return unit_id in preserve_link_units

    dispatcher = PreserveLinkAwareOperations(
        default_operations=_RecordingOperations("copy", log),
        preserve_link_operations=_RecordingOperations("publish", log),
        preserve_link_lookup=lookup,
    )

    await dispatcher.switch_database(_unit(1))
    await dispatcher.switch_database(_unit(2))

    assert log == [("copy", "switch_database"), ("publish", "switch_database")]


@pytest.mark.parametrize(
    ("overwrite_unit_key", "expected"),
    [
        (None, None),
        ("", None),
        ("document:555", 555),
        # Folder units are keyed differently and can never be merge targets.
        ("folder:12", None),
        ("document:not-a-number", None),
    ],
)
def test_merge_target_comes_from_the_overwrite_key(overwrite_unit_key, expected):
    """Not from the unit's target_document_id — that column holds the *source* id.

    The copy path carries the source document id straight through to the target,
    so reading it here would ask publish to merge a document into itself.
    """
    from bisheng.knowledge.domain.services.migration_preserve_link_operations import (
        _merge_target_document_id,
    )

    assert _merge_target_document_id(overwrite_unit_key) == expected


# ── Space listing ────────────────────────────────────────────────────


class _StubSourceRepository:
    def __init__(self, rows):
        self.rows = rows
        self.calls: list = []

    async def list_spaces(self, *, keyword, level, offset, limit, levels=None):
        self.calls.append({"level": level, "levels": levels})
        return list(self.rows), len(self.rows)


class _StubAdmin:
    def is_admin(self) -> bool:
        return True


def _space_row(space_id: int, level: str, name: str = "库"):
    from types import SimpleNamespace

    return SimpleNamespace(
        space=SimpleNamespace(id=space_id, name=name),
        level=level,
        owner_id=1,
    )


def _migration_service(rows):
    from types import SimpleNamespace

    from bisheng.knowledge.domain.services.knowledge_migration_service import (
        KnowledgeMigrationService,
    )

    repository = _StubSourceRepository(rows)
    return (
        KnowledgeMigrationService(
            repository=SimpleNamespace(),
            source_repository=repository,
            dispatcher=SimpleNamespace(),
        ),
        repository,
    )


async def test_target_listing_is_restricted_to_the_parent_level():
    service, repository = _migration_service([_space_row(1, "team")])

    await service.list_spaces(
        _StubAdmin(),
        keyword=None,
        space_level=None,
        page=1,
        page_size=20,
        purpose="target",
        preserve_link=True,
        source_level="personal",
    )

    # Personal publishes into either team flavour, so both must be offered.
    assert repository.calls[0]["levels"] == {"team", "team_ks"}


async def test_target_listing_is_empty_when_the_source_has_no_parent():
    service, repository = _migration_service([_space_row(1, "public")])

    page = await service.list_spaces(
        _StubAdmin(),
        keyword=None,
        space_level=None,
        page=1,
        page_size=20,
        purpose="target",
        preserve_link=True,
        source_level="public",
    )

    assert page.total == 0
    assert page.data == []
    assert repository.calls == []


async def test_public_source_is_listed_but_not_selectable():
    """Shown with a reason rather than hidden: the operator knows it exists."""
    service, _ = _migration_service([_space_row(1, "public"), _space_row(2, "team")])

    page = await service.list_spaces(
        _StubAdmin(),
        keyword=None,
        space_level=None,
        page=1,
        page_size=20,
        purpose="source",
        preserve_link=True,
    )

    by_id = {item["id"]: item for item in page.data}
    assert by_id[1]["selectable"] is False
    assert by_id[1]["unavailable_reason"]
    assert by_id[2]["selectable"] is True
    assert by_id[2]["unavailable_reason"] is None


async def test_normal_mode_listing_is_untouched():
    service, repository = _migration_service([_space_row(1, "public")])

    page = await service.list_spaces(
        _StubAdmin(),
        keyword=None,
        space_level="public",
        page=1,
        page_size=20,
    )

    assert repository.calls[0] == {"level": "public", "levels": None}
    assert page.data[0]["selectable"] is True
