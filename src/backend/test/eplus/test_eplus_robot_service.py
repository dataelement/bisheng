from __future__ import annotations

import asyncio
from collections import defaultdict

import pytest

from bisheng.eplus.domain.models.eplus import EPlusTurn
from bisheng.eplus.domain.schemas.execution import (
    EPlusAssistantRequest,
    EPlusBotRuntimeContext,
    EPlusTurnDelivery,
)
from bisheng.eplus.domain.schemas.protocol import EPlusCallback, EPlusContentBlock, EPlusContentKind
from bisheng.eplus.domain.services.conversation_scheduler import EPlusHistoryTurn, ReadyEPlusTurn
from bisheng.eplus.domain.services.message_service import (
    AdmissionDisposition,
    AdmissionResult,
    EPlusAdmissionContext,
)
from bisheng.eplus.domain.services.robot_service import EPlusRobotService


def _callback(msg_id: str, msg_type: str = "text") -> EPlusCallback:
    blocks = {
        "text": (EPlusContentBlock(EPlusContentKind.TEXT, text="hello"),),
        "image": (EPlusContentBlock(EPlusContentKind.IMAGE, url="https://media/image", aes_key="key"),),
        "mixed": (
            EPlusContentBlock(EPlusContentKind.TEXT, text="look"),
            EPlusContentBlock(EPlusContentKind.IMAGE, url="https://media/image", aes_key="key"),
        ),
    }[msg_type]
    return EPlusCallback(
        req_id=f"req-{msg_id}",
        msg_id=msg_id,
        bot_id="bot-1",
        sender_external_id="user-1",
        chat_type="single",
        chat_id=None,
        msg_type=msg_type,
        blocks=blocks,
    )


def _context(sender=object()) -> EPlusBotRuntimeContext:
    return EPlusBotRuntimeContext(
        admission=EPlusAdmissionContext(
            tenant_id=9,
            bot_config_id=73,
            assistant_id="assistant-1",
            bot_id="bot-1",
            scope_version=1,
            space_ids=(11,),
            media_hosts=("media",),
            ca_pem=None,
        ),
        sender=sender,
    )


def _ready(
    turn_id: str,
    conversation_id: str,
    *,
    manifest: list[dict] | None = None,
    scope_version: int = 1,
    spaces: tuple[int, ...] = (11,),
    history: tuple[EPlusHistoryTurn, ...] = (),
) -> ReadyEPlusTurn:
    return ReadyEPlusTurn(
        turn=EPlusTurn(
            id=turn_id,
            tenant_id=9,
            conversation_id=conversation_id,
            inbound_message_id=int(turn_id.rsplit("-", 1)[-1]),
            turn_seq=int(turn_id.rsplit("-", 1)[-1]),
            sender_user_id=88,
            sender_external_id="user-1",
            user_text="hello",
            content_manifest=manifest or [{"kind": "text", "text": "hello", "media": None}],
            scope_version=scope_version,
            scope_space_ids=list(spaces),
            status="RUNNING",
        ),
        history=history,
    )


class FakeAdmission:
    def __init__(self) -> None:
        self.results: dict[str, AdmissionResult] = {}

    async def admit(self, context, callback) -> AdmissionResult:
        return self.results[callback.msg_id]


class FakeScheduler:
    def __init__(self) -> None:
        self.queues: dict[str, list[ReadyEPlusTurn]] = defaultdict(list)
        self.completed: list[tuple[str, bool, str | None, str | None]] = []

    async def next_ready_turn(self, tenant_id: int, conversation_id: str):
        queue = self.queues[conversation_id]
        return queue.pop(0) if queue else None

    async def expire_waiting_turn(self, *, tenant_id, turn_id):
        return False

    async def complete_and_wake_next(
        self,
        *,
        tenant_id,
        turn_id,
        succeeded,
        answer_text=None,
        error_code=None,
        execution_token,
    ):
        self.completed.append((turn_id, succeeded, answer_text, error_code))
        conversation_id = turn_id.rsplit("-", 1)[0]
        return await self.next_ready_turn(tenant_id, conversation_id)


