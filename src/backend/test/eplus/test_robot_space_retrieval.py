from __future__ import annotations

from langchain_core.documents import Document

from bisheng.assistant.domain.schemas.execution import AssistantRobotScope
from bisheng.eplus.domain.services.robot_space_retrieval import RobotSpaceRetrievalPolicy


class FakeDocumentStateReader:
    def __init__(self, valid_ids: set[int]) -> None:
        self.valid_ids = valid_ids
        self.calls: list[tuple[int, tuple[int, ...], set[int]]] = []

    async def valid_file_ids(
        self,
        *,
        tenant_id: int,
        space_ids: tuple[int, ...],
        file_ids: set[int],
    ) -> set[int]:
        self.calls.append((tenant_id, space_ids, file_ids))
        return file_ids & self.valid_ids


class FakeRetrievalBackend:
    def __init__(self, docs_by_space: dict[int, list[Document]], on_retrieve=None) -> None:
        self.docs_by_space = docs_by_space
        self.on_retrieve = on_retrieve
        self.calls: list[int] = []

    async def retrieve_space(self, *, space_id: int, query: str, invoke_user_id: int, **kwargs) -> list[Document]:
        self.calls.append(space_id)
        if self.on_retrieve:
            self.on_retrieve()
        return self.docs_by_space.get(space_id, [])


def _doc(file_id: int, space_id: int, chunk: int = 0, text: str | None = None) -> Document:
    return Document(
        page_content=text or f"file-{file_id}-chunk-{chunk}",
        metadata={"document_id": file_id, "knowledge_id": space_id, "chunk_index": chunk},
    )


def _policy(
    *,
    spaces: tuple[int, ...],
    docs_by_space: dict[int, list[Document]],
    valid_ids: set[int],
    version: int = 7,
    on_retrieve=None,
):
    backend = FakeRetrievalBackend(docs_by_space, on_retrieve=on_retrieve)
    files = FakeDocumentStateReader(valid_ids)
    policy = RobotSpaceRetrievalPolicy(
        tenant_id=9,
        bot_config_id=3,
        invoke_user_id=88,
        document_state_reader=files,
        retrieval_backend=backend,
    )
    scope = AssistantRobotScope(bot_config_id=3, space_ids=spaces, scope_version=version)
    return policy, scope, backend, files


async def test_zero_binding_returns_empty_without_touching_retrieval_backend():
    policy, scope, backend, files = _policy(spaces=(), docs_by_space={}, valid_ids=set())

    assert await policy.retrieve("anything", expected_scope=scope) == []
    assert backend.calls == []
    assert files.calls == []


async def test_bound_spaces_are_queried_once_and_results_are_deduplicated():
    duplicate = _doc(100, 11, text="same chunk")
    policy, scope, backend, _ = _policy(
        spaces=(11, 12),
        docs_by_space={
            11: [duplicate, _doc(101, 11)],
            12: [_doc(100, 11, text="same chunk"), _doc(102, 12)],
            99: [_doc(999, 99)],  # a space the user may personally access must not expand robot scope
        },
        valid_ids={100, 101, 102, 999},
    )

    result = await policy.retrieve("question", expected_scope=scope)

    assert backend.calls == [11, 12]
    assert [doc.metadata["document_id"] for doc in result] == [100, 101, 102]
    assert all(doc.metadata["access_scope"] == "robot_bound" for doc in result)


async def test_result_postfilter_drops_deleted_failed_or_moved_files_without_personal_acl():
    policy, scope, _, files = _policy(
        spaces=(11,),
        docs_by_space={11: [_doc(100, 11), _doc(101, 11), _doc(102, 11)]},
        # The production reader defines validity solely by tenant, current bound
        # space, file row and SUCCESS status. It deliberately has no user ACL.
        valid_ids={100},
    )

    result = await policy.retrieve("question", expected_scope=scope)

    assert [doc.metadata["document_id"] for doc in result] == [100]
    assert files.calls == [(9, (11,), {100, 101, 102})]


async def test_scope_change_during_retrieval_keeps_the_turn_snapshot():
    policy, scope, backend, _ = _policy(
        spaces=(11,),
        docs_by_space={11: [_doc(100, 11)]},
        valid_ids={100},
    )

    def mutate_scope() -> None:
        # Represents an administrator changing the persisted binding while
        # this turn is already retrieving. The turn snapshot remains fixed.
        return None

    policy.retrieval_backend.on_retrieve = mutate_scope

    result = await policy.retrieve("question", expected_scope=scope)

    assert [doc.metadata["document_id"] for doc in result] == [100]
    assert backend.calls == [11]
