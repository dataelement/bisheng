"""``ORDER BY`` fragments are built from an allow-list, not from raw input."""

import pytest

from bisheng.knowledge.domain.models.knowledge_space_file import SpaceFileDao

# The sort keys the API contract exposes (``SortType`` in the web client).
SUPPORTED_FIELDS = ["file_name", "file_type", "file_size", "update_time"]
SUPPORTED_SORTS = ["asc", "desc"]


@pytest.mark.parametrize("order_field", SUPPORTED_FIELDS)
@pytest.mark.parametrize("order_sort", SUPPORTED_SORTS)
def test_accepts_every_supported_sort_key(order_field, order_sort):
    fragment = SpaceFileDao.order_field_text(order_field, order_sort)

    assert order_sort.upper() in fragment
    if order_field != "update_time":
        assert fragment.endswith(", update_time desc")


@pytest.mark.parametrize(
    "order_field",
    [
        "update_time, (select 1)",
        "(case when (select 1)=1 then id else file_name end)",
        "id; drop table knowledge_file",
        "id/**/",
        "unknown_column",
        "",
    ],
)
def test_rejects_unsupported_order_field(order_field):
    with pytest.raises(ValueError):
        SpaceFileDao.order_field_text(order_field, "asc")


@pytest.mark.parametrize(
    "order_sort",
    ["asc, (select 1)", "desc; drop table knowledge_file", "ascending", "", None],
)
def test_rejects_unsupported_order_sort(order_sort):
    with pytest.raises(ValueError):
        SpaceFileDao.order_field_text("file_name", order_sort)
