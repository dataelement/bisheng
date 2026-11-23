"""Hash-checked reference leaves for an already completed SQL/permission stage.

Only the explicit registration application uses this reader. It does not claim
that skipped permission/member/FGA leaves have been reverified.
"""

from bisheng.knowledge.application.unification_inventory import FrozenInventoryPage
from bisheng.knowledge.application.unification_inventory_codec import decode_inventory_page
from bisheng.knowledge.application.unification_reference_plan import UnificationReferencePlanReader
from bisheng.knowledge.application.unification_reference_state import blocked, validate_inventory_fact
from bisheng.knowledge.application.unification_source_codec import decode_source_page
from bisheng.knowledge.domain.services.unification_fingerprints import digest


class CompletedReferenceInventory:
    def __init__(self, store):
        self.store = store

    async def aiter_frozen_pages(self, frozen, *, environment, backup_ref, schema_ref, current=None):
        current = current or (lambda: None)
        shared = None
        for kind, descriptor in (("baseline", frozen.baseline_ref), ("plan", frozen.plan_ref)):
            seen, indices = set(), {}

            async def visit(
                ref,
                *,
                section="manifest",
                scope="global",
                tenant_id=None,
                page_index=0,
                depth=0,
                record_count=None,
                kind=kind,
                seen=seen,
                indices=indices,
            ):
                nonlocal shared
                current()
                if depth > 64 or ref["object_key"] in seen:
                    blocked("registration_manifest_graph")
                seen.add(ref["object_key"])
                if scope == "tenant" and tenant_id not in frozen.tenant_ids:
                    blocked("registration_manifest_tenant")
                selected = (kind == "baseline" and section == "sources") or (kind == "plan" and section == "conversion")
                if section != "manifest" and not selected:
                    return
                content = await self.store.aload_canonical(
                    ref, run_id=frozen.run_id, kind="sources" if section == "sources" else kind
                )
                if section == "sources":
                    page = decode_source_page(content, run_id=frozen.run_id, tenant_id=tenant_id, page_index=page_index)
                    for row in page.records:
                        validate_inventory_fact(row)
                else:
                    page = decode_inventory_page(
                        content,
                        run_id=frozen.run_id,
                        section=section,
                        scope=scope,
                        tenant_id=tenant_id,
                        page_index=page_index,
                        kind=kind,
                    )
                if record_count is not None and len(page.records) != record_count:
                    blocked("registration_manifest_count")
                if section != "manifest":
                    key = (section, tenant_id)
                    if page_index != indices.get(key, 0):
                        blocked("registration_manifest_order")
                    indices[key] = page_index + 1
                    yield FrozenInventoryPage(
                        kind, section, scope, tenant_id, page_index, len(page.records), ref, content
                    )
                    return
                metadata = [r.data for r in page.records if r.record_type == "run"]
                if depth == 0:
                    if len(metadata) != 1:
                        blocked("registration_manifest_metadata")
                    value = metadata[0]
                    expected = {
                        "writer_contract_version": frozen.writer_contract_version,
                        "environment": environment,
                        "tenant_count": len(frozen.tenant_ids),
                        "tenant_inventory_digest": digest(frozen.tenant_ids),
                        "baseline_ref": None if kind == "baseline" else frozen.baseline_ref,
                    }
                    if any(value.get(k) != v for k, v in expected.items()):
                        blocked("registration_manifest_identity")
                    if any(
                        v is not None and value.get(k) != v
                        for k, v in (("backup_ref", backup_ref), ("schema_ref", schema_ref))
                    ):
                        blocked("registration_manifest_assertion")
                    common = {
                        k: value.get(k)
                        for k in (
                            "backup_ref",
                            "schema_ref",
                            "preparation_policy_version",
                            "physical_inventory_policy",
                            "external_material_policy",
                        )
                    }
                    if shared is not None and common != shared:
                        blocked("registration_manifest_policy")
                    shared = common
                elif metadata:
                    blocked("registration_nested_metadata")
                for row in page.records:
                    if row.record_type == "run":
                        continue
                    if row.record_type != "manifest_entry":
                        blocked("registration_manifest_entry")
                    entry = row.data
                    async for leaf in visit(
                        entry["descriptor"],
                        section=entry["section"],
                        scope=entry["scope"],
                        tenant_id=entry["tenant_id"],
                        page_index=entry["page_index"],
                        depth=depth + 1,
                        record_count=entry["record_count"],
                    ):
                        yield leaf

            async for leaf in visit(descriptor):
                yield leaf


def registration_reader(store):
    return UnificationReferencePlanReader(inventory=CompletedReferenceInventory(store), artifact_store=store)
