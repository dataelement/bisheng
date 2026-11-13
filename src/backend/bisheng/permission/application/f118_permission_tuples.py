"""Complete finite Store transformation; values here never authorize writes."""

from dataclasses import dataclass, field, replace

from bisheng.common.errcode.permission import PermissionMigrationBlockedError
from bisheng.permission.application.relation_api import PermissionObject, PermissionRelation, PermissionSubject
from bisheng.permission.application.sql_runtime import stable_grant_key
from bisheng.permission.domain.services.grant_source_service import GrantSourceService
from bisheng.permission.domain.services.resource_lifecycle_policy import compile_existing_mode_tuples
from bisheng.permission.domain.services.visibility_projection_service import VisibilityProjectionCompiler
from bisheng.permission.migration.f118_plan import ResourceRetirementPlan


def blocked(reason):
    raise PermissionMigrationBlockedError(reason="f118_permission_tuple_" + reason)


def permits(schema, key):
    user, relation, obj = key
    kind = obj.partition(":")[0]
    definitions = {value["type"]: value for value in schema["type_definitions"]}
    value = definitions.get(kind)
    if value is None or relation not in value.get("relations", {}):
        return False
    subject, _, userset = user.partition("#")
    subject_type, _, ident = subject.partition(":")
    allowed = value.get("metadata", {}).get("relations", {}).get(relation, {}).get("directly_related_user_types", ())
    return any(
        row.get("type") == subject_type and row.get("relation", "") == userset and ("wildcard" in row) == (ident == "*")
        for row in allowed
    )


def typed_relation(key):
    user, relation, obj = key
    subject, _, userset = user.partition("#")
    subject_type, _, subject_id = subject.partition(":")
    object_type, _, object_id = obj.partition(":")
    value = PermissionRelation(
        PermissionSubject(subject_type, subject_id, userset or None), relation, PermissionObject(object_type, object_id)
    )
    return value.subject._backend_key(), value.relation, value.resource._backend_key()


@dataclass(frozen=True, slots=True)
class PermissionTuplePlan:
    before: frozenset = field(repr=False)
    staged: frozenset = field(repr=False)
    after: frozenset = field(repr=False)
    writes: tuple = field(repr=False)
    deletes: tuple = field(repr=False)


