"""F018 T02: ResourceTypeRegistry tests."""

import pytest

from bisheng.common.errcode.resource_owner_transfer import (
    ResourceTransferUnsupportedTypeError,
)
from bisheng.tenant.domain.services.resource_type_registry import (
    REGISTRY,
    SUPPORTED_TYPES,
    get_meta,
)


def test_supported_types_exactly_7():
    assert len(SUPPORTED_TYPES) == 7
    assert 'dashboard' not in SUPPORTED_TYPES
    assert set(SUPPORTED_TYPES) == {
        'knowledge_space', 'folder', 'knowledge_file',
        'workflow', 'assistant', 'tool', 'channel',
    }


def test_get_meta_known_types_tables_match_orm():
    # Map confirmed against ORM definitions on 2026-04-21.
    table_map = {
        'knowledge_space': 'knowledge',
        'folder': 'knowledgefile',
        'knowledge_file': 'knowledgefile',
        'workflow': 'flow',
        'assistant': 'assistant',
        'tool': 't_gpts_tools',
        'channel': 'channel',
    }
    for rt, tbl in table_map.items():
        assert get_meta(rt).table == tbl


def test_get_meta_unknown_raises_19604():
    with pytest.raises(ResourceTransferUnsupportedTypeError) as exc:
        get_meta('dashboard')
    assert exc.value.Code == 19604


def test_id_types_split_between_int_and_uuid_string():
    # UUID-id resources.
    for rt in ('workflow', 'assistant', 'channel'):
        assert get_meta(rt).id_type is str
    # Integer-id resources.
    for rt in ('knowledge_space', 'folder', 'knowledge_file', 'tool'):
        assert get_meta(rt).id_type is int


def test_type_filters_only_for_shared_tables():
    # Types whose physical table carries variants need a filter.
    assert get_meta('knowledge_space').type_filter_sql == 'type = 3'
    assert get_meta('folder').type_filter_sql == 'file_type = 0'
    assert get_meta('knowledge_file').type_filter_sql == 'file_type = 1'
    assert get_meta('workflow').type_filter_sql == 'flow_type = 10'
    assert get_meta('tool').type_filter_sql == 'is_delete = 0'
    # Standalone tables — no additional filter needed.
    assert get_meta('assistant').type_filter_sql is None
    assert get_meta('channel').type_filter_sql is None


def test_registry_is_frozen_dataclass():
    meta = get_meta('workflow')
    with pytest.raises(Exception):
        meta.table = 'hacked'  # type: ignore[misc]  # frozen=True