class FakeTurnLoader:
    async def load(self, ready: ReadyEPlusTurn) -> EPlusTurnDelivery:
        turn = ready.turn
        return EPlusTurnDelivery(
            tenant_id=9,
            assistant_id="assistant-1",
            conversation_id=turn.conversation_id,
            turn_id=turn.id,
            inbound_message_id=turn.inbound_message_id,
            req_id=f"req-{turn.id}",
            stream_id=f"stream-{turn.id}",
            sender_user_id=turn.sender_user_id,
            sender_external_id=turn.sender_external_id,
            content_manifest=tuple(turn.content_manifest),
            scope_version=turn.scope_version,
            space_ids=tuple(turn.scope_space_ids),
            history=ready.history,
            execution_token=turn.assistant_run_id or "execution-token",
        )


class FakeMedia:
    async def materialize(self, blocks, *, supports_vision: bool, user_id: int):
        result = []
        for block in blocks:
            if block.kind == "text":
                result.append({"type": "text", "text": block.text})
            elif block.kind == "error":
                result.append({"type": "text", "text": block.text})
            elif supports_vision:
                result.append({"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}})
            else:
                result.append({"type": "text", "text": "[OCR image]"})
        return result


class FakeAssistantRuntime:
    def __init__(self, factory) -> None:
        self.factory = factory
        self.supports_vision = True

    async def astream(self, request: EPlusAssistantRequest):
        self.factory.requests.append(request)
        if self.factory.error is not None:
            raise self.factory.error
        self.factory.started.set()
        if self.factory.block is not None:
            await self.factory.block.wait()
        for fragment in self.factory.fragments:
            yield fragment


class FakeAssistantFactory:
    def __init__(self, *, fragments=("answer",), error=None, block=None) -> None:
        self.fragments = fragments
        self.error = error
        self.block = block
        self.requests: list[EPlusAssistantRequest] = []
        self.created = 0
        self.started = asyncio.Event()

    async def create(self, delivery: EPlusTurnDelivery):
        self.created += 1
        return FakeAssistantRuntime(self)


class FakeReplyStream:
    def __init__(self, *, start_error=None) -> None:
        self.start_error = start_error
        self.events: list[tuple] = []
        self.answer = ""
        self.finished = False

    async def start(self) -> None:
        self.events.append(("start",))
        if self.start_error:
            raise self.start_error

    async def append(self, fragment: str) -> bool:
        self.answer += fragment
        self.events.append(("append", fragment))
        return True

    async def finish(self) -> None:
        self.events.append(("finish", self.answer))
        self.finished = True

    async def send_terminal(self, content: str, *, error_code: str | None = None) -> None:
        self.answer = content
        self.events.append(("terminal", content, error_code))
        self.finished = True

    async def fail(self, content: str, *, error_code: str) -> None:
        self.answer = content
        self.events.append(("fail", content, error_code))
        self.finished = True


class FakeReplyFactory:
    def __init__(self, *, start_error=None) -> None:
        self.start_error = start_error
        self.streams: dict[str, FakeReplyStream] = {}
        self.calls: list[dict] = []

    def create(self, *, req_id: str, **kwargs) -> FakeReplyStream:
        self.calls.append({"req_id": req_id, **kwargs})
        stream = FakeReplyStream(start_error=self.start_error)
        self.streams[req_id] = stream
        return stream


def _service(
    admission,
    scheduler,
    assistant,
    replies,
    *,
    turn_loader=None,
    execution_timeout_seconds=300,
) -> EPlusRobotService:
    return EPlusRobotService(
        admission_service=admission,
        scheduler=scheduler,
        turn_loader=turn_loader or FakeTurnLoader(),
        media_service=FakeMedia(),
        assistant_factory=assistant,
        reply_factory=replies,
        execution_timeout_seconds=execution_timeout_seconds,
    )


@pytest.mark.parametrize(
    ("msg_type", "manifest", "expected_types"),
    [
        ("text", [{"kind": "text", "text": "hello", "media": None}], ["text"]),
        (
            "image",
            [
                {
                    "kind": "image",
                    "text": None,
                    "media": {"object_key": "o", "sha256": "s", "mime_type": "image/png", "size": 4},
                }
            ],
            ["image_url"],
        ),
        (
            "mixed",
            [
                {"kind": "text", "text": "look", "media": None},
                {
                    "kind": "image",
                    "text": None,
                    "media": {"object_key": "o", "sha256": "s", "mime_type": "image/png", "size": 4},
                },
            ],
            ["text", "image_url"],
        ),
        (
            "mixed",
            [
                {"kind": "text", "text": "still usable", "media": None},
                {"kind": "error", "text": "[无法读取图片]", "media": None},
            ],
            ["text", "text"],
        ),
    ],
)
async def test_four_input_shapes_reach_assistant_and_finish(msg_type, manifest, expected_types) -> None:
    admission = FakeAdmission()
    scheduler = FakeScheduler()
    assistant = FakeAssistantFactory(fragments=("an", "swer"))
    replies = FakeReplyFactory()
    callback = _callback(f"c-{msg_type}", msg_type)
    conversation_id = f"conversation-{msg_type}"
    admission.results[callback.msg_id] = AdmissionResult(
        AdmissionDisposition.QUEUED, 1, conversation_id, f"{conversation_id}-1"
    )
    scheduler.queues[conversation_id].append(_ready(f"{conversation_id}-1", conversation_id, manifest=manifest))
    service = _service(admission, scheduler, assistant, replies)

    await service.handle_message(_context(), callback)
    await service.wait_idle()

    assert [block["type"] for block in assistant.requests[0].content] == expected_types
    assert replies.streams[f"req-{conversation_id}-1"].events[-1] == ("finish", "answer")
    assert scheduler.completed == [(f"{conversation_id}-1", True, "answer", None)]


@pytest.mark.parametrize(
    ("disposition", "reply"),
    [
        (AdmissionDisposition.NO_PERMISSION, "无权限使用"),
        (AdmissionDisposition.BUSY, "消息处理中，请稍后再试"),  # noqa: RUF001
    ],
)
async def test_rejections_send_one_terminal_reply_without_assistant(disposition, reply) -> None:
    admission = FakeAdmission()
    callback = _callback(disposition.value)
    admission.results[callback.msg_id] = AdmissionResult(disposition, 1, reply_text=reply)
    scheduler = FakeScheduler()
    assistant = FakeAssistantFactory()
    replies = FakeReplyFactory()
    service = _service(admission, scheduler, assistant, replies)

    await service.handle_message(_context(), callback)

    assert replies.streams[callback.req_id].events == [("terminal", reply, disposition.value.upper())]
    assert assistant.created == 0


async def test_rejections_share_quota_key_for_same_bot_conversation() -> None:
    admission = FakeAdmission()
    replies = FakeReplyFactory()
    service = _service(admission, FakeScheduler(), FakeAssistantFactory(), replies)

    for msg_id in ("rejected-1", "rejected-2"):
        callback = _callback(msg_id)
        admission.results[msg_id] = AdmissionResult(
            AdmissionDisposition.NO_PERMISSION,
            int(msg_id.rsplit("-", 1)[-1]),
            reply_text="无权限使用",
        )
        await service.handle_message(_context(), callback)

    quota_keys = [call["conversation_id"] for call in replies.calls]
    assert quota_keys[0] == quota_keys[1]
    assert quota_keys[0].startswith("rejected:")


async def test_duplicate_does_not_reply_or_run_assistant() -> None:
    admission = FakeAdmission()
    callback = _callback("duplicate")
    admission.results[callback.msg_id] = AdmissionResult(AdmissionDisposition.DUPLICATE, 1)
    assistant = FakeAssistantFactory()
    replies = FakeReplyFactory()
    service = _service(admission, FakeScheduler(), assistant, replies)

    await service.handle_message(_context(), callback)

    assert replies.streams == {}
    assert assistant.created == 0


async def test_scope_change_keeps_running_snapshot_next_turn_uses_new_scope_and_full_history() -> None:
    admission = FakeAdmission()
    scheduler = FakeScheduler()
    gate = asyncio.Event()
    assistant = FakeAssistantFactory(block=gate)
    replies = FakeReplyFactory()
    callback = _callback("scope")
    conversation = "conversation-scope"
    admission.results[callback.msg_id] = AdmissionResult(
        AdmissionDisposition.QUEUED, 1, conversation, f"{conversation}-1"
    )
    old_history = EPlusHistoryTurn("old", 0, 88, "user-1", "old q", (), "old a")
    scheduler.queues[conversation] = [
        _ready(f"{conversation}-1", conversation, scope_version=1, spaces=(11,)),
        _ready(
            f"{conversation}-2",
            conversation,
            scope_version=2,
            spaces=(12,),
            history=(old_history,),
        ),
    ]
    service = _service(admission, scheduler, assistant, replies)

    await service.handle_message(_context(), callback)
    await assistant.started.wait()
    gate.set()
    await service.wait_idle()

    assert [request.robot_scope.space_ids for request in assistant.requests] == [(11,), (12,)]
    assert assistant.requests[1].history[0].answer == "old a"


async def test_assistant_error_sends_safe_failure_and_releases_turn() -> None:
    admission = FakeAdmission()
    scheduler = FakeScheduler()
    assistant = FakeAssistantFactory(error=RuntimeError("provider secret detail"))
    replies = FakeReplyFactory()
    callback = _callback("failure")
    conversation = "conversation-failure"
    admission.results[callback.msg_id] = AdmissionResult(
        AdmissionDisposition.QUEUED, 1, conversation, f"{conversation}-1"
    )
    scheduler.queues[conversation].append(_ready(f"{conversation}-1", conversation))
    service = _service(admission, scheduler, assistant, replies)

    await service.handle_message(_context(), callback)
    await service.wait_idle()

    assert replies.streams[f"req-{conversation}-1"].events[-1] == (
        "fail",
        "处理失败，请稍后重试",  # noqa: RUF001
        "ASSISTANT_ERROR",
    )
    assert scheduler.completed[-1] == (f"{conversation}-1", False, None, "ASSISTANT_ERROR")


async def test_hard_timeout_cancels_silent_assistant_and_wakes_queue() -> None:
    admission = FakeAdmission()
    scheduler = FakeScheduler()
    assistant = FakeAssistantFactory(block=asyncio.Event())
    replies = FakeReplyFactory()
    callback = _callback("timeout")
    conversation = "conversation-timeout"
    admission.results[callback.msg_id] = AdmissionResult(
        AdmissionDisposition.QUEUED, 1, conversation, f"{conversation}-1"
    )
    scheduler.queues[conversation].append(_ready(f"{conversation}-1", conversation))
    service = _service(
        admission,
        scheduler,
        assistant,
        replies,
        execution_timeout_seconds=0.01,
    )

    await service.handle_message(_context(), callback)
    await service.wait_idle()

    assert replies.streams[f"req-{conversation}-1"].events[-1] == (
        "fail",
        "处理超时，请稍后重试",  # noqa: RUF001
        "ASSISTANT_TIMEOUT",
    )
    assert scheduler.completed[-1] == (f"{conversation}-1", False, None, "ASSISTANT_TIMEOUT")


async def test_lost_bot_ownership_cancels_running_consumer_without_completing_it() -> None:
    admission = FakeAdmission()
    scheduler = FakeScheduler()
    assistant = FakeAssistantFactory(block=asyncio.Event())
    callback = _callback("lease-lost")
    conversation = "conversation-lease-lost"
    admission.results[callback.msg_id] = AdmissionResult(
        AdmissionDisposition.QUEUED, 1, conversation, f"{conversation}-1"
    )
    scheduler.queues[conversation].append(_ready(f"{conversation}-1", conversation))
    service = _service(admission, scheduler, assistant, FakeReplyFactory())

    await service.handle_message(_context(), callback)
    await assistant.started.wait()
    await service.cancel_bot(tenant_id=9, bot_config_id=73)

    assert scheduler.completed == []


async def test_first_frame_failure_never_creates_assistant() -> None:
    admission = FakeAdmission()
    scheduler = FakeScheduler()
    assistant = FakeAssistantFactory()
    replies = FakeReplyFactory(start_error=TimeoutError("ACK timeout"))
    callback = _callback("ack-failure")
    conversation = "conversation-ack-failure"
    admission.results[callback.msg_id] = AdmissionResult(
        AdmissionDisposition.QUEUED, 1, conversation, f"{conversation}-1"
    )
    scheduler.queues[conversation].append(_ready(f"{conversation}-1", conversation))
    service = _service(admission, scheduler, assistant, replies)

    await service.handle_message(_context(), callback)
    await service.wait_idle()

    assert assistant.created == 0
    assert scheduler.completed[-1] == (f"{conversation}-1", False, None, "REPLY_START_FAILED")


async def test_orchestration_failure_releases_turn_without_starting_assistant() -> None:
    class BrokenTurnLoader:
        async def load(self, ready):
            raise LookupError("missing delivery")

    admission = FakeAdmission()
    scheduler = FakeScheduler()
    assistant = FakeAssistantFactory()
    callback = _callback("orchestration-failure")
    conversation = "conversation-orchestration-failure"
    admission.results[callback.msg_id] = AdmissionResult(
        AdmissionDisposition.QUEUED, 1, conversation, f"{conversation}-1"
    )
    scheduler.queues[conversation].append(_ready(f"{conversation}-1", conversation))
    service = _service(
        admission,
        scheduler,
        assistant,
        FakeReplyFactory(),
        turn_loader=BrokenTurnLoader(),
    )

    await service.handle_message(_context(), callback)
    await service.wait_idle()

    assert assistant.created == 0
    assert scheduler.completed[-1] == (
        f"{conversation}-1",
        False,
        None,
        "ORCHESTRATION_ERROR",
    )


async def test_different_conversations_execute_concurrently() -> None:
    admission = FakeAdmission()
    scheduler = FakeScheduler()
    gate = asyncio.Event()
    assistant = FakeAssistantFactory(block=gate)
    replies = FakeReplyFactory()
    service = _service(admission, scheduler, assistant, replies)

    for index in (1, 2):
        callback = _callback(f"parallel-{index}")
        conversation = f"parallel-{index}"
        admission.results[callback.msg_id] = AdmissionResult(
            AdmissionDisposition.QUEUED, index, conversation, f"{conversation}-1"
        )
        scheduler.queues[conversation].append(_ready(f"{conversation}-1", conversation))
        await service.handle_message(_context(), callback)

    await _eventually(lambda: assistant.created == 2)
    gate.set()
    await service.wait_idle()


async def _eventually(predicate, *, timeout: float = 1) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0)


async def test_history_budget_excludes_old_image_before_materialization():
    class RejectOldImage(FakeMedia):
        async def materialize(self, blocks, **kwargs):
            assert all(block.kind != "image" for block in blocks), "out-of-budget image must not be read"
            return await super().materialize(blocks, **kwargs)

    older = EPlusHistoryTurn(
        "old",
        1,
        88,
        "user-1",
        None,
        ({"kind": "image", "media": {"object_key": "o", "sha256": "s", "mime_type": "image/png", "size": 4}},),
        "x" * 1000,
    )
    recent = EPlusHistoryTurn("recent", 2, 88, "user-1", "recent q", (), "recent a")
    delivery = await FakeTurnLoader().load(_ready("c-3", "c", history=(older, recent)))
    service = _service(FakeAdmission(), FakeScheduler(), FakeAssistantFactory(), FakeReplyFactory())
    service._media = RejectOldImage()

    request = await service._build_request(_context(), delivery, False, history_budget=100)

    assert [(item.content, item.answer) for item in request.history] == [
        ([{"type": "text", "text": "recent q"}], "recent a"),
    ]


async def test_waiting_hint_is_sent_before_media_finalization_and_reused_for_answer():
    from bisheng.eplus.domain.services.message_service import EPlusAdmissionReservation
    from bisheng.eplus.domain.services.reply_stream import EPlusReplyStream
    from test.eplus.test_eplus_reply_stream import FakeQuota, FakeRecorder, FakeSender

    sender = FakeSender()
    callback = _callback("early")
    scheduler = FakeScheduler()
    scheduler.queues["c"] = [_ready("c-1", "c")]

    class ReservedAdmission:
        async def finalize(self, context, callback, reservation):
            assert sender.frames[0]["body"]["stream"]["content"] == "处理中"
            return AdmissionResult(AdmissionDisposition.QUEUED, 1, "c", "c-1")

    class ReplyFactory:
        def create(self, **values):
            return EPlusReplyStream(
                sender=values["sender"],
                quota=FakeQuota(),
                recorder=FakeRecorder(),
                req_id=values["req_id"],
                stream_id=values["stream_id"],
            )

    service = _service(ReservedAdmission(), scheduler, FakeAssistantFactory(), ReplyFactory())
    await service.handle_reserved_message(_context(sender), callback, EPlusAdmissionReservation(1, "c", "c-1"))
    await service.wait_idle()

    streams = [frame["body"]["stream"] for frame in sender.frames]
    assert [item["content"] for item in streams].count("处理中") == 1
    assert len({item["id"] for item in streams}) == 1
    assert streams[-1]["content"] == "answer"
    assert streams[-1]["finish"] is True


async def test_queue_wait_timeout_returns_terminal_without_executing_later():
    from bisheng.eplus.domain.services.message_service import EPlusAdmissionReservation
    from bisheng.eplus.domain.services.reply_stream import EPlusReplyStream
    from test.eplus.test_eplus_reply_stream import FakeQuota, FakeRecorder, FakeSender

    sender = FakeSender()
    gate = asyncio.Event()
    scheduler = FakeScheduler()
    assistant = FakeAssistantFactory()

    class Admission:
        async def finalize(self, context, callback, reservation):
            await gate.wait()
            return AdmissionResult(AdmissionDisposition.QUEUED, 1, "c", "c-1")

    class Replies:
        def create(self, **values):
            return EPlusReplyStream(
                sender=sender,
                quota=FakeQuota(),
                recorder=FakeRecorder(),
                req_id=values["req_id"],
                stream_id=values["stream_id"],
            )

    service = _service(Admission(), scheduler, assistant, Replies(), execution_timeout_seconds=0.02)
    task = asyncio.create_task(
        service.handle_reserved_message(
            _context(sender),
            _callback("expiry"),
            EPlusAdmissionReservation(1, "c", "c-1"),
        )
    )
    await _eventually(lambda: len(sender.frames) == 2)
    assert sender.frames[-1]["body"]["stream"]["finish"] is True
    scheduler.queues["c"] = [_ready("c-1", "c")]
    gate.set()
    await task
    await service.wait_idle()

    assert assistant.created == 0
    assert scheduler.completed == [("c-1", False, None, "ASSISTANT_TIMEOUT")]
    assert len(sender.frames) == 2


async def test_history_with_saved_text_does_not_retry_failed_image_ocr():
    from dataclasses import replace

    old = EPlusHistoryTurn("old", 1, 88, "user-1", None, ({"kind": "image", "media": None},), "answer")
    old = replace(old, extracted_text="[图片文字提取失败, 请补充文字描述]")
    delivery = await FakeTurnLoader().load(_ready("c-2", "c", history=(old,)))
    service = _service(FakeAdmission(), FakeScheduler(), FakeAssistantFactory(), FakeReplyFactory())
    request = await service._build_request(_context(), delivery, False)

    assert request.history[0].content == [{"type": "text", "text": "[图片文字提取失败, 请补充文字描述]"}]


async def test_claim_does_not_cancel_an_inflight_timeout_ack():
    from bisheng.eplus.domain.services.message_service import EPlusAdmissionReservation
    from bisheng.eplus.domain.services.reply_stream import EPlusReplyStream
    from test.eplus.test_eplus_reply_stream import FakeQuota, FakeRecorder, FakeSender

    terminal_started, terminal_ack = asyncio.Event(), asyncio.Event()

    class SlowTerminalSender(FakeSender):
        async def send_with_ack(self, frame):
            result = await super().send_with_ack(frame)
            if frame["body"]["stream"]["finish"]:
                terminal_started.set()
                await terminal_ack.wait()
            return result

    sender = SlowTerminalSender()
    recorder = FakeRecorder()

    class Replies:
        def create(self, **values):
            return EPlusReplyStream(
                sender=sender,
                quota=FakeQuota(),
                recorder=recorder,
                req_id=values["req_id"],
                stream_id=values["stream_id"],
            )

    scheduler = FakeScheduler()
    service = _service(FakeAdmission(), scheduler, FakeAssistantFactory(), Replies(), execution_timeout_seconds=0.02)
    await service._start_waiting_reply(
        _context(sender), _callback("ack-race"), EPlusAdmissionReservation(1, "c", "c-1")
    )
    await terminal_started.wait()
    execution = asyncio.create_task(service._execute_turn(_context(sender), _ready("c-1", "c")))
    try:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(execution), timeout=0.02)
    finally:
        terminal_ack.set()
        await execution
        await service.close()

    assert recorder.events[-1][0].value == "FINISHED"
    assert scheduler.completed == [("c-1", False, None, "ASSISTANT_TIMEOUT")]


