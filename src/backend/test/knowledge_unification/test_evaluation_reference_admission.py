"""JWT evaluation admission owns its real row and actual version. 覆盖 AC: AC-68, AC-79, AC-83, AC-91."""

from contextlib import contextmanager
from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import sqlalchemy as sa
from fastapi import BackgroundTasks, UploadFile
from sqlmodel import Session

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.http_error import NotFoundError, UnAuthorizedError
from bisheng.core.context.tenant import bypass_tenant_filter, current_tenant_id, set_current_tenant_id
from bisheng.core.database import tenant_filter
from bisheng.database.models.flow_version import FlowVersion
from bisheng.evaluation.api.endpoints import evaluation as endpoint
from bisheng.evaluation.domain.models.evaluation import Evaluation, EvaluationTaskStatus
from bisheng.evaluation.domain.repositories import evaluation_repository as repository_module
from bisheng.evaluation.domain.services import evaluation_service as service
from bisheng.open_api.domain.context import reset_current_open_api_principal, set_current_open_api_principal
from bisheng.permission.application.identity import get_current_permission_actor
from bisheng.resource_reference.application.contracts import reference_set_digest
from bisheng.resource_reference.domain.models.business_reference_set import BusinessReferenceSet
from bisheng.workflow.common.workflow import WorkflowStatus
from test.knowledge_unification import test_wf_entry as workflow_fixtures
from test.open_api.test_dependencies import service_account_principal

store = workflow_fixtures.store
tenant = workflow_fixtures.tenant
real_core = workflow_fixtures.real_core


@pytest.fixture
async def evaluation_context(real_core, store, monkeypatch):
    engine, sync = store
    table = sa.Table(
        Evaluation.__tablename__,
        sa.MetaData(),
        *[
            sa.Column(
                column.name,
                column.type.copy(),
                primary_key=column.primary_key,
                nullable=column.nullable,
                server_default=sa.text("CURRENT_TIMESTAMP")
                if column.name in {"create_time", "update_time"}
                else column.server_default,
            )
            for column in Evaluation.__table__.columns
        ],
    )
    table.create(sync)
    monkeypatch.setattr(tenant_filter, "_tenant_aware_tables", tenant_filter._tenant_aware_tables | {table.name})

    @contextmanager
    def sessions():
        with Session(sync, expire_on_commit=False) as session:
            yield session

    monkeypatch.setattr(repository_module, "get_sync_db_session", sessions)
    monkeypatch.setattr(endpoint, "get_sync_db_session", sessions)
    graph = {"nodes": [{"data": {"id": "draft-code", "type": "code", "prompt": "actual-v2"}}], "edges": []}
    with sessions() as session:
        session.add_all(
            [
                Evaluation(
                    id=key,
                    user_id=owner,
                    tenant_id=tenant_id,
                    exec_type="workflow",
                    unique_id="wf",
                    version=2,
                    file_path="dataset.csv",
                    result_score={"old": "kept"},
                    result_file_path="old.csv",
                    is_delete=deleted,
                )
                for key, owner, tenant_id, deleted in [
                    (42, 11, 101, 0),
                    (43, 22, 101, 0),
                    (44, 11, 202, 0),
                    (45, 11, 1, 0),
                    (46, 11, 101, 1),
                ]
            ]
        )
        session.add(
            BusinessReferenceSet(
                tenant_id=101,
                source_type="workflow_version",
                source_id="wf",
                source_version="2",
                source_revision=1,
                extractor_version="workflow-version-v1",
                digest=reference_set_digest(()),
                effective=True,
                ready=True,
            )
        )
        session.execute(sa.update(FlowVersion).where(FlowVersion.id == 2).values(data=graph))
        session.commit()
    read_csv = Mock(return_value=BytesIO(b"question,ground_truth\nfirst,one\nsecond,two\n"))
    monkeypatch.setattr(service.EvaluationService, "read_csv_file", read_csv)
    monkeypatch.setattr(service.EvaluationService, "upload_file", Mock(return_value=("dataset.csv", "dataset.csv")))
    monkeypatch.setattr(service.EvaluationService, "upload_result_file", Mock(return_value="result.csv"))
    redis = SimpleNamespace(set=Mock(), delete=Mock())
    get_redis = Mock(return_value=redis)
    monkeypatch.setattr(service, "get_redis_client_sync", get_redis)
    score_llm = AsyncMock(return_value=object())
    monkeypatch.setattr(service.LLMService, "get_evaluation_llm_object", score_llm)

    def score(llm, questions, answers, truths, prompt):
        return {
            "question": questions,
            "answer": answers,
            "ground_truths": truths,
            **{
                key: [1] * len(questions)
                for key in [
                    "statements_num_gt_only",
                    "statements_num_answer_only",
                    "statements_num_overlap",
                    "answer_recall",
                    "answer_precision",
                    "answer_f1",
                ]
            },
        }

    monkeypatch.setattr(service, "compute_answer_correctness", Mock(side_effect=score))
    return SimpleNamespace(
        identity=real_core.identity,
        actor=get_current_permission_actor(),
        engine=engine,
        sync=sync,
        sessions=sessions,
        graph=graph,
        read_csv=read_csv,
        redis=redis,
        get_redis=get_redis,
        score_llm=score_llm,
    )


