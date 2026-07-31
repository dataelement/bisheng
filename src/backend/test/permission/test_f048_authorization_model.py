"""Semantic contract for the F048 OpenFGA authorization model.

覆盖 AC: AC-02, AC-04, AC-07, AC-08, AC-15, AC-19, AC-20, AC-21,
AC-22, AC-26, AC-28, AC-29, AC-33, AC-36, AC-37, AC-38, AC-39,
AC-40, AC-41, AC-45, AC-46, AC-47
"""

from __future__ import annotations

from collections.abc import Iterable

from bisheng.core.openfga.authorization_model_f048 import (
    DEFAULT_ACTION_CODES,
    authorization_model_checksum,
    build_authorization_model_f048,
)

TupleKey = tuple[str, str, str]


class ModelEvaluator:
    """Small schema-1.1 evaluator for the rewrites emitted by the builder."""

    def __init__(self, model: dict, tuples: Iterable[TupleKey]) -> None:
        self._types = {definition["type"]: definition for definition in model["type_definitions"]}
        self._tuples = set(tuples)

    def check(self, user: str, relation: str, object_key: str) -> bool:
        return self._check(user, relation, object_key, frozenset())

    def _check(
        self,
        user: str,
        relation: str,
        object_key: str,
        visited: frozenset[TupleKey],
    ) -> bool:
        key = (user, relation, object_key)
        if key in visited:
            return False
        object_type = object_key.split(":", 1)[0]
        rewrite = self._types[object_type]["relations"][relation]
        return self._eval(
            rewrite,
            user,
            relation,
            object_key,
            visited | {key},
        )

    def _eval(
        self,
        rewrite: dict,
        user: str,
        relation: str,
        object_key: str,
        visited: frozenset[TupleKey],
    ) -> bool:
        if "this" in rewrite:
            return any(
                tuple_relation == relation
                and tuple_object == object_key
                and self._matches_direct_user(
                    user,
                    tuple_user,
                    visited,
                )
                for tuple_user, tuple_relation, tuple_object in self._tuples
            )
        if "computedUserset" in rewrite:
            return self._check(
                user,
                rewrite["computedUserset"]["relation"],
                object_key,
                visited,
            )
        if "tupleToUserset" in rewrite:
            tupleset_relation = rewrite["tupleToUserset"]["tupleset"]["relation"]
            computed_relation = rewrite["tupleToUserset"]["computedUserset"]["relation"]
            return any(
                tuple_relation == tupleset_relation
                and tuple_object == object_key
                and self._check(
                    user,
                    computed_relation,
                    tuple_user.split("#", 1)[0],
                    visited,
                )
                for tuple_user, tuple_relation, tuple_object in self._tuples
            )
        if "union" in rewrite:
            return any(self._eval(child, user, relation, object_key, visited) for child in rewrite["union"]["child"])
        if "intersection" in rewrite:
            return all(
                self._eval(child, user, relation, object_key, visited) for child in rewrite["intersection"]["child"]
            )
        raise AssertionError(f"Unsupported rewrite: {rewrite}")

    def _matches_direct_user(
        self,
        user: str,
        tuple_user: str,
        visited: frozenset[TupleKey],
    ) -> bool:
        if tuple_user == user:
            return True
        if tuple_user.endswith(":*"):
            return user.split(":", 1)[0] == tuple_user[:-2]
        if "#" in tuple_user:
            userset_object, userset_relation = tuple_user.split("#", 1)
            return self._check(
                user,
                userset_relation,
                userset_object,
                visited,
            )
        return False


def _active_model_tuples(
    *,
    model_key: str = "editor",
    actions: tuple[str, ...] = ("edit",),
    grant_levels: tuple[int, ...] = (),
) -> set[TupleKey]:
    release = f"permission_model_release:catalog-1~{model_key}"
    model = f"permission_model:{model_key}"
    tuples: set[TupleKey] = {
        ("user:*", "active", "permission_catalog_release:catalog-1"),
        ("permission_catalog_release:catalog-1", "catalog", release),
        ("user:*", "enabled_marker", release),
        (release, "release", model),
    }
    tuples.update(("user:*", f"{action}_marker", release) for action in actions)
    tuples.update(("user:*", f"grant_level_{level}_marker", release) for level in grant_levels)
    return tuples


def _resource_grant_tuples(
    *,
    resource: str,
    grant: str,
    model_key: str,
    subject: str,
    protected: bool = False,
    custom: bool = True,
) -> set[TupleKey]:
    relation = "protected_assignee" if protected else "ordinary_assignee"
    tuples: set[TupleKey] = {
        (f"permission_model:{model_key}", "model", grant),
        (subject, relation, grant),
        (grant, "grant", resource),
        ("user:*", "permission_enabled", resource),
    }
    if custom:
        tuples.add(("user:*", "custom_mode", resource))
    return tuples


def test_model_shape_actions_and_checksum_are_stable() -> None:
    model = build_authorization_model_f048()
    second = build_authorization_model_f048()
    assert model == second
    assert authorization_model_checksum(model) == authorization_model_checksum(second)
    assert len(authorization_model_checksum(model)) == 64

    types = {definition["type"]: definition for definition in model["type_definitions"]}
    assert {
        "permission_catalog_release",
        "permission_model_release",
        "permission_model",
        "permission_grant",
        "department",
        "user_group",
        "dashboard",
        "knowledge_file",
        "linsight_skill",
    } <= set(types)
    assert "can_preview" not in types["knowledge_file"]["relations"]
    assert {f"can_{action}" for action in DEFAULT_ACTION_CODES} <= set(types["dashboard"]["relations"])


