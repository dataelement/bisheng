"""Unit tests for the personal-space cleanup classification logic.

The DB/cascade side runs only inside the container; here we lock down the pure
keep / delete / skip decision that decides what the script touches.
"""

import importlib.util
import os
from types import SimpleNamespace

_SCRIPT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "scripts", "shougang_clean_personal_spaces.py")
)
_spec = importlib.util.spec_from_file_location("shougang_clean_personal_spaces", _SCRIPT)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def _space(sid, name, user_id, is_favorite=False):
    return SimpleNamespace(id=sid, name=name, user_id=user_id, is_favorite=is_favorite)


def test_default_name_helper():
    assert mod._personal_default_name("张三") == "张三的知识库"


def test_classify_keeps_favorite_and_default_deletes_the_rest():
    spaces = [
        _space(1, "我的收藏", 7, is_favorite=True),   # keep: favorite
        _space(2, "张三的知识库", 7),                  # keep: personal default
        _space(3, "个人知识库1", 7),                   # delete: empty legacy
        _space(4, "GR000113", 7),                      # skip: non-empty legacy
    ]
    file_counts = {3: 0, 4: 5}
    user_name_by_id = {7: "张三"}

    keep, to_delete, skipped, unknown = mod._classify(
        spaces, file_counts, user_name_by_id, include_non_empty=False
    )

    assert {r.id for r in keep} == {1, 2}
    assert {r.id for r in to_delete} == {3}
    assert {r.id for r in skipped} == {4}
    assert unknown == []


def test_classify_include_non_empty_deletes_non_empty_too():
    spaces = [
        _space(2, "张三的知识库", 7),
        _space(3, "个人知识库1", 7),
        _space(4, "GR000113", 7),
    ]
    file_counts = {3: 0, 4: 5}
    user_name_by_id = {7: "张三"}

    keep, to_delete, skipped, unknown = mod._classify(
        spaces, file_counts, user_name_by_id, include_non_empty=True
    )

    assert {r.id for r in keep} == {2}
    assert {r.id for r in to_delete} == {3, 4}
    assert skipped == []


def test_classify_unknown_owner_is_never_deleted():
    spaces = [_space(9, "谁的库", 999)]  # owner 999 not in user map
    keep, to_delete, skipped, unknown = mod._classify(
        spaces, {9: 0}, {}, include_non_empty=True
    )
    assert to_delete == []
    assert {r.id for r in unknown} == {9}


def test_classify_default_name_requires_exact_owner_match():
    # A space named after ANOTHER user's pattern is NOT that user's default.
    spaces = [_space(5, "李四的知识库", 7)]  # owner is 张三, name references 李四
    keep, to_delete, skipped, unknown = mod._classify(
        spaces, {5: 0}, {7: "张三"}, include_non_empty=False
    )
    assert keep == []
    assert {r.id for r in to_delete} == {5}