def row(context, evaluation_id=42):
    with context.sessions() as session:
        return session.get(Evaluation, evaluation_id)


def set_values(context, **values):
    with context.sync.begin() as connection:
        connection.execute(sa.update(Evaluation).where(Evaluation.id == 42).values(**values))


@pytest.mark.parametrize("evaluation_id", [43, 44, 45, 46, 999])
def test_process_rejects_real_other_owner_wrong_current_tenant_deleted_or_missing_before_schedule(
    evaluation_context, evaluation_id
):
    ctx = evaluation_context
    tasks = BackgroundTasks()
    with pytest.raises(NotFoundError):
        endpoint.process_evaluation(evaluation_id=evaluation_id, background_tasks=tasks, login_user=ctx.identity)
    assert not tasks.tasks and not ctx.read_csv.called and not ctx.get_redis.called


def test_process_and_create_background_tasks_carry_original_jwt_object(evaluation_context):
    ctx = evaluation_context
    manual = BackgroundTasks()
    endpoint.process_evaluation(evaluation_id=42, background_tasks=manual, login_user=ctx.identity)
    assert manual.tasks[0].kwargs == {"evaluation_id": 42, "login_user": ctx.identity}
    assert manual.tasks[0].kwargs["login_user"] is ctx.identity
    create = BackgroundTasks()
    upload = UploadFile(file=BytesIO(b"question,ground_truth\nfirst,one\n"), filename="dataset.csv")
    result = endpoint.create_evaluation(
        file=upload,
        prompt="",
        exec_type="workflow",
        unique_id="wf",
        version=2,
        background_tasks=create,
        login_user=ctx.identity,
    )
    assert create.tasks[0].kwargs["login_user"] is ctx.identity
    created = service.EvaluationService.require_evaluation_owner(result.data.id, ctx.identity)
    assert created.tenant_id == 101 and created.user_id == ctx.identity.user_id and upload.file.closed


@pytest.mark.parametrize("kind", ["id_only", "bypass", "missing_tenant", "open_api"])
def test_jwt_task_owner_check_never_promotes_other_identity_channels(evaluation_context, kind):
    ctx = evaluation_context
    if kind == "id_only":
        with pytest.raises(UnAuthorizedError):
            service.EvaluationService.require_evaluation_owner(42, SimpleNamespace(user_id=11))
    elif kind == "bypass":
        with bypass_tenant_filter(), pytest.raises(UnAuthorizedError):
            service.EvaluationService.require_evaluation_owner(42, ctx.identity)
    elif kind == "missing_tenant":
        token = set_current_tenant_id(None)
        try:
            with pytest.raises(UnAuthorizedError):
                service.EvaluationService.require_evaluation_owner(42, ctx.identity)
        finally:
            current_tenant_id.reset(token)
    else:
        token = set_current_open_api_principal(service_account_principal())
        try:
            with pytest.raises(UnAuthorizedError):
                service.EvaluationService.require_evaluation_owner(42, ctx.identity)
        finally:
            reset_current_open_api_principal(token)


async def test_background_entry_rechecks_real_owner_before_csv_or_redis(evaluation_context):
    ctx = evaluation_context
    set_values(ctx, user_id=22)
    with pytest.raises(NotFoundError):
        await service.add_evaluation_task(42, login_user=ctx.identity)
    assert row(ctx).status == EvaluationTaskStatus.running.value
    ctx.read_csv.assert_not_called()
    ctx.get_redis.assert_not_called()


