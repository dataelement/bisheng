"""Exact bounded six-source projections for offline F118 maintenance.

The history view owns AFTER overlaying; this adapter reads original database
facts only. It neither creates reference authority nor commits a transaction.
"""

from sqlalchemy import and_, or_, select

from bisheng.knowledge.domain.repositories import unification_inventory_repository as native
from bisheng.resource_reference.application.contracts import SourceKey, SourceRootKey, SourceType


class UnificationReferenceBatchRepository(native.UnificationInventoryRepository):
    async def alock_reference_roots(self, session, *, root_keys):
        tenant = native._scope(session)
        if (
            type(root_keys) is not tuple
            or not 1 <= len(root_keys) <= 200
            or len(set(root_keys)) != len(root_keys)
            or any(type(key) is not SourceRootKey or key.tenant_id != tenant for key in root_keys)
        ):
            native._blocked("source_root_batch_scope")
        models = {
            SourceType.WORKFLOW_VERSION: (native.Flow, native.Flow.id),
            SourceType.HOSTED_APP_VERSION: (native.App, native.App.id),
            SourceType.ASSISTANT: (native.Assistant, native.Assistant.id),
            SourceType.CHANNEL_SYNC: (native.Channel, native.Channel.id),
            SourceType.KNOWLEDGE: (native.Knowledge, native.Knowledge.id),
            SourceType.MODEL_DEFAULT: (native.TenantSystemModelConfig, native.TenantSystemModelConfig.key),
        }
        for key in sorted(root_keys, key=lambda key: (key.source_type.value, key.source_id)):
            model, column = models[key.source_type]
            await self._read(
                session,
                select(model.id)
                .where(column == (int(key.source_id) if key.source_type == SourceType.KNOWLEDGE else key.source_id))
                .with_for_update(),
            )

    async def aload_reference_sources(self, session, *, source_keys, for_update=False):
        tenant = native._scope(session)
        if (
            type(source_keys) is not tuple
            or not 1 <= len(source_keys) <= 200
            or type(for_update) is not bool
            or len(set(source_keys)) != len(source_keys)
            or any(type(key) is not SourceKey or key.tenant_id != tenant for key in source_keys)
        ):
            native._blocked("source_batch_scope")
        grouped = {}
        for key in source_keys:
            if key.source_type == SourceType.MODEL_DEFAULT and key.source_id not in native.MODEL_DEFAULT_SCHEMAS:
                native._blocked("source_unknown_default_key")
            grouped.setdefault(key.source_type, []).append(key)
        if for_update:
            # Hold each business root once before versions, always in the same
            # total order. A bulk ORDER BY does not portably specify lock order.
            await self.alock_reference_roots(
                session,
                root_keys=tuple({SourceRootKey(key.tenant_id, key.source_type, key.source_id) for key in source_keys}),
            )
            for key in sorted(
                source_keys, key=lambda item: (item.source_type.value, item.source_id, item.source_version)
            ):
                if key.source_type == SourceType.WORKFLOW_VERSION:
                    await self._read(
                        session,
                        select(native.FlowVersion.id)
                        .where(
                            native.FlowVersion.id == int(key.source_version),
                            native.FlowVersion.flow_id == key.source_id,
                        )
                        .with_for_update(),
                    )
                elif key.source_type == SourceType.HOSTED_APP_VERSION:
                    await self._read(
                        session,
                        select(native.AppVersion.id)
                        .join(native.App, native.App.id == native.AppVersion.app_id)
                        .where(native.AppVersion.id == key.source_version, native.AppVersion.app_id == key.source_id)
                        .with_for_update(),
                    )

        async def project(model, cls, condition, overrides=None, parent=None):
            statement = select(*native._columns(model, cls, overrides)).where(condition)
            if parent is not None:
                statement = statement.join(*parent)
            if self.fact_view is None:
                observed = await self._read(session, statement)
            else:
                aliases = {
                    name: column
                    for name, column in {
                        "data_json": "data",
                        "model_transition_json": "model_transition",
                        "capabilities_json": "capabilities",
                    }.items()
                    if name in (overrides or {})
                }
                observed = await self.fact_view.exact_source_mappings(
                    session,
                    model=model,
                    statement=statement,
                    tenant=tenant,
                    aliases=aliases,
                )
            values = tuple(native._row(cls, row) for row in observed)
            if any(getattr(row, "tenant_id", tenant) != tenant for row in values):
                native._blocked("source_wrong_tenant")
            return values

        result = {}
        for kind, keys in grouped.items():
            identifiers = tuple(sorted({key.source_id for key in keys}))
            if kind in {SourceType.WORKFLOW_VERSION, SourceType.HOSTED_APP_VERSION}:
                workflow = kind == SourceType.WORKFLOW_VERSION
                root_model, root_cls = (
                    (native.Flow, native.WorkflowRootRow) if workflow else (native.App, native.AppRootRow)
                )
                root_rows = await project(
                    root_model,
                    root_cls,
                    root_model.id.in_(identifiers),
                    {"data_json": native.Flow.data} if workflow else None,
                )
                roots = {row.id: row for row in root_rows}
                if len(roots) != len(root_rows):
                    native._blocked("source_missing_or_duplicated")
                if workflow:
                    versions = await project(
                        native.FlowVersion,
                        native.WorkflowVersionRow,
                        or_(
                            *(
                                and_(
                                    native.FlowVersion.id == int(key.source_version),
                                    native.FlowVersion.flow_id == key.source_id,
                                )
                                for key in keys
                            )
                        ),
                        {"data_json": native.FlowVersion.data},
                    )
                    by_version = {(row.flow_id, str(row.id)): row for row in versions}
                else:
                    versions = await project(
                        native.AppVersion,
                        native.AppVersionRow,
                        or_(
                            *(
                                and_(
                                    native.AppVersion.id == key.source_version,
                                    native.AppVersion.app_id == key.source_id,
                                )
                                for key in keys
                            )
                        ),
                        {"tenant_id": native.App.tenant_id, "capabilities_json": native.AppVersion.capabilities},
                        (native.App, native.App.id == native.AppVersion.app_id),
                    )
                    by_version = {(row.app_id, row.id): row for row in versions}
                if len(by_version) != len(versions):
                    native._blocked("source_missing_or_duplicated")
                for key in keys:
                    if key.source_id not in roots or (key.source_id, key.source_version) not in by_version:
                        native._blocked("source_missing_or_duplicated")
                    result[key] = roots[key.source_id], by_version[key.source_id, key.source_version], ()
            elif kind in {SourceType.ASSISTANT, SourceType.CHANNEL_SYNC}:
                assistant = kind == SourceType.ASSISTANT
                model, cls = (
                    (native.Assistant, native.AssistantRow) if assistant else (native.Channel, native.ChannelRow)
                )
                values = await project(model, cls, model.id.in_(identifiers))
                roots, children = {row.id: row for row in values}, {identifier: [] for identifier in identifiers}
                if len(roots) != len(values):
                    native._blocked("source_missing_or_duplicated")
                method = self.alist_assistant_links if assistant else self.alist_channel_syncs
                argument = "assistant_ids" if assistant else "channel_ids"
                after = None
                while True:
                    page = await method(session, **{argument: identifiers}, after_id=after, limit=200)
                    for child in page.items:
                        parent = child.assistant_id if assistant else child.channel_id
                        if parent not in children:
                            native._blocked("source_unexpected_child")
                        children[parent].append(child)
                    if page.next_after is None:
                        break
                    after = page.next_after
                for key in keys:
                    if key.source_id not in roots or key.source_version != "current":
                        native._blocked("source_missing_or_duplicated")
                    result[key] = roots[key.source_id], None, tuple(children[key.source_id])
            else:
                knowledge = kind == SourceType.KNOWLEDGE
                model, cls = (
                    (native.Knowledge, native.KnowledgeRow)
                    if knowledge
                    else (native.TenantSystemModelConfig, native.DefaultRow)
                )
                values = await project(
                    model,
                    cls,
                    model.id.in_(tuple(int(ident) for ident in identifiers))
                    if knowledge
                    else model.key.in_(identifiers),
                    {"model_transition_json": native.Knowledge.model_transition} if knowledge else None,
                )
                roots = {(str(row.id) if knowledge else row.key): row for row in values}
                if len(roots) != len(values):
                    native._blocked("source_missing_or_duplicated")
                for key in keys:
                    if key.source_id not in roots or key.source_version != "current":
                        native._blocked("source_missing_or_duplicated")
                    result[key] = roots[key.source_id], None, ()
        if set(result) != set(source_keys):
            native._blocked("source_batch_incomplete")
        return result
