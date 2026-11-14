"""Public model prechecks and source pages use the same real reference Core."""

from bisheng.llm.application.model_delete_plan import ModelDeletePlanApplication, _Scope
from bisheng.llm.application.model_deletion_context import ModelDeleteCommand, changed, model_deletion_request


class ModelReferenceApplication:
    def __init__(self, application):
        self.application = application
        self.references, self.plans = application.references, application.plans
        self.prechecks = ModelDeletePlanApplication(references=self.references, plans=self.plans)

    async def _read(self, identity, method, **kwargs):
        async with model_deletion_request(identity, references=self.references, plans=self.plans) as request:
            async with self.application.session_factory() as session:
                if session.in_transaction():
                    changed()
                async with session.begin():
                    scope = _Scope(session)
                    result = await request.call(scope.call, method, session, identity=identity, **kwargs)
                    scope.check()
                    request.check()
                    if session.new or session.dirty or session.deleted:
                        changed()
            request.check()
            return result

    async def aplan_removed_update(self, *, identity, server):
        command = ModelDeleteCommand.create(server=server)
        return await self._read(identity, self.prechecks.aplan_removed_update, server=command.server)

    async def aplan_server_delete(self, *, identity, server_id):
        command = ModelDeleteCommand.create(server_id=server_id)
        return await self._read(identity, self.prechecks.aplan_server_delete, server_id=command.server_id)

    async def alist_sources(self, *, identity, query):
        arguments = {
            "server_id": query.server_id,
            "retained_model_ids": tuple(query.retained_model_ids),
            "delete_server": query.delete_server,
        }
        if query.cursor is None:
            inspection = await self._read(
                identity, self.references.ainspect_removed_models, **arguments, source_page_size=query.page_size
            )
            return inspection.source_page
        return await self._read(
            identity,
            self.references.alist_removed_model_sources,
            **arguments,
            cursor=query.cursor,
            page_size=query.page_size,
        )


async def get_model_reference_application():
    from bisheng.llm.application.model_deletion import get_model_deletion_application

    return ModelReferenceApplication(await get_model_deletion_application())