def workflow_runtime(context, monkeypatch):
    callbacks = []

    class Callback:
        def __init__(self, unique_id, workflow_id, chat_id, user_id):
            assert user_id == context.identity.user_id
            self.reads = 0
            self.graph = None
            callbacks.append(self)

        def set_workflow_data(self, graph):
            self.graph = deepcopy(graph)

        def set_workflow_status(self, status):
            return None

        def sync_get_response_until_break(self):
            self.reads += 1
            if self.reads == 1:
                yield SimpleNamespace(message={"node_id": "input", "input_schema": {"tab": "dialog_input"}})
            else:
                yield SimpleNamespace(category="output_msg", type="end", message={"msg": "answer"})

        def get_workflow_status(self):
            return {"status": WorkflowStatus.INPUT.value if self.reads == 1 else WorkflowStatus.SUCCESS.value}

        def set_user_input(self, inputs):
            return None

        def set_workflow_stop(self):
            return None

    factory = Mock(side_effect=Callback)
    monkeypatch.setattr(service, "RedisCallback", factory)
    monkeypatch.setattr(service.workflow_stateful_worker, "find_task_node_sync", Mock(return_value="queue"))
    execute = Mock()
    monkeypatch.setattr(service, "execute_workflow", execute)
    monkeypatch.setattr(service, "continue_workflow", Mock())
    return SimpleNamespace(callbacks=callbacks, factory=factory, execute=execute)


async def test_real_wf_owner_core_uses_stored_noncurrent_version_before_every_queue_write(
    evaluation_context, monkeypatch
):
    ctx = evaluation_context
    runtime = workflow_runtime(ctx, monkeypatch)
    prepare = AsyncMock(wraps=service.prepare_saved)
    monkeypatch.setattr(service, "prepare_saved", prepare)
    await service.add_evaluation_task(42, login_user=ctx.identity)
    assert row(ctx).status == EvaluationTaskStatus.success.value
    assert len(runtime.callbacks) == 2 and all(callback.graph == ctx.graph for callback in runtime.callbacks)
    assert prepare.await_count == 3  # pre-CSV plus each of two questions
    for call in prepare.await_args_list:
        assert call.args[0] is ctx.identity and call.args[1] == "wf" and call.kwargs == {"version_id": 2}
    assert runtime.execute.apply_async.call_count == 2
    assert get_current_permission_actor() is ctx.actor


@pytest.mark.parametrize("version", [None, 0])
async def test_missing_stored_version_never_falls_back_to_current(evaluation_context, monkeypatch, version):
    ctx = evaluation_context
    set_values(ctx, version=version)
    runtime = workflow_runtime(ctx, monkeypatch)
    await service.add_evaluation_task(42, login_user=ctx.identity)
    assert row(ctx).status == EvaluationTaskStatus.failed.value
    assert "workflow version info not found" in row(ctx).description
    ctx.read_csv.assert_not_called()
    runtime.factory.assert_not_called()
    ctx.score_llm.assert_not_awaited()


async def test_source_becomes_unready_after_first_question_second_question_never_queues(
    evaluation_context, monkeypatch
):
    ctx = evaluation_context
    runtime = workflow_runtime(ctx, monkeypatch)

    def invalidate(*args, **kwargs):
        with ctx.sync.begin() as connection:
            connection.execute(
                sa.update(BusinessReferenceSet)
                .where(BusinessReferenceSet.source_id == "wf", BusinessReferenceSet.source_version == "2")
                .values(ready=False)
            )

    runtime.execute.apply_async.side_effect = invalidate
    await service.add_evaluation_task(42, login_user=ctx.identity)
    failed = row(ctx)
    assert failed.status == EvaluationTaskStatus.failed.value
    assert failed.result_score == {"old": "kept"} and failed.result_file_path == "old.csv"
    assert runtime.execute.apply_async.call_count == 1 and len(runtime.callbacks) == 1
    ctx.score_llm.assert_not_awaited()
    ctx.redis.delete.assert_called_once()


async def test_initial_bad_source_fails_before_csv_redis_provider_or_queue(evaluation_context, monkeypatch):
    ctx = evaluation_context
    runtime = workflow_runtime(ctx, monkeypatch)
    with ctx.sync.begin() as connection:
        connection.execute(
            sa.update(BusinessReferenceSet).where(BusinessReferenceSet.source_version == "2").values(ready=False)
        )
    await service.add_evaluation_task(42, login_user=ctx.identity)
    assert row(ctx).status == EvaluationTaskStatus.failed.value
    ctx.read_csv.assert_not_called()
    ctx.get_redis.assert_not_called()
    runtime.factory.assert_not_called()
    runtime.execute.apply_async.assert_not_called()
    ctx.score_llm.assert_not_awaited()