def test_catalog_model_and_permission_enabled_are_all_required() -> None:
    resource = "workflow:w1"
    grant = "permission_grant:g1"
    tuples = _active_model_tuples(actions=("edit",))
    tuples |= _resource_grant_tuples(
        resource=resource,
        grant=grant,
        model_key="editor",
        subject="user:7",
    )
    evaluator = ModelEvaluator(build_authorization_model_f048(), tuples)
    assert evaluator.check("user:7", "can_edit", resource)
    assert evaluator.check("user:7", "visible", resource)

    for required_tuple in (
        ("user:*", "active", "permission_catalog_release:catalog-1"),
        (
            "permission_catalog_release:catalog-1",
            "catalog",
            "permission_model_release:catalog-1~editor",
        ),
        ("user:*", "permission_enabled", resource),
    ):
        without_required = ModelEvaluator(
            build_authorization_model_f048(),
            tuples - {required_tuple},
        )
        assert not without_required.check("user:7", "can_edit", resource)


def test_custom_gate_blocks_ordinary_but_not_protected_assignment() -> None:
    resource = "tool:t1"
    ordinary_grant = "permission_grant:ordinary"
    protected_grant = "permission_grant:protected"
    tuples = _active_model_tuples(actions=("edit",))
    tuples |= _resource_grant_tuples(
        resource=resource,
        grant=ordinary_grant,
        model_key="editor",
        subject="user:7",
        custom=False,
    )
    tuples |= _resource_grant_tuples(
        resource=resource,
        grant=protected_grant,
        model_key="editor",
        subject="user:8",
        protected=True,
        custom=False,
    )
    evaluator = ModelEvaluator(build_authorization_model_f048(), tuples)
    assert not evaluator.check("user:7", "can_edit", resource)
    assert evaluator.check("user:8", "can_edit", resource)


def test_inherit_uses_only_canonical_parent_and_system_visibility_ignores_mode() -> None:
    parent = "knowledge_space:s1"
    child = "knowledge_file:f1"
    grant = "permission_grant:g1"
    tuples = _active_model_tuples(actions=("download",))
    tuples |= _resource_grant_tuples(
        resource=parent,
        grant=grant,
        model_key="editor",
        subject="user:7",
    )
    tuples |= {
        (parent, "parent", child),
        ("user:*", "inherit_mode", child),
        ("user:*", "permission_enabled", child),
    }
    evaluator = ModelEvaluator(build_authorization_model_f048(), tuples)
    assert evaluator.check("user:7", "can_download", child)

    custom_child = ModelEvaluator(
        build_authorization_model_f048(),
        tuples - {("user:*", "inherit_mode", child)} | {("user:*", "custom_mode", child)},
    )
    assert not custom_child.check("user:7", "can_download", child)

    system_custom_child = ModelEvaluator(
        build_authorization_model_f048(),
        tuples - {("user:*", "inherit_mode", child)}
        | {
            ("user:*", "custom_mode", child),
            ("user:*", "public_reader", parent),
        },
    )
    assert system_custom_child.check("user:99", "visible", child)
    assert system_custom_child.check("user:99", "can_download", child)


def test_department_subtree_and_user_group_usersets_are_not_expanded() -> None:
    resource = "channel:c1"
    grant = "permission_grant:g1"
    tuples = _active_model_tuples(actions=("edit",))
    tuples |= _resource_grant_tuples(
        resource=resource,
        grant=grant,
        model_key="editor",
        subject="department:root#subtree_member",
    )
    tuples |= {
        ("department:child", "child", "department:root"),
        ("user:7", "member", "department:child"),
        ("user:8", "member", "user_group:team"),
        ("user_group:team#member", "ordinary_assignee", grant),
    }
    evaluator = ModelEvaluator(build_authorization_model_f048(), tuples)
    assert evaluator.check("user:7", "can_edit", resource)
    assert evaluator.check("user:8", "can_edit", resource)


def test_grant_level_is_intersected_inside_the_same_grant() -> None:
    resource = "dashboard:d1"
    manager_grant = "permission_grant:manager"
    unrelated_grant = "permission_grant:unrelated"
    tuples = _active_model_tuples(
        model_key="manager",
        actions=("manage_permission", "edit"),
        grant_levels=(1, 2),
    )
    tuples |= _active_model_tuples(
        model_key="viewer",
        actions=(),
        grant_levels=(),
    )
    tuples |= _resource_grant_tuples(
        resource=resource,
        grant=manager_grant,
        model_key="manager",
        subject="user:7",
    )
    tuples |= _resource_grant_tuples(
        resource=resource,
        grant=unrelated_grant,
        model_key="viewer",
        subject="user:8",
    )
    evaluator = ModelEvaluator(build_authorization_model_f048(), tuples)
    assert evaluator.check("user:7", "can_grant_level_2", resource)
    assert not evaluator.check("user:8", "can_grant_level_2", resource)
    assert evaluator.check("user:7", "can_edit", resource)
    assert not evaluator.check("user:7", "can_delete", resource)


def test_shared_system_read_is_resource_specific_and_read_only() -> None:
    model = build_authorization_model_f048()
    base = {
        ("user:7", "member", "tenant:child"),
        ("tenant:child", "shared_with", "knowledge_library:k1"),
        ("user:*", "permission_enabled", "knowledge_library:k1"),
        ("tenant:child", "shared_with", "knowledge_file:f1"),
        ("user:*", "permission_enabled", "knowledge_file:f1"),
    }
    evaluator = ModelEvaluator(model, base)
    assert evaluator.check("user:7", "visible", "knowledge_library:k1")
    assert evaluator.check("user:7", "can_use", "knowledge_library:k1")
    assert not evaluator.check("user:7", "can_edit", "knowledge_library:k1")
    assert evaluator.check("user:7", "can_download", "knowledge_file:f1")
    assert not evaluator.check("user:7", "can_use", "knowledge_file:f1")
