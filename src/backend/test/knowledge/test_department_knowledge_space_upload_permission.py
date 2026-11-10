"""A real child-space upload keeps upload_file admission and creates no old approval."""

from unittest.mock import AsyncMock, Mock

from sqlmodel import select

from bisheng.knowledge.domain.models.knowledge import AuthTypeEnum, Knowledge
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from test.knowledge_unification import test_kn_upload as native

store, tenant, business, admission = native.store, native.tenant, native.business, native.admission
processing, application, files, legacy, upload = (
    native.processing,
    native.application,
    native.files,
    native.legacy,
    native.upload,
)


async def test_department_space_upload_does_not_create_approval_request(upload, monkeypatch):
    from bisheng.approval.domain.services.approval_service import ApprovalService

    assert upload.context.user.tenant_id == 101
    async with upload.context.sessions() as session:
        root = await session.get(Knowledge, 40)
        root.auth_type = AuthTypeEnum.PUBLIC
        await session.commit()
    create = AsyncMock()
    monkeypatch.setattr(ApprovalService, "create_department_space_upload_request", create)
    prepare = Mock(wraps=upload.legacy.cls.prepare_one_file)
    monkeypatch.setattr(upload.legacy.cls, "prepare_one_file", prepare)
    result = await upload.service.add_file(40, ["opaque-document"])
    assert len(result) == 1 and result[0].tenant_id == 101 and result[0].knowledge_id == 40
    prepare.assert_called_once()
    create.assert_not_called()
    upload.service._require_action.assert_awaited()
    assert all(
        call.args == ("knowledge_space", 40, "upload_file") for call in upload.service._require_action.await_args_list
    )
    async with upload.context.sessions() as session:
        version = (
            await session.exec(
                select(KnowledgeDocumentVersion).where(KnowledgeDocumentVersion.knowledge_file_id == result[0].id)
            )
        ).one()
        document = await session.get(KnowledgeDocument, version.document_id)
        assert version.version_no == 1 and version.is_primary and document.primary_version_id == version.id
        assert document.knowledge_id == 40
    upload.projection._permission.authorize_created.assert_awaited_once()
    upload.publish.assert_called_once()
