"""Recognize an old ordinary PUT retry without replaying generated model IDs."""

from bisheng.llm.application.model_deletion_context import ModelDeleteCommand
from bisheng.llm.application.model_provider_projection import execution_metadata


async def find_completed_update(application, *, identity, server):
    command = ModelDeleteCommand.create(server=server)
    async with application.session_factory() as session:
        async with session.begin():
            row = await application.providers.afind_completed(
                session,
                server_id=command.server_id,
                operation=command.operation,
                actor_user_id=identity.user_id,
                command_digest=command.command_digest,
            )
            if row is None:
                return None
            application.providers.validate(row)
            metadata = execution_metadata(row)
            if metadata["force"] or not isinstance(metadata["ack"], dict):
                return None
            provider, models = await application.writer.aread_result(session, server_id=command.server_id)
            if application.writer.result_digest(provider, models) != metadata["ack"].get("result_digest"):
                return None
            return row.id, row.plan_digest