async def test_assistant_original_jwt_identity_enters_agent_and_every_run(evaluation_context, monkeypatch):
    ctx = evaluation_context
    set_values(ctx, exec_type="assistant", unique_id="assistant-a", version=None)
    monkeypatch.setattr(
        service.AssistantDao, "aget_one_assistant", AsyncMock(return_value=SimpleNamespace(id="assistant-a"))
    )
    seen = []

    class Agent:
        def __init__(self, assistant_info, chat_id, invoke_user_id, *, login_user):
            assert login_user is ctx.identity and invoke_user_id == ctx.identity.user_id
            assert get_current_permission_actor() is ctx.actor

        async def init_assistant(self):
            seen.append("init")

        async def run(self, question):
            seen.append(question)
            return [SimpleNamespace(content="answer")]

    monkeypatch.setattr(service, "AssistantAgent", Agent)
    await service.add_evaluation_task(42, login_user=ctx.identity)
    assert seen == ["init", "first", "second"] and row(ctx).status == EvaluationTaskStatus.success.value


@pytest.fixture
async def web_session_user(evaluation_context, monkeypatch):
    """Use the actual HTTP JWT dependency's credential-reference construction."""
    import jwt

    user = evaluation_context.identity
    secret = "test-only-evaluation-signing-key-32-bytes"
    claims = {
        "user_id": user.user_id,
        "user_name": user.user_name,
        "tenant_id": user.tenant_id,
        "token_version": user.token_version,
        "exp": 4070908800,
        "iss": "evaluation-test",
    }
    token = jwt.encode(claims, secret, algorithm="HS256")
    auth = SimpleNamespace(
        get_subject=lambda: claims,
        req=SimpleNamespace(cookies={"access": token}),
        _access_cookie_key="access",
        jwt_secret=secret,
        cookie_conf=SimpleNamespace(jwt_iss="evaluation-test"),
        _decode_algorithms=["HS256"],
    )
    monkeypatch.setattr(UserPayload, "init_login_user", AsyncMock(return_value=user))
    original = await UserPayload.get_login_user(auth)
    assert original is user and original._runtime_credential_reference["kind"] == "web_session"
    return original


def test_real_http_jwt_reference_is_accepted_before_scheduling_and_preserved(evaluation_context, web_session_user):
    ctx = evaluation_context
    reference = web_session_user._runtime_credential_reference
    tasks = BackgroundTasks()
    endpoint.process_evaluation(evaluation_id=42, background_tasks=tasks, login_user=web_session_user)
    assert tasks.tasks[0].kwargs["login_user"] is web_session_user
    assert web_session_user._runtime_credential_reference is reference
    create = BackgroundTasks()
    upload = UploadFile(file=BytesIO(b"question,ground_truth\nfirst,one\n"), filename="dataset.csv")
    result = endpoint.create_evaluation(
        file=upload,
        prompt="",
        exec_type="workflow",
        unique_id="wf",
        version=2,
        background_tasks=create,
        login_user=web_session_user,
    )
    assert create.tasks[0].kwargs["login_user"] is web_session_user
    assert service.EvaluationService.require_evaluation_owner(result.data.id, web_session_user).tenant_id == 101
    assert not ctx.get_redis.called


async def test_real_http_jwt_reference_reaches_background_and_actual_source_scope(
    evaluation_context, web_session_user, monkeypatch
):
    runtime = workflow_runtime(evaluation_context, monkeypatch)
    await service.add_evaluation_task(42, login_user=web_session_user)
    assert row(evaluation_context).status == EvaluationTaskStatus.success.value
    assert runtime.execute.apply_async.call_count == 2


def test_web_session_home_tenant_differs_from_trusted_management_pin(evaluation_context, web_session_user):
    home = web_session_user.tenant_id
    reference = web_session_user._runtime_credential_reference
    web_session_user.tenant_id = 1
    reference["tenant_id"] = 1
    try:
        owned = service.EvaluationService.require_evaluation_owner(42, web_session_user)
        assert owned.tenant_id == 101 and web_session_user.tenant_id == 1
        assert reference["tenant_id"] == 1
    finally:
        web_session_user.tenant_id = home
        reference["tenant_id"] = home


@pytest.mark.parametrize(
    "reference",
    [
        {"kind": "service_account", "user_id": 11, "tenant_id": 101, "token_version": 0},
        {"kind": "open_api", "user_id": 11, "tenant_id": 101, "token_version": 0},
        {"kind": "web_session", "user_id": 22, "tenant_id": 101, "token_version": 0},
        {"kind": "web_session", "user_id": 11, "tenant_id": 202, "token_version": 0},
        {"kind": "web_session", "user_id": 11, "tenant_id": 101, "token_version": 99},
        {"kind": "web_session"},
    ],
)
def test_nonweb_or_mismatched_credential_reference_cannot_become_jwt(evaluation_context, reference):
    user = evaluation_context.identity
    user._runtime_credential_reference = reference
    with pytest.raises(UnAuthorizedError):
        service.EvaluationService.require_evaluation_owner(42, user)
