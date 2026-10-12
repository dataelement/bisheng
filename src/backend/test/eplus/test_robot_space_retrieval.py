from __future__ import annotations

from types import SimpleNamespace

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

    async def file_sources(self, *, tenant_id, space_ids, file_ids=None, file_name=None):
        self.calls.append((tenant_id, space_ids, file_ids))
        ids = self.valid_ids if file_ids is None else file_ids & self.valid_ids
        return {
            file_id: SimpleNamespace(
                file_id=file_id,
                file_name=f"file-{file_id}.pdf",
                space_id=11 if file_id < 102 else 12,
                space_name="真实空间" if file_id < 102 else "另一空间",
            )
            for file_id in ids
            if (11 if file_id < 102 else 12) in space_ids and (file_name is None or file_name == f"file-{file_id}.pdf")
        }

    async def search_file_sources(self, *, tenant_id, space_ids, keywords, limit=50):
        sources = await self.file_sources(tenant_id=tenant_id, space_ids=space_ids)
        return {fid: source for fid, source in sources.items() if all(t in source.file_name for t in keywords)}


class FakeRetrievalBackend:
    def __init__(self, docs_by_space: dict[int, list[Document]], on_retrieve=None) -> None:
        self.docs_by_space = docs_by_space
        self.on_retrieve = on_retrieve
        self.calls: list[int] = []
        self.file_filters: dict[int, tuple[int, ...] | None] = {}
        self.requests: list[tuple[int, tuple[int, ...] | None]] = []
        self.supplement_docs_by_space: dict[int, list[Document]] = {}

    async def retrieve_space(self, *, space_id: int, query: str, invoke_user_id: int, **kwargs) -> list[Document]:
        self.calls.append(space_id)
        self.file_filters[space_id] = kwargs.get("file_ids")
        self.requests.append((space_id, kwargs.get("file_ids")))
        if self.on_retrieve:
            self.on_retrieve()
        if kwargs.get("file_ids") is not None and space_id in self.supplement_docs_by_space:
            return self.supplement_docs_by_space[space_id]
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
    assert backend.file_filters == {11: None}


async def test_current_database_source_replaces_stale_index_names_and_space():
    stale = _doc(100, 999)
    stale.metadata["document_name"] = "旧文件名.pdf"
    policy, scope, _, _ = _policy(spaces=(11,), docs_by_space={11: [stale]}, valid_ids={100})

    result = await policy.retrieve("归属", expected_scope=scope)

    assert result[0].metadata["knowledge_id"] == 11
    assert result[0].metadata["knowledge_name"] == "真实空间"
    assert result[0].metadata["document_name"] == "file-100.pdf"
    assert stale.metadata["knowledge_id"] == 999


async def test_explicit_file_search_excludes_unrelated_content_even_when_it_mentions_the_file():
    policy, scope, backend, _ = _policy(
        spaces=(11, 12),
        docs_by_space={11: [_doc(101, 11, text="正文提到了 file-100.pdf"), _doc(100, 11)], 12: [_doc(102, 12)]},
        valid_ids={100, 101, 102},
    )

    result = await policy.retrieve("查询 file-100.pdf", file_name="file-100.pdf", expected_scope=scope)

    assert [d.metadata["document_id"] for d in result] == [100]
    assert backend.calls == [11]
    assert backend.file_filters == {11: (100,)}


async def test_explicit_missing_file_does_not_fall_back_to_other_documents():
    policy, scope, backend, _ = _policy(spaces=(11,), docs_by_space={11: [_doc(100, 11)]}, valid_ids={100})

    assert await policy.retrieve("不存在.pdf", file_name="不存在.pdf", expected_scope=scope) == []
    assert backend.calls == []


async def test_exact_source_is_available_without_vector_hits_but_not_invented_content():
    policy, scope, _, _ = _policy(spaces=(11,), docs_by_space={}, valid_ids={100})

    result = await policy.retrieve("归属", file_name="file-100.pdf", expected_scope=scope)

    assert len(result) == 1
    assert result[0].metadata["document_id"] == 100
    assert result[0].metadata["source_only"] is True
    assert result[0].page_content == ""


async def test_filename_keyword_search_preserves_sources_when_body_is_unavailable():
    policy, scope, backend, _ = _policy(spaces=(11, 12), docs_by_space={}, valid_ids={100, 102})
    result = await policy.retrieve("有哪些文件", file_name_query="file-102", expected_scope=scope)
    assert [(d.metadata["document_id"], d.metadata["knowledge_id"]) for d in result] == [(102, 12)]
    assert all(d.metadata["source_only"] and d.page_content == "" for d in result)
    assert backend.requests == [(11, None), (12, None), (12, (102,))]


async def test_filename_match_does_not_skip_other_spaces_relevant_bodies():
    policy, scope, backend, _ = _policy(
        spaces=(11, 12),
        docs_by_space={
            11: [_doc(100, 11, text="医学研究项目的申请条件")],
            12: [_doc(102, 12, text="指南的医学研究内容")],
        },
        valid_ids={100, 102},
    )
    result = await policy.retrieve("医学研究大概是什么内容", file_name_query="file-102", expected_scope=scope)
    assert {d.metadata["document_id"] for d in result} == {100, 102}
    assert all(d.page_content and not d.metadata.get("source_only") for d in result)
    assert backend.requests == [(11, None), (12, None)]