async def test_cancelled_media_admission_does_not_send_after_losing_ownership():
    from bisheng.eplus.domain.services.message_service import EPlusAdmissionReservation
    from bisheng.eplus.domain.services.reply_stream import EPlusReplyStream
    from test.eplus.test_eplus_reply_stream import FakeQuota, FakeRecorder, FakeSender

    sender, entered = FakeSender(), asyncio.Event()

    class Admission:
        async def finalize(self, *args):
            entered.set()
            await asyncio.Event().wait()

    class Replies:
        def create(self, **values):
            return EPlusReplyStream(
                sender=sender,
                quota=FakeQuota(),
                recorder=FakeRecorder(),
                req_id=values["req_id"],
                stream_id=values["stream_id"],
            )

    service = _service(Admission(), FakeScheduler(), FakeAssistantFactory(), Replies())
    task = asyncio.create_task(
        service.handle_reserved_message(
            _context(sender),
            _callback("cancel-admission"),
            EPlusAdmissionReservation(1, "c", "c-1"),
        )
    )
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await service.close()

    assert len(sender.frames) == 1
    assert sender.frames[0]["body"]["stream"]["finish"] is False


async def test_recovered_expired_delivery_never_starts_placeholder_or_model():
    from dataclasses import replace
    from datetime import datetime, timedelta

    class RecoveredLoader(FakeTurnLoader):
        async def load(self, ready):
            return replace(await super().load(ready), reply_started_at=datetime.now() - timedelta(seconds=310))

    scheduler, assistant, replies = FakeScheduler(), FakeAssistantFactory(), FakeReplyFactory()
    service = _service(FakeAdmission(), scheduler, assistant, replies, turn_loader=RecoveredLoader())

    await service._execute_turn(_context(), _ready("c-1", "c"))

    assert assistant.created == 0
    assert all(event[0] != "start" for event in replies.streams["req-c-1"].events)
    assert scheduler.completed == [("c-1", False, None, "ASSISTANT_TIMEOUT")]