class F118PermissionTupleBuilder:
    def __init__(self, *, catalog_plan, before_tuples, source_schema, target_schema, legacy_policy=False):
        self.catalog, self.source, self.target = catalog_plan, source_schema, target_schema
        self.before_order = tuple(before_tuples)
        self.before = frozenset(self.before_order)
        if len(self.before) != len(before_tuples):
            blocked("duplicate_original_tuple")
        self.resources, self.grants, self.moves = set(), set(), {}
        self.expected_before, self.expected_after = set(), set()
        self.after_order = {}
        self.legacy_policy = legacy_policy

    def _add(self, output, keys):
        for key in keys:
            output.add(key)
            if output is self.expected_after:
                self.after_order.setdefault(key, None)

    def observe(self, plan, *, restore_missing_markers=True):
        if type(plan) is not ResourceRetirementPlan or plan.catalog_plan is not self.catalog or plan.after is None:
            blocked("complete_shared_plan_required")
        old, new = plan.before, plan.after
        old_object, new_object = f"{old.resource_type}:{old.resource_id}", f"{new.resource_type}:{new.resource_id}"
        if old_object in self.resources:
            blocked("duplicate_resource_object")
        self.resources.add(old_object)
        if old_object != new_object:
            self.moves[old_object] = new_object
        for actual, schema, output in (
            (old, self.source, self.expected_before),
            (new, self.target, self.expected_after),
        ):
            keys = [delta.key for delta in compile_existing_mode_tuples(actual.mode)]
            self._add(
                output,
                (
                    key
                    for key in keys
                    if permits(schema, key)
                    and (
                        (output is self.expected_after and not self.legacy_policy and restore_missing_markers)
                        or key[1] not in {"permission_enabled", "custom_mode", "inherit_mode"}
                        or (key[0], key[1], old_object) in self.before
                    )
                ),
            )
        for actual, output in ((old, self.expected_before), (new, self.expected_after)):
            grants = []
            for grant in plan.after_grants:
                ident = stable_grant_key(
                    tenant_id=actual.tenant_id,
                    resource_type=actual.resource_type,
                    resource_id=actual.resource_id,
                    model_key=grant.model.model_key,
                )
                grants.append(replace(grant, grant_id=ident, resource_type=actual.resource_type))
            self._add(output, (delta.key for delta in GrantSourceService().compile_existing_tuples(tuple(grants))))
            self._add(
                output,
                (
                    (row.source.projected_subject, "visible", f"{actual.resource_type}:{actual.resource_id}")
                    for row in actual.visible_sources
                    if row.source.state == "ACTIVE"
                ),
            )
        for grant in old.grants:
            old_key = "permission_grant:" + stable_grant_key(
                tenant_id=old.tenant_id,
                resource_type=old.resource_type,
                resource_id=old.resource_id,
                model_key=grant.model_key,
            )
            new_key = "permission_grant:" + stable_grant_key(
                tenant_id=new.tenant_id,
                resource_type=new.resource_type,
                resource_id=new.resource_id,
                model_key=grant.model_key,
            )
            self.grants.add(old_key)
            if old_key != new_key:
                self.moves[old_key] = new_key
        result = VisibilityProjectionCompiler().compile(
            tenant_id=new.tenant_id,
            grants=plan.after_grants,
            existing_sources=tuple(row.source for row in new.visible_sources),
        )
        if result.deltas or result.retired_sources:
            blocked("visible_source_drift")

    def _extra(self, key):
        user, relation, obj = key
        kind = obj.partition(":")[0]
        # Existing facts only. These are the actual old compiler forms, not
        # permission to invoke a business sharing/system creation operation.
        if relation == "shared_with":
            from bisheng.tenant.domain.services.resource_share_service import LEGACY_SHAREABLE_TYPES

            return (
                kind in LEGACY_SHAREABLE_TYPES
                and user.startswith("tenant:")
                and user.partition(":")[2].isascii()
                and user.partition(":")[2].isdigit()
            )
        if relation == "public_reader":
            return kind == "knowledge_space" and user == "user:*"
        if relation in {"visible", "system_download_marker", "system_use_marker"}:
            return user == "user:*" and kind in {"knowledge_library", "workflow", "assistant", "tool", "linsight_skill"}
        return False

    def finish(self, *, stage_tuples, before_release_key, after_release_key):
        # A duplicated parent can already name the destination while its exact
        # old parent remains present and both are backed by the signed SQL plan.
        # It adds nothing to the intended after graph. All other dormant
        # destination edges remain unsigned, even when schema-legal.
        destinations = set(self.moves.values())
        destination_edges = {
            key for key in self.before if key[0].partition("#")[0] in destinations or key[2] in destinations
        }
        duplicate_parents = set()
        for key in destination_edges:
            user, relation, obj = key
            if (
                relation != "parent"
                or not user.startswith("knowledge_space:")
                or "#" in user
                or obj.partition(":")[0] not in {"folder", "knowledge_file"}
                or obj not in self.resources
                or obj in destinations
            ):
                continue
            previous_user = "knowledge_library:" + user.partition(":")[2]
            previous = (previous_user, relation, obj)
            if (
                self.moves.get(previous_user) == user
                and previous in self.before
                and previous in self.expected_before
                and key in self.expected_after
                and permits(self.source, key)
                and permits(self.target, key)
            ):
                duplicate_parents.add(key)
        if destination_edges - duplicate_parents:
            blocked("unowned_destination_endpoint")
        controlled = {"permission_enabled", "custom_mode", "inherit_mode", "parent", "grant", "visible"}
        owned = {
            key
            for key in self.before
            if (key[2] in self.resources and key[1] in controlled)
            or (key[2] in self.grants and key[1] in {"model", "ordinary_assignee", "protected_assignee"})
        }
        extras = owned - self.expected_before - duplicate_parents
        retained_extras = set()
        invalid_extras = set()
        for key in extras:
            if self._extra(key) and permits(self.source, key):
                continue
            if not self.legacy_policy:
                # SQL mode owns the sole structural parent/mode. An extra
                # parent is removable only when its canonical original edge
                # is present; never infer a missing parent or a new Grant.
                if (
                    key[2] in self.resources
                    and key[1] in {"parent", "custom_mode", "inherit_mode"}
                    and any(
                        original[2] == key[2]
                        and (
                            original[1] == "parent"
                            if key[1] == "parent"
                            else original[1] in {"custom_mode", "inherit_mode"}
                        )
                        and original in self.before
                        for original in self.expected_before
                    )
                ):
                    invalid_extras.add(key)
                    continue
                blocked("unclassified_existing_graph")
            # Historical SQL/FGA differences on nodes whose identity does not
            # change remain exact original facts. This is preservation, never
            # a source for new assignments or destination-node adoption.
            endpoints = {key[0].partition("#")[0], key[2]}
            if (
                not endpoints.intersection(self.moves)
                and not endpoints.intersection(destinations)
                and permits(self.source, key)
                and permits(self.target, key)
                and typed_relation(key) == key
            ):
                retained_extras.add(key)
            else:
                blocked("existing_graph_drift")
        if self.expected_before - owned:
            blocked("missing_existing_graph")
        result = dict.fromkeys(key for key in self.before_order if key not in owned or key in retained_extras)
        for key in self.after_order:
            if not permits(self.target, key):
                blocked("target_schema_mismatch")
            result[key] = None
        for key in self.before_order:
            if key not in extras or key in retained_extras or key in invalid_extras:
                continue
            changed = (self.moves.get(key[0], key[0]), key[1], self.moves.get(key[2], key[2]))
            if typed_relation(changed) != changed or not permits(self.target, changed):
                blocked("target_context_mismatch")
            result[changed] = None
        for key in tuple(result):
            if key in self.before and (key[0].partition("#")[0] in self.moves or key[2] in self.moves):
                if not self._extra(key) or not permits(self.source, key):
                    blocked("unknown_namespace_edge")
                changed = (self.moves.get(key[0], key[0]), key[1], self.moves.get(key[2], key[2]))
                if typed_relation(changed) != changed or not permits(self.target, changed):
                    blocked("target_context_mismatch")
                del result[key]
                result[changed] = None
        for key in stage_tuples:
            if not permits(self.target, key):
                blocked("target_catalog_schema_mismatch")
            result[key] = None
        staged = frozenset(result)
        from bisheng.core.openfga.authorization_model_f048 import TECHNICAL_MARKER_SUBJECTS

        previous = {
            (subject, "active", "permission_catalog_release:" + before_release_key)
            for subject in TECHNICAL_MARKER_SUBJECTS
        }
        actual_active = {
            key for key in self.before if key[1] == "active" and key[2].startswith("permission_catalog_release:")
        }
        if actual_active != previous:
            blocked("original_active_pointer")
        following = {
            (subject, "active", "permission_catalog_release:" + after_release_key)
            for subject in TECHNICAL_MARKER_SUBJECTS
        }
        if any(not permits(self.source, key) for key in self.before - staged):
            blocked("delete_source_schema_mismatch")
        # Frozen fact/compiler order is deterministic across fresh processes;
        # neither live Read order nor hash-set iteration selects the sequence.
        return PermissionTuplePlan(
            self.before,
            staged,
            frozenset((set(staged) - previous) | following),
            tuple(key for key in result if key not in self.before),
            tuple(key for key in self.before_order if key not in staged),
        )