async def test_missing_filename_body_is_supplemented_without_losing_unrelated_name_content():
    policy, scope, backend, _ = _policy(
        spaces=(11, 12), docs_by_space={11: [_doc(100, 11, text="医学研究的内容")], 12: []}, valid_ids={100, 102}
    )
    backend.supplement_docs_by_space = {12: [_doc(102, 12, text="医学研究申请指南的正文")]}
    result = await policy.retrieve("医学研究大概是什么内容", file_name_query="file-102", expected_scope=scope)
    assert {d.metadata["document_id"] for d in result} == {100, 102}
    assert next(d for d in result if d.metadata["document_id"] == 102).page_content == "医学研究申请指南的正文"
    assert backend.requests == [(11, None), (12, None), (12, (102,))]


async def test_empty_ingestion_wrapper_does_not_prevent_body_supplement():
    policy, scope, backend, _ = _policy(
        spaces=(11,),
        docs_by_space={
            11: [_doc(100, 11, text="{<file_title>file-100.pdf</file_title><paragraph_content></paragraph_content>}")]
        },
        valid_ids={100},
    )
    backend.supplement_docs_by_space = {11: [_doc(100, 11, text="医学研究正文")]}
    result = await policy.retrieve("医学研究", file_name_query="file-100", expected_scope=scope)
    assert [d.page_content for d in result] == ["医学研究正文"]
    assert backend.requests == [(11, None), (11, (100,))]


async def test_supplement_is_postfiltered_and_cannot_add_wrong_file_or_unbound_space():
    policy, scope, backend, _ = _policy(spaces=(11,), docs_by_space={}, valid_ids={100, 101, 999})
    backend.supplement_docs_by_space = {11: [_doc(100, 11), _doc(101, 11), _doc(999, 99)]}
    result = await policy.retrieve("内容", file_name_query="file-100", expected_scope=scope)
    assert [d.metadata["document_id"] for d in result] == [100]
    assert result[0].page_content
    assert not result[0].metadata.get("source_only")
    assert backend.requests == [(11, None), (11, (100,))]


async def test_missing_filename_bodies_are_batched_per_space_and_keep_sources_after_budget():
    policy, scope, backend, _ = _policy(spaces=(11,), docs_by_space={}, valid_ids={100, 101})
    backend.supplement_docs_by_space = {11: [_doc(100, 11, text="医学研究正文"), _doc(101, 11, text="项目说明")]}
    result = await policy.retrieve("医学研究", file_name_query="file-", expected_scope=scope, max_content=4)
    assert {d.metadata["document_id"] for d in result} == {100, 101}
    assert sum(len(d.page_content) for d in result) == 4
    assert backend.requests == [(11, None), (11, (100, 101))]


async def test_equal_body_with_different_index_wrappers_is_not_returned_twice():
    policy, scope, _, _ = _policy(
        spaces=(11,),
        docs_by_space={
            11: [
                _doc(100, 11, text="医学研究正文"),
                _doc(
                    100, 11, text="{<file_title>旧名字</file_title><paragraph_content>医学研究正文</paragraph_content>}"
                ),
            ]
        },
        valid_ids={100},
    )
    result = await policy.retrieve("医学研究", file_name_query="file-100", expected_scope=scope)
    assert [d.page_content for d in result] == ["医学研究正文"]


async def test_no_filename_match_falls_back_to_content_recall_without_inventing_sources():
    policy, scope, _, _ = _policy(spaces=(11,), docs_by_space={11: [_doc(100, 11)]}, valid_ids={100})
    result = await policy.retrieve("topic", file_name_query="不存在", expected_scope=scope)
    assert [d.metadata["document_id"] for d in result] == [100]
    assert not result[0].metadata.get("source_only")


async def test_later_space_relevant_content_is_ranked_before_budget_cutoff():
    policy, scope, backend, _ = _policy(
        spaces=(12, 11),
        docs_by_space={
            11: [_doc(100, 11, text="发票内容" * 100)],
            12: [_doc(102, 12, text="深圳市医学研究专项资金申请指南")],
        },
        valid_ids={100, 102},
    )
    result = await policy.retrieve("深圳市医学研究", expected_scope=scope, max_content=20)
    assert result[0].metadata["document_id"] == 102
    assert backend.calls == [11, 12]
    assert sum(len(d.page_content) for d in result) <= 20


async def test_content_budget_trims_first_oversized_chunk_instead_of_exceeding_limit():
    policy, scope, _, _ = _policy(
        spaces=(11,), docs_by_space={11: [_doc(100, 11, text="医学研究" * 100)]}, valid_ids={100}
    )
    result = await policy.retrieve("医学研究", expected_scope=scope, max_content=10)
    assert result[0].page_content == "医学研究医学研究医学"
    assert result[0].metadata["content_truncated"] is True


async def test_same_body_from_different_files_keeps_both_provenances():
    policy, scope, _, _ = _policy(
        spaces=(11, 12),
        docs_by_space={11: [_doc(100, 11, text="医学研究")], 12: [_doc(102, 12, text="医学研究")]},
        valid_ids={100, 102},
    )
    result = await policy.retrieve("医学研究", expected_scope=scope)
    assert {d.metadata["document_id"] for d in result} == {100, 102}
