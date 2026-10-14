"""Bound real robot policy scheduling with deterministic index gates."""

import asyncio

import pytest

from bisheng.assistant.domain.schemas.execution import AssistantRobotScope
from bisheng.core.context.tenant import get_current_tenant_id, set_current_tenant_id
from bisheng.eplus.domain.schemas.knowledge import RobotFileSource
from bisheng.eplus.domain.services.robot_space_retrieval import RobotSpaceRetrievalPolicy
from test.eplus.test_robot_space_retrieval import _doc


class Sources:
    async def file_sources(self, *, tenant_id, space_ids, file_ids=None, file_name=None):
        ids = set(space_ids) if file_ids is None else set(space_ids) & file_ids
        return {sid: RobotFileSource(sid, f"file-{sid}.pdf", sid, f"space-{sid}") for sid in sorted(ids)}

    async def search_file_sources(self, *, tenant_id, space_ids, keywords, limit=50):
        return await self.file_sources(tenant_id=tenant_id, space_ids=space_ids)


class GatedBackend:
    def __init__(self, *, supplement=False):
        self.supplement = supplement
        self.active = 0
        self.peak = 0
        self.started = []
        self.tenant_contexts = []
        self.six_started = asyncio.Event()
        self.release = asyncio.Event()

    async def retrieve_space(self, *, space_id, file_ids, **kwargs):
        if self.supplement and file_ids is None:
            return []
        self.started.append((space_id, file_ids))
        self.tenant_contexts.append(get_current_tenant_id())
        self.active += 1
        self.peak = max(self.peak, self.active)
        if self.active == 6:
            self.six_started.set()
        try:
            await self.release.wait()
            return [_doc(space_id, space_id, text="医学研究")]
        finally:
            self.active -= 1


def policy(backend, spaces):
    return RobotSpaceRetrievalPolicy(
        tenant_id=9, bot_config_id=3, invoke_user_id=88, document_state_reader=Sources(), retrieval_backend=backend
    ), AssistantRobotScope(3, tuple(spaces), 1)


@pytest.mark.parametrize("supplement", [False, True])
async def test_recall_and_supplement_overlap_six_spaces_but_never_start_a_seventh(supplement):
    backend = GatedBackend(supplement=supplement)
    retriever, scope = policy(backend, range(1, 14))
    set_current_tenant_id(9)
    task = asyncio.create_task(
        retriever.retrieve("医学研究", expected_scope=scope, file_name_query="医学" if supplement else None)
    )
    try:
        await asyncio.wait_for(backend.six_started.wait(), 1)
        # Let any unbounded tasks attempt to enter while the first six are blocked.
        await asyncio.sleep(0)
        assert backend.active == backend.peak == 6
        assert len(backend.started) == 6
        backend.release.set()
        result = await asyncio.wait_for(task, 1)
        assert [d.metadata["document_id"] for d in result] == list(range(1, 14))
        assert backend.peak == 6
        assert backend.active == 0
        assert len(backend.started) == 13
        assert all(value == 9 for value in backend.tenant_contexts)
        if supplement:
            assert all(ids == (sid,) for sid, ids in backend.started)
    finally:
        backend.release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_parallel_tool_calls_in_one_turn_share_the_six_space_limit():
    backend = GatedBackend()
    retriever, scope = policy(backend, range(1, 5))
    set_current_tenant_id(9)
    tasks = [asyncio.create_task(retriever.retrieve(q, expected_scope=scope)) for q in ("A", "B")]
    try:
        await asyncio.wait_for(backend.six_started.wait(), 1)
        await asyncio.sleep(0)
        assert backend.active == backend.peak == 6
        backend.release.set()
        results = await asyncio.wait_for(asyncio.gather(*tasks), 1)
        assert all(len(result) == 4 for result in results)
        assert backend.peak == 6
    finally:
        backend.release.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.parametrize("failure", [False, True])
async def test_cancellation_or_one_space_failure_cleans_up_running_and_waiting_tasks(failure):
    class FailingBackend(GatedBackend):
        async def retrieve_space(self, **kwargs):
            if failure and kwargs["space_id"] == 6:
                await self.six_started.wait()
                raise RuntimeError("index unavailable")
            return await super().retrieve_space(**kwargs)

    backend = FailingBackend()
    retriever, scope = policy(backend, range(1, 14))
    set_current_tenant_id(9)
    task = asyncio.create_task(retriever.retrieve("医学研究", expected_scope=scope))
    try:
        if failure:
            # Five index calls run and the sixth waits to fail.
            async def wait_for_siblings():
                while len(backend.started) < 5 and not task.done():
                    await asyncio.sleep(0)

            await asyncio.wait_for(wait_for_siblings(), 1)
            backend.six_started.set()
            with pytest.raises(ExceptionGroup) as error:
                await asyncio.wait_for(task, 1)
            assert any(isinstance(exc, RuntimeError) for exc in error.value.exceptions)
        else:
            await asyncio.wait_for(backend.six_started.wait(), 1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert backend.active == 0
        if not failure:
            assert all(sid <= 6 for sid, _ in backend.started)
    finally:
        backend.release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_completion_order_does_not_change_which_duplicate_is_retained():
    class ReverseBackend:
        def __init__(self):
            self.second_finished = asyncio.Event()

        async def retrieve_space(self, *, space_id, **kwargs):
            if space_id == 1:
                await self.second_finished.wait()
            else:
                self.second_finished.set()
            doc = _doc(1, 1, text="医学研究")
            doc.metadata["marker"] = space_id
            return [doc]

    retriever, scope = policy(ReverseBackend(), (1, 2))
    result = await asyncio.wait_for(retriever.retrieve("医学研究", expected_scope=scope), 1)
    assert len(result) == 1
    assert result[0].metadata["marker"] == 1


async def test_sync_executor_can_reuse_policy_across_fresh_event_loops():
    class YieldingBackend:
        async def retrieve_space(self, *, space_id, **kwargs):
            await asyncio.sleep(0)
            return [_doc(space_id, space_id, text="医学研究")]

    retriever, scope = policy(YieldingBackend(), range(1, 8))

    def run():
        return asyncio.run(retriever.retrieve("医学研究", expected_scope=scope))

    assert len(await asyncio.to_thread(run)) == 7
    assert len(await asyncio.to_thread(run)) == 7
