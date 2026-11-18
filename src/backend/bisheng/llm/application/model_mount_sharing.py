"""Resume the actual mount's unfinished model shares, without remounting."""

from bisheng.common.errcode.llm_tenant import LLMModelNotAccessibleError
from bisheng.database.models.tenant import ROOT_TENANT_ID
from bisheng.llm.application.model_deletion_context import model_deletion_request, model_write_phase
from bisheng.llm.application.model_operation_recovery import needs_recovery
from bisheng.llm.application.model_provider_projection import execution_metadata
from bisheng.llm.domain.repositories.model_mount_sharing_repository import ModelMountSharingRepository


class ModelMountSharingApplication:
    def __init__(self, sharing):
        self.sharing, self.repository = sharing, ModelMountSharingRepository()

    async def _facts(self, identity, parameters, *, pending=False):
        app = self.sharing
        async with model_deletion_request(identity, references=app.references, plans=app.plans) as request:
            if request.tenant_id != ROOT_TENANT_ID or not request.actor.super_admin:
                raise LLMModelNotAccessibleError()
            async with model_write_phase(app.session_factory, request) as phase:
                facts, child = await phase.call(self.repository.aread_mount, phase.session, **parameters)
                providers = []
                if pending:
                    rows = await phase.call(self.repository.apending_candidates, phase.session)
                    for row in rows:
                        if row.parameters.get("command_digest") != facts.digest(row.model_server_id):
                            continue
                        if row.model_execution_state == "ABANDONED":
                            # This is a retry receipt, not execution authority.
                            # ashare builds a new plan after rechecking the real
                            # mount and current Root administrator.
                            metadata = row.model_execution_metadata
                            if (
                                isinstance(metadata, dict)
                                and metadata.get("purpose") == "model_share_server"
                                and isinstance(metadata.get("ack"), dict)
                                and metadata["ack"].get("status") == "abandoned_unstarted"
                            ):
                                providers.append(row.model_server_id)
                            continue
                        if (
                            needs_recovery(row, app.plans.clock())
                            and execution_metadata(row)["purpose"] == "model_share_server"
                        ):
                            providers.append(row.model_server_id)
                            continue
                        app.providers.validate(row)
                        if execution_metadata(row)["purpose"] == "model_share_server":
                            providers.append(row.model_server_id)
                return facts, child, tuple(sorted(set(providers)))

    async def aenabled_server_ids(self, *, identity):
        app = self.sharing
        async with model_deletion_request(identity, references=app.references, plans=app.plans) as request:
            if request.tenant_id != ROOT_TENANT_ID or not request.actor.super_admin:
                raise LLMModelNotAccessibleError()
            async with model_write_phase(app.session_factory, request) as phase:
                return await phase.call(app.intents.aenabled_server_ids, phase.session)

    async def areconcile_child(self, *, identity, child_id):
        """A current explicit command repairs differences after mount/enable.

        Failures remain visible as intent/actual coverage gaps; an active frozen
        command is never replaced or expanded by this lifecycle producer.
        """
        from loguru import logger

        failures = []
        for server_id in await self.aenabled_server_ids(identity=identity):
            try:
                await self.sharing.aset_sharing(identity=identity, server_id=server_id, enabled=True, child_id=child_id)
            except Exception as error:
                logger.exception("Provider {} sharing to child {} requires recovery", server_id, child_id)
                failures.append(error)
        if failures:
            raise failures[0]

    async def ashare(self, *, identity, server_id, **parameters):
        facts, _, _ = await self._facts(identity, parameters)
        return await self.sharing._set_sharing(
            identity=identity,
            server_id=server_id,
            enabled=True,
            child_id=facts.child_id,
            command=facts.digest(server_id),
            mounted=facts,
        )

    async def aresume(self, *, identity, **parameters):
        _, child, providers = await self._facts(identity, parameters, pending=True)
        if not providers:
            return None
        for server_id in providers:
            await self.ashare(identity=identity, server_id=server_id, **parameters)
        return child


async def get_model_mount_sharing_application():
    from bisheng.llm.application.model_sharing import get_model_sharing_application

    return ModelMountSharingApplication(await get_model_sharing_application())
