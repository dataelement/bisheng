"""Initial uploads create a real atomic File/Doc/V1 before external dispatch."""

from sqlmodel import select

from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from test.knowledge_unification import test_kn_upload as native

store, tenant, business, admission = native.store, native.tenant, native.business, native.admission
processing, application, files, legacy, upload = (
    native.processing,
    native.application,
    native.files,
    native.legacy,
    native.upload,
)


async def test_add_file_creates_document_and_v1(upload):
    context = upload.context
    async with context.sessions() as session:
        before = set((await session.exec(select(KnowledgeDocument.id))).all())

    def dispatch_after_committed_v1(**request):
        with context.sync.connect() as connection:
            versions = (
                connection.execute(
                    select(KnowledgeDocumentVersion.__table__).where(
                        KnowledgeDocumentVersion.knowledge_file_id == request["file_id"]
                    )
                )
                .mappings()
                .all()
            )
            assert len(versions) == 1 and versions[0]["is_primary"]
            document = (
                connection.execute(
                    select(KnowledgeDocument.__table__).where(KnowledgeDocument.id == versions[0]["document_id"])
                )
                .mappings()
                .one()
            )
            assert document["primary_version_id"] == versions[0]["id"]

    upload.publish.side_effect = dispatch_after_committed_v1
    result = await upload.service.add_file(40, ["opaque-document"])
    assert len(result) == 1 and result[0].tenant_id == 101 and result[0].knowledge_id == 40
    file_id = result[0].id
    assert type(file_id) is int and file_id > 0
    async with context.sessions() as session:
        docs = (await session.exec(select(KnowledgeDocument))).all()
        created = [row for row in docs if row.id not in before]
        assert len(created) == 1
        doc = created[0]
        assert doc.knowledge_id == 40
        versions = (
            await session.exec(select(KnowledgeDocumentVersion).where(KnowledgeDocumentVersion.document_id == doc.id))
        ).all()
        assert len(versions) == 1
        version = versions[0]
        assert (version.knowledge_file_id, version.version_no, version.is_primary) == (file_id, 1, True)
        assert doc.primary_version_id == version.id
        assert (await session.get(KnowledgeFile, file_id)).user_id == 7
        assert (await session.get(KnowledgeDocument, 80)).primary_version_id == 181
    upload.projection._permission.authorize_created.assert_awaited_once()
    upload.service._require_action.assert_awaited()
    assert all(
        call.args == ("knowledge_space", 40, "upload_file") for call in upload.service._require_action.await_args_list
    )
    upload.publish.assert_called_once()
