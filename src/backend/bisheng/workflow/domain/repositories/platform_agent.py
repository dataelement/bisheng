"""平台 Agent 的发布事务、运行快照和发送栅栏。远端调用不得进入这些事务。"""

import time
from contextlib import contextmanager
from copy import deepcopy
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import select

from bisheng.common.errcode.flow import (
    PlatformAgentEnvironmentError,
    PlatformAgentExecutionError,
    PlatformAgentPublicationError,
    PlatformAgentUnknownError,
    WorkFlowOnlineEditError,
)
from bisheng.core.database import get_sync_db_session
from bisheng.core.database.tenant_filter import build_tenant_filter_clause
from bisheng.database.models.flow import Flow, FlowStatus
from bisheng.database.models.flow_version import FlowVersion
from bisheng.workflow.domain.models.platform_agent_execution import PlatformAgentExecution, utc_now
from bisheng.workflow.domain.repositories.platform_node_publication import PlatformNodePublication
from bisheng.workflow.domain.schemas.platform_agent import AgentDispatch, canonical_digest, uses_agent_interaction

REMOTE_TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED", "START_REJECTED"}
LOCAL_TERMINAL = {"SUCCEEDED", "FAILED", "STOPPED", "TIMED_OUT"}
LONG_CANCEL_WINDOW = 15
LONG_SUMMARY_WINDOW = 24 * 60 * 60
INTERACTION_WAIT_WINDOW = 120
INTERACTION_SUBMIT_WINDOW = 30
INTERACTION_RESULT_WINDOW = 30
INTERACTION_RECONCILE_INTERVAL = 1
LONG_RESUME_RECHECK_INTERVAL = 1
LONG_RESUME_POLL_LEASE = 10
LONG_RESUME_EXECUTION_LEASE = 10


class PlatformAgentRepository(PlatformNodePublication):
    def __init__(self, sessions=get_sync_db_session, *, clock=time.time):
        self.sessions = sessions
        self.clock = clock

    @contextmanager
    def transaction(self):
        try:
            with self.sessions() as session:
                try:
                    yield session
                    session.commit()
                except BaseException:
                    session.rollback()
                    raise
        except SQLAlchemyError:
            # SQL 参数和驱动异常不得进入节点事件。
            raise PlatformAgentExecutionError() from None

    @staticmethod
    def _flow(session, flow_id, *, lock=False):
        statement = select(Flow).where(Flow.id == flow_id)
        flow = session.exec(statement.with_for_update() if lock else statement).first()
        if flow is None:
            raise PlatformAgentPublicationError()
        return flow

    @staticmethod
    def _version(session, version_id, *, lock=False):
        statement = select(FlowVersion).where(FlowVersion.id == version_id, FlowVersion.is_delete == 0)
        version = session.exec(statement.with_for_update() if lock else statement).first()
        if version is None:
            raise PlatformAgentPublicationError()
        return version

    def get_workflow(self, flow_id):
        with self.transaction() as session:
            return deepcopy(self._flow(session, flow_id).model_dump())

    def get_version(self, version_id):
        with self.transaction() as session:
            version = self._version(session, version_id)
            self._flow(session, version.flow_id)
            return deepcopy(version.model_dump())

    def save_version(self, version_id, *, data=None, name=None, description=None, allow_online=False):
        parent = self.get_version(version_id)["flow_id"]
        with self.transaction() as session:
            flow = self._flow(session, parent, lock=True)
            version = self._version(session, version_id, lock=True)
            if data is not None:
                if flow.status == FlowStatus.ONLINE.value and version.is_current and not allow_online:
                    raise WorkFlowOnlineEditError()
                version.data = self.candidate_graph(data)
            if name is not None:
                version.name = name
            if description is not None:
                version.description = description
            session.add(version)
            return deepcopy(version.model_dump())

    def change_version(self, flow_id, version_id):
        with self.transaction() as session:
            flow = self._flow(session, flow_id, lock=True)
            version = self._version(session, version_id, lock=True)
            if flow.status == FlowStatus.ONLINE.value:
                raise WorkFlowOnlineEditError()
            if version.flow_id != flow_id:
                raise PlatformAgentPublicationError()
            for item in session.exec(select(FlowVersion).where(FlowVersion.flow_id == flow_id)).all():
                item.is_current = int(item.id == version_id)
                session.add(item)

    def delete_version(self, version_id):
        parent = self.get_version(version_id)["flow_id"]
        with self.transaction() as session:
            self._flow(session, parent, lock=True)
            version = self._version(session, version_id, lock=True)
            if version.is_current:
                raise PlatformAgentPublicationError()
            version.is_delete = 1
            session.add(version)

    @staticmethod
    def environment(config):
        return canonical_digest(config.model_dump())

    def prepare_execution(
        self, flow_id, session_id, actor, graph, config, entry_kind, *, browser_origin=None, long_task_resume=False
    ):
        with self.transaction() as session:
            flow = self._flow(session, flow_id, lock=True)
            if flow.tenant_id != actor.tenant_id:
                raise PlatformAgentExecutionError()
            if entry_kind != "DEBUG" and flow.status != FlowStatus.ONLINE.value:
                raise PlatformAgentExecutionError()
            graph_digest = canonical_digest(graph)
            start = {"state": "ACCEPTED", "kind": "START"}
            if long_task_resume:
                start["long_task_resume"] = True
            if long_task_resume or uses_agent_interaction(graph):
                versions = session.exec(
                    select(FlowVersion).where(
                        FlowVersion.flow_id == flow_id, FlowVersion.is_current == 1, FlowVersion.is_delete == 0
                    )
                ).all()
                if (
                    entry_kind != "PUBLISHED"
                    or not session_id
                    or len(versions) != 1
                    or canonical_digest(versions[0].data) != graph_digest
                    or canonical_digest(flow.data) != graph_digest
                ):
                    raise PlatformAgentPublicationError()
                start["workflow_version_id"] = versions[0].id
            active = session.exec(
                select(PlatformAgentExecution).where(
                    PlatformAgentExecution.workflow_id == flow_id,
                    PlatformAgentExecution.session_id == session_id,
                    PlatformAgentExecution.state.in_(["READY", "RUNNING", "WAITING"]),
                )
            ).first()
            if active:
                if active.actor_reference.get("environment") != self.environment(config):
                    raise PlatformAgentEnvironmentError()
                if active.user_id != actor.user_id or active.graph_digest != graph_digest:
                    raise PlatformAgentExecutionError()
                if browser_origin is not None and active.actor_reference.get("browser_origin") != browser_origin:
                    raise PlatformAgentExecutionError()
                if active.state != "READY":
                    raise PlatformAgentExecutionError()
                if len(active.dispatches) != 1:
                    raise PlatformAgentExecutionError()
                dispatch_id = next(iter(active.dispatches))
                existing = active.dispatches[dispatch_id]
                if any(existing.get(field) != start.get(field) for field in ("workflow_version_id", "long_task_resume")):
                    raise PlatformAgentExecutionError()
                return deepcopy(active.model_dump()), dispatch_id
            dispatch_id = uuid4().hex
            execution = PlatformAgentExecution(
                execution_id=uuid4().hex,
                workflow_id=flow_id,
                session_id=session_id,
                user_id=actor.user_id,
                tenant_id=actor.tenant_id,
                entry_kind=entry_kind,
                provider_mode=config.mode,
                connection_id=config.connection_id,
                policy_revision=config.policy_revision,
                graph_digest=graph_digest,
                graph_snapshot=deepcopy(graph),
                actor_reference={
                    "environment": self.environment(config),
                    "token_version": actor.token_version,
                    **({"browser_origin": browser_origin} if browser_origin is not None else {}),
                },
                dispatches={dispatch_id: start},
            )
            session.add(execution)
            session.flush()
            return deepcopy(execution.model_dump()), dispatch_id

    @staticmethod
    def _execution(session, execution_id):
        row = session.exec(
            select(PlatformAgentExecution).where(PlatformAgentExecution.execution_id == execution_id).with_for_update()
        ).first()
        if row is None:
            raise PlatformAgentExecutionError()
        return row

    def get_execution(self, execution_id):
        with self.transaction() as session:
            return deepcopy(self._execution(session, execution_id).model_dump())

    @contextmanager
    def admission_scope(self, execution_id):
        workflow_id = self.get_execution(execution_id)["workflow_id"]
        with self.transaction() as session:
            self._flow(session, workflow_id, lock=True)
            row = self._execution(session, execution_id)
            if row.state != "READY" or row.stop_requested:
                raise PlatformAgentExecutionError()
            yield

    def find_session_execution(self, flow_id, session_id):
        with self.transaction() as session:
            row = session.exec(
                select(PlatformAgentExecution)
                .where(
                    PlatformAgentExecution.workflow_id == flow_id,
                    PlatformAgentExecution.session_id == session_id,
                )
                .order_by(PlatformAgentExecution.create_time.desc(), PlatformAgentExecution.execution_id.desc())
                .limit(1)
            ).first()
            return deepcopy(row.model_dump()) if row else None

    def find_active_session_execution(self, flow_id, session_id):
        with self.transaction() as session:
            rows = session.exec(
                select(PlatformAgentExecution)
                .where(
                    PlatformAgentExecution.workflow_id == flow_id,
                    PlatformAgentExecution.session_id == session_id,
                    PlatformAgentExecution.state.in_(["READY", "RUNNING", "WAITING"]),
                )
                .limit(2)
            ).all()
            if len(rows) > 1:
                raise PlatformAgentExecutionError()
            return deepcopy(rows[0].model_dump()) if rows else None

    @contextmanager
    def interaction_reference_scope(self, execution_id):
        with self.transaction() as session:
            row = self._execution(session, execution_id)
            yield row.state in {"READY", "RUNNING", "WAITING"} and not row.stop_requested

    def claim_dispatch(self, execution_id, dispatch_id):
        with self.transaction() as session:
            row = self._execution(session, execution_id)
            dispatches = deepcopy(row.dispatches)
            item = dispatches.get(dispatch_id)
            if (
                row.stop_requested or row.state not in {"READY", "WAITING"}
                or not item or item["state"] != "ACCEPTED" or item["kind"] == "LONG_TASK_RESUME"
            ):
                return None
            if item["kind"] == "INTERACTION_RESUME":
                calls = deepcopy(row.calls)
                call = calls.get(item["call_key"], {})
                task = call.get("long_task", {})
                interaction = task.get("interaction", {})
                if (
                    row.state != "WAITING"
                    or call.get("state") != "DISPATCHING"
                    or task.get("local_state") != "WAITING_RESULT"
                    or interaction.get("phase") != "SUBMIT_QUEUED"
                    or interaction.get("interaction_id") != item["interaction_id"]
                    or interaction.get("dispatch_id") != dispatch_id
                ):
                    return None
                now = self.clock()
                if now >= call["deadline"]:
                    self._timeout_long(call, now)
                    item["state"] = "DONE"
                    row.dispatches = dispatches
                    row.calls = calls
                    row.state = "FAILED"
                    return None
                call["dispatch_id"] = dispatch_id
                row.calls = calls
            owner = uuid4().hex
            item.update(state="CLAIMED", owner=owner)
            row.dispatches = dispatches
            row.state = "RUNNING"
            row.update_time = utc_now()
            session.add(row)
            return AgentDispatch(execution_id, dispatch_id, owner)

    @staticmethod
    def _owned(row, dispatch):
        item = row.dispatches.get(dispatch.dispatch_id, {})
        if (
            row.stop_requested
            or row.state != "RUNNING"
            or item.get("owner") != dispatch.owner
            or item.get("state") != "CLAIMED"
        ):
            raise PlatformAgentExecutionError()

    def reserve_call(self, dispatch, node_id, ordinal, request_digest, ref, deadline):
        with self.transaction() as session:
            row = self._execution(session, dispatch.execution_id)
            self._owned(row, dispatch)
            key = f"{node_id}:{ordinal}"
            if key in row.calls or deadline <= self.clock():
                raise PlatformAgentExecutionError()
            calls = deepcopy(row.calls)
            calls[key] = {
                "state": "DISPATCHING",
                "digest": request_digest,
                "ref": ref,
                "deadline": deadline,
                "dispatch_id": dispatch.dispatch_id,
            }
            row.calls = calls
            session.add(row)

    def reserve_long_call(self, dispatch, key, digest, ref, started, start_deadline, deadline, *, resume_checkpoint=None):
        with self.transaction() as session:
            row = self._execution(session, dispatch.execution_id)
            self._owned(row, dispatch)
            if key in row.calls or row.provider_mode != "mock":
                raise PlatformAgentExecutionError()
            extra = {}
            if resume_checkpoint is not None:
                entry = row.dispatches[dispatch.dispatch_id]
                if (
                    entry.get("long_task_resume") is not True
                    or resume_checkpoint.get("execution_id") != row.execution_id
                    or resume_checkpoint.get("workflow_version_id") != entry.get("workflow_version_id")
                    or resume_checkpoint.get("graph_digest") != row.graph_digest
                    or f"{resume_checkpoint.get('agent_node')}:0" != key
                ):
                    raise PlatformAgentExecutionError()
                extra["resume"] = {"format": 1, "phase": "STARTING", "snapshot": resume_checkpoint}
            row.calls = {
                **row.calls,
                key: {
                    "state": "DISPATCHING",
                    "digest": digest,
                    "ref": ref,
                    "deadline": deadline,
                    "dispatch_id": dispatch.dispatch_id,
                    "long_task": {
                        "format": 1,
                        "sequence": len(row.calls) + 1,
                        "local_state": "PREPARED",
                        "remote_state": "NOT_SENT",
                        "cancel_state": "NONE",
                        "started": started,
                        "start_deadline": start_deadline,
                        **extra,
                    },
                },
            }

    def save_long_task_resume_wait(self, dispatch, key, observation):
        with self._long_scope(dispatch.execution_id, key, dispatch) as (row, call, task, now):
            self._owned(row, dispatch)
            if now >= call["deadline"]:
                raise TimeoutError()
            resume = task.get("resume")
            if not resume or resume["phase"] != "STARTING" or task["remote_state"] != "START_IN_FLIGHT":
                raise PlatformAgentExecutionError()
            if observation is None:
                task["remote_state"] = "START_UNKNOWN"
                resume["phase"] = "START_CHECK"
            else:
                if observation.ref.model_dump() != call["ref"]:
                    raise PlatformAgentExecutionError()
                call["agent_run_id"] = observation.run_id
                task["remote_state"] = observation.status
                if observation.progress is not None:
                    task["progress"] = observation.progress
                resume["phase"] = "POLL_WAIT"
            resume["next_check"] = now
            self._finish_long_dispatch(row, dispatch.dispatch_id)
            row.state = "WAITING"

    @staticmethod
    def _finish_long_dispatch(row, dispatch_id):
        row.dispatches = {**row.dispatches, dispatch_id: {**row.dispatches[dispatch_id], "state": "DONE"}}

    @staticmethod
    def _long_resume_active(row, task):
        return (
            not row.stop_requested
            and row.state in {"RUNNING", "WAITING"}
            and task["local_state"] not in LOCAL_TERMINAL
        )

    @classmethod
    def _long_resume_poll_due(cls, row, call, task, resume, now):
        if not resume or not cls._long_resume_active(row, task):
            return False
        if now >= call["deadline"]:
            return True
        if resume["phase"] == "STARTING":
            return now >= task["start_deadline"]
        return resume["phase"] in {"START_CHECK", "POLL_WAIT"} and now >= max(
            resume.get("next_check", 0), resume.get("lease_until", 0)
        )

    @classmethod
    def _long_resume_delivery_due(cls, row, call, task, resume, now):
        if (
            not resume
            or not cls._long_resume_active(row, task)
            or resume["phase"] not in {"RESUME_READY", "RESUMING"}
            or not resume.get("next_dispatch_at", 0) <= now < call["deadline"]
        ):
            return False
        item = row.dispatches.get(resume.get("dispatch_id"), {})
        return item.get("kind") == "LONG_TASK_RESUME" and (
            item.get("state") == "ACCEPTED"
            or (item.get("state") == "CLAIMED" and now >= item.get("lease_until", float("inf")))
        )

    def _finish_long_resume(self, row, call, resume, now, error=None):
        if error is None:
            self._timeout_long(call, now)
        else:
            self._end_long(call, now, "FAILED", error)
        self._seal_long_resume(row, call, resume)
        row.state = "FAILED"

    def _seal_long_resume(self, row, call, resume):
        if resume["phase"] == "TERMINAL":
            return
        self._finish_long_dispatch(row, resume.get("dispatch_id", call["dispatch_id"]))
        resume.clear()
        resume.update(format=1, phase="TERMINAL")

    @staticmethod
    def _version_long_resume(previous, call):
        task = call.get("long_task", {})
        resume = task.get("resume")
        if resume is None:
            return
        prior_task = previous.get("long_task", {})
        prior = prior_task.get("resume", {})
        changed = (
            prior.get("phase") != resume.get("phase")
            or previous.get("agent_run_id") != call.get("agent_run_id")
            or any(prior_task.get(field) != task.get(field) for field in (
                "local_state", "remote_state", "cancel_state", "reason", "progress"
            ))
        )
        resume["status_version"] = prior.get("status_version", 1) + int(changed)

    def claim_long_task_resume_poll(self, execution_id, key, tenant_id):
        with self._long_scope(execution_id, key) as (row, call, task, now):
            if row.tenant_id != tenant_id or row.provider_mode != "mock":
                raise PlatformAgentExecutionError()
            resume = task.get("resume")
            if not self._long_resume_poll_due(row, call, task, resume, now):
                return None
            if now >= call["deadline"]:
                self._finish_long_resume(row, call, resume, now)
                return None
            if resume["phase"] == "STARTING":
                if task["remote_state"] != "START_IN_FLIGHT":
                    error = "REMOTE_FAILED" if task["remote_state"] == "START_REJECTED" else None
                    self._finish_long_resume(row, call, resume, now, error)
                    return None
                self._finish_long_dispatch(row, call["dispatch_id"])
                row.state = "WAITING"
                task["remote_state"] = "START_UNKNOWN"
                resume["phase"] = "START_CHECK"
            lease = uuid4().hex
            until = min(now + LONG_RESUME_POLL_LEASE, call["deadline"])
            resume.update(lease=lease, lease_until=until)
            return lease, until

    def finish_long_task_resume_poll(self, execution_id, key, lease, *, observation=None, result=None, error=None):
        with self._long_scope(execution_id, key) as (row, call, task, now):
            resume = task.get("resume", {})
            if not self._long_resume_active(row, task) or not self._valid_long_lease(resume, lease, now):
                return False
            if observation is not None:
                if observation.ref.model_dump() != call["ref"] or call.get("agent_run_id") not in (
                    None, observation.run_id
                ):
                    error = "INVALID_OUTPUT"
                elif task["remote_state"] not in REMOTE_TERMINAL:
                    call["agent_run_id"] = observation.run_id
                    if task["remote_state"] != "RUNNING" or observation.status != "QUEUED":
                        task["remote_state"] = observation.status
                    if observation.progress is not None:
                        task["progress"] = max(task.get("progress", 0), observation.progress)
                    resume["phase"] = "POLL_WAIT"
            error = error or {
                "WAITING_INPUT": "UNSUPPORTED_INPUT",
                "FAILED": "REMOTE_FAILED",
                "CANCELLED": "REMOTE_CANCELLED",
            }.get(task["remote_state"])
            if result is not None and (
                task["remote_state"] != "SUCCEEDED"
                or result.agent_run_id != call.get("agent_run_id")
                or result.ref.model_dump() != call["ref"]
                or result.status != "SUCCEEDED"
            ):
                error = "INVALID_OUTPUT"
            if error:
                self._finish_long_resume(row, call, resume, now, error)
                return True
            resume.pop("lease", None)
            resume.pop("lease_until", None)
            resume["next_check"] = now + LONG_RESUME_RECHECK_INTERVAL
            if result is not None:
                dispatch_id = uuid4().hex
                row.dispatches = {
                    **row.dispatches,
                    dispatch_id: {"kind": "LONG_TASK_RESUME", "state": "ACCEPTED", "call_key": key},
                }
                resume.update(phase="RESUME_READY", result=deepcopy(result.output), dispatch_id=dispatch_id)
            return True

    def claim_long_task_resume_redelivery(self, execution_id, key, tenant_id):
        with self._long_scope(execution_id, key) as (row, call, task, now):
            if row.tenant_id != tenant_id or row.provider_mode != "mock":
                raise PlatformAgentExecutionError()
            resume = task.get("resume")
            if not self._long_resume_delivery_due(row, call, task, resume, now):
                return None
            resume["next_dispatch_at"] = now + LONG_RESUME_RECHECK_INTERVAL
            return resume["dispatch_id"]

    def claim_long_task_resume_dispatch(self, execution_id, key, dispatch_id, tenant_id):
        with self._long_scope(execution_id, key) as (row, call, task, now):
            if row.tenant_id != tenant_id or row.provider_mode != "mock" or row.entry_kind != "PUBLISHED":
                raise PlatformAgentExecutionError()
            resume = task.get("resume", {})
            item = row.dispatches.get(dispatch_id, {})
            if item.get("kind") != "LONG_TASK_RESUME" or item.get("call_key") != key:
                raise PlatformAgentExecutionError()
            if resume.get("dispatch_id") != dispatch_id or not self._long_resume_active(row, task):
                return None
            if now >= call["deadline"]:
                self._finish_long_resume(row, call, resume, now)
                return None
            first_claim = row.state == "WAITING" and resume["phase"] == "RESUME_READY" and item["state"] == "ACCEPTED"
            takeover = (
                row.state == "RUNNING" and resume["phase"] == "RESUMING" and item["state"] == "CLAIMED"
                and now >= item.get("lease_until", float("inf"))
            )
            if not (first_claim or takeover):
                return None
            owner = uuid4().hex
            lease_until = min(now + LONG_RESUME_EXECUTION_LEASE, call["deadline"])
            row.dispatches = {**row.dispatches, dispatch_id: {**item, "state": "CLAIMED", "owner": owner,
                                                              "lease_until": lease_until}}
            row.state = "RUNNING"
            call["dispatch_id"] = dispatch_id
            resume["phase"] = "RESUMING"
            return AgentDispatch(execution_id, dispatch_id, owner)

    @staticmethod
    def _owns_long_task_resume(row, call, resume, dispatch, now):
        item = row.dispatches.get(dispatch.dispatch_id, {})
        return (
            not row.stop_requested and row.state == "RUNNING" and call["state"] == "DISPATCHING"
            and resume.get("phase") == "RESUMING" and resume.get("dispatch_id") == dispatch.dispatch_id
            and item.get("kind") == "LONG_TASK_RESUME" and item.get("state") == "CLAIMED"
            and item.get("owner") == dispatch.owner and now < min(item.get("lease_until", 0), call["deadline"])
        )

    def fail_long_task_resume(self, dispatch, key, reason):
        with self._long_scope(dispatch.execution_id, key) as (row, call, task, now):
            resume = task.get("resume", {})
            if not self._owns_long_task_resume(row, call, resume, dispatch, now):
                return False
            self._finish_long_resume(row, call, resume, now, reason)
            return True

    def commit_long_task_resume_output(self, dispatch, key, write_output):
        with self.transaction() as session:
            row = self._execution(session, dispatch.execution_id)
            calls = deepcopy(row.calls)
            call = calls[key]
            task = call["long_task"]
            resume = task["resume"]
            if not self._owns_long_task_resume(row, call, resume, dispatch, self.clock()):
                raise PlatformAgentExecutionError()
            message_id = write_output(session)
            now = self.clock()
            if not self._owns_long_task_resume(row, call, resume, dispatch, now):
                raise PlatformAgentExecutionError()
            call["state"] = "SUCCEEDED"
            task.update(local_state="SUCCEEDED", retain_until=now + LONG_SUMMARY_WINDOW)
            task["resume"] = {"format": 1, "phase": "TERMINAL", "message_id": message_id,
                              "dispatch_id": dispatch.dispatch_id}
            self._version_long_resume(row.calls[key], call)
            self._finish_long_dispatch(row, dispatch.dispatch_id)
            row.calls = calls
            row.state = "SUCCEEDED"
            session.add(row)
            return message_id

    @contextmanager
    def _long_scope(self, execution_id, key, dispatch=None):
        with self.transaction() as session:
            row = self._execution(session, execution_id)
            calls = deepcopy(row.calls)
            call = calls.get(key)
            if not call or call.get("long_task", {}).get("format") != 1:
                raise PlatformAgentExecutionError()
            if dispatch and (
                call["dispatch_id"] != dispatch.dispatch_id
                or row.dispatches.get(dispatch.dispatch_id, {}).get("owner") != dispatch.owner
            ):
                raise PlatformAgentExecutionError()
            yield row, call, call["long_task"], self.clock()
            if calls != row.calls:
                self._version_long_resume(row.calls[key], call)
                row.calls = calls
                session.add(row)

    def permit_long_start(self, dispatch, key):
        with self._long_scope(dispatch.execution_id, key, dispatch) as (row, _, task, now):
            self._owned(row, dispatch)
            if task["remote_state"] != "NOT_SENT" or now >= task["start_deadline"]:
                return False
            task.update(remote_state="START_IN_FLIGHT", local_state="WAITING_RESULT")
            return True

    def long_snapshot(self, execution_id, key):
        with self._long_scope(execution_id, key) as (row, call, task, _):
            return {
                "user_id": row.user_id,
                "tenant_id": row.tenant_id,
                "workflow_id": row.workflow_id,
                "entry_kind": row.entry_kind,
                "actor_reference": deepcopy(row.actor_reference),
                "connection_id": row.connection_id,
                "ref": deepcopy(call["ref"]),
                "deadline": call["deadline"],
                "run_id": call.get("agent_run_id"),
                **deepcopy(task),
            }

    def observe_long(self, execution_id, key, *, dispatch=None, lease=None, observation=None, remote_state=None):
        with self._long_scope(execution_id, key, dispatch) as (row, call, task, now):
            if lease is not None and not self._valid_long_lease(task, lease, now):
                return False
            if dispatch is not None and (task.get("interaction") or task.get("resume")):
                self._owned(row, dispatch)
                if now >= call["deadline"]:
                    raise TimeoutError()
            if task["local_state"] in LOCAL_TERMINAL and now >= task.get("reconcile_until", 0):
                return False
            if observation is not None:
                if observation.ref.model_dump() != call["ref"] or call.get("agent_run_id") not in (
                    None,
                    observation.run_id,
                ):
                    raise PlatformAgentExecutionError()
                remote_state = observation.status
            previous = task["remote_state"]
            if previous in REMOTE_TERMINAL or (previous == "RUNNING" and remote_state == "QUEUED"):
                return False
            if call.get("agent_run_id") and observation is None:
                return False
            if observation is not None:
                call["agent_run_id"] = observation.run_id
            task["remote_state"] = remote_state
            if observation is not None and observation.progress is not None:
                task["progress"] = max(task.get("progress", 0), observation.progress)
            if remote_state == "CANCELLED" and task["cancel_state"] in {"SENT", "ACCEPTED"}:
                task["cancel_state"] = "CONFIRMED"
            return True

    def ready_long_output(self, dispatch, key):
        with self._long_scope(dispatch.execution_id, key, dispatch) as (row, call, task, now):
            self._owned(row, dispatch)
            if task["local_state"] != "WAITING_RESULT" or task["remote_state"] != "SUCCEEDED":
                raise PlatformAgentExecutionError()
            if now < call["deadline"]:
                task["result_ready"] = True
                return
            self._timeout_long(call, now)
        raise TimeoutError()

    def save_long_wait(self, dispatch, key, observation, snapshot):
        with self._long_scope(dispatch.execution_id, key, dispatch) as (row, call, task, now):
            self._owned(row, dispatch)
            if now >= call["deadline"]:
                raise TimeoutError()
            active = row.dispatches[dispatch.dispatch_id]
            if (
                active.get("kind") != "START"
                or active.get("workflow_version_id") is None
                or task["local_state"] != "WAITING_RESULT"
                or task["remote_state"] in REMOTE_TERMINAL | {"WAITING_INPUT"}
                or observation.status != "WAITING_INPUT"
                or observation.interaction is None
                or observation.ref.model_dump() != call["ref"]
                or call.get("agent_run_id") not in (None, observation.run_id)
                or snapshot.get("execution_id") != row.execution_id
                or snapshot.get("workflow_version_id") != active["workflow_version_id"]
                or snapshot.get("graph_digest") != row.graph_digest
                or f"{snapshot.get('agent_node')}:0" != key
            ):
                raise PlatformAgentExecutionError()
            call["agent_run_id"] = observation.run_id
            call["deadline"] = now + INTERACTION_WAIT_WINDOW
            task["remote_state"] = "WAITING_INPUT"
            task["interaction"] = {
                "format": 1,
                "phase": "WAITING_INPUT",
                "interaction_id": uuid4().hex,
                "status_version": 1,
                "expires_at": call["deadline"],
                "form": observation.interaction.model_dump(),
                "snapshot": snapshot,
            }
            dispatches = deepcopy(row.dispatches)
            dispatches[dispatch.dispatch_id]["state"] = "DONE"
            row.dispatches = dispatches
            row.state = "WAITING"

    def accept_interaction_answer(self, execution_id, key, actor, interaction_id, revision, submission_id, answer):
        with self._long_scope(execution_id, key) as (row, call, task, now):
            interaction = task.get("interaction")
            if (
                row.provider_mode != "mock"
                or (row.user_id, row.tenant_id) != (actor.user_id, actor.tenant_id)
                or row.actor_reference.get("token_version") != actor.token_version
                or not interaction
                or interaction["interaction_id"] != interaction_id
                or interaction.get("remote_interaction", interaction.get("form", {})).get("revision") != revision
                or not isinstance(submission_id, str)
                or not submission_id.strip()
                or len(submission_id) > 128
                or not isinstance(answer, str)
                or not answer.strip()
                or len(answer) > 2000
            ):
                raise PlatformAgentExecutionError()
            submission_digest = canonical_digest(submission_id)
            answer_digest = canonical_digest(answer)
            if "submission_digest" in interaction:
                if (
                    (interaction["submission_digest"], interaction["answer_digest"]) !=
                    (submission_digest, answer_digest)
                    or now >= task.get("retain_until", float("inf"))
                ):
                    raise PlatformAgentExecutionError()
            else:
                if (
                    row.stop_requested
                    or row.state != "WAITING"
                    or task["local_state"] != "WAITING_RESULT"
                    or interaction["phase"] != "WAITING_INPUT"
                    or len(answer) > interaction["form"]["max_length"]
                    or now >= call["deadline"]
                ):
                    raise PlatformAgentExecutionError()
                dispatch_id = uuid4().hex
                remote_key = canonical_digest([execution_id, key, interaction["form"]["interaction_id"], revision])
                call["deadline"] = now + INTERACTION_SUBMIT_WINDOW
                self._interaction_phase(interaction, "SUBMIT_QUEUED")
                interaction.update(
                    dispatch_id=dispatch_id,
                    submission_digest=submission_digest,
                    answer_digest=answer_digest,
                    remote_key=remote_key,
                    answer=answer,
                    expires_at=call["deadline"],
                )
                row.dispatches = {
                    **row.dispatches,
                    dispatch_id: {
                        "state": "ACCEPTED",
                        "kind": "INTERACTION_RESUME",
                        "call_key": key,
                        "interaction_id": interaction_id,
                    },
                }
            return {field: interaction[field] for field in ("dispatch_id", "phase", "status_version", "expires_at")}

    @staticmethod
    def _interaction_phase(interaction, phase):
        interaction["phase"] = phase
        interaction["status_version"] += 1

    def permit_interaction_submit(self, dispatch, key, *, replay=False):
        with self._long_scope(dispatch.execution_id, key, dispatch) as (row, call, task, now):
            self._owned(row, dispatch)
            if now >= call["deadline"]:
                raise TimeoutError()
            interaction = task.get("interaction", {})
            if task["local_state"] != "WAITING_RESULT":
                raise PlatformAgentExecutionError()
            if replay:
                if interaction.get("phase") != "SUBMIT_UNKNOWN" or interaction.get("replayed"):
                    raise PlatformAgentExecutionError()
                interaction["replayed"] = True
            elif interaction.get("phase") == "SUBMIT_QUEUED":
                self._interaction_phase(interaction, "SUBMIT_IN_FLIGHT")
                interaction["next_receipt_check"] = None
            else:
                raise PlatformAgentExecutionError()

    def mark_interaction_unknown(self, dispatch, key):
        with self._long_scope(dispatch.execution_id, key, dispatch) as (row, _, task, _):
            self._owned(row, dispatch)
            interaction = task["interaction"]
            if interaction["phase"] == "SUBMIT_IN_FLIGHT":
                self._interaction_phase(interaction, "SUBMIT_UNKNOWN")

    def confirm_interaction_handoff(self, dispatch, key):
        with self._long_scope(dispatch.execution_id, key, dispatch) as (row, call, task, now):
            self._owned(row, dispatch)
            if now >= call["deadline"]:
                raise TimeoutError()
            interaction = task["interaction"]
            if interaction["phase"] not in {"SUBMIT_IN_FLIGHT", "SUBMIT_UNKNOWN"}:
                raise PlatformAgentExecutionError()
            if interaction.get("next_receipt_check") is None:
                interaction["next_receipt_check"] = now + INTERACTION_RECONCILE_INTERVAL

    @staticmethod
    def _matches_interaction_receipt(call, interaction, receipt):
        reference = interaction.get("remote_interaction", interaction.get("form", {}))
        return (
            receipt.status in {"ACCEPTED", "REJECTED"}
            and receipt.ref.model_dump() == call["ref"]
            and receipt.run_id == call["agent_run_id"]
            and receipt.interaction_id == reference.get("interaction_id")
            and receipt.revision == reference.get("revision")
            and receipt.submission_key == interaction.get("remote_key")
        )

    def record_interaction_receipt(self, dispatch, key, receipt):
        with self._long_scope(dispatch.execution_id, key, dispatch) as (row, call, task, now):
            self._owned(row, dispatch)
            if now >= call["deadline"]:
                raise TimeoutError()
            interaction = task["interaction"]
            if (
                interaction["phase"] not in {"SUBMIT_IN_FLIGHT", "SUBMIT_UNKNOWN"}
                or task["local_state"] != "WAITING_RESULT"
                or not self._matches_interaction_receipt(call, interaction, receipt)
                or interaction.get("remote_receipt", receipt.status) != receipt.status
            ):
                raise PlatformAgentExecutionError()
            interaction["remote_receipt"] = receipt.status
            interaction.pop("answer", None)
            interaction.pop("receipt_lease", None)
            if receipt.status == "REJECTED":
                self._end_long(call, now, "FAILED", "SUBMIT_REJECTED")
                return False
            self._interaction_phase(interaction, "WAITING_RESULT")
            # TODO [F125][EXT-03] 确认正式阶段时限、取消与迟到回执的核对窗口。
            call["deadline"] = now + INTERACTION_RESULT_WINDOW
            interaction["expires_at"] = call["deadline"]
            return True

    @classmethod
    def _seal_interaction(cls, task, now):
        interaction = task.get("interaction")
        if not interaction or interaction["phase"] == "TERMINAL":
            return
        form = interaction.pop("form", None)
        if form and "submission_digest" in interaction:
            interaction["remote_interaction"] = {field: form[field] for field in ("interaction_id", "revision")}
        if interaction["phase"] == "WAITING_RESULT":
            interaction.setdefault("remote_receipt", "ACCEPTED")
        if cls._interaction_receipt_pending(interaction):
            interaction["receipt_until"] = now + LONG_CANCEL_WINDOW
            interaction.setdefault("next_receipt_check", now)
        else:
            interaction.pop("next_receipt_check", None)
        for field in ("answer", "snapshot", "next_dispatch_at", "replayed", "receipt_lease"):
            interaction.pop(field, None)
        cls._interaction_phase(interaction, "TERMINAL")

    @classmethod
    def _end_long(cls, call, now, state, reason, *, cancel=False):
        task = call["long_task"]
        if task["local_state"] not in LOCAL_TERMINAL:
            task.update(local_state=state, reason=reason, retain_until=now + LONG_SUMMARY_WINDOW)
            call["state"] = "ABANDONED" if state == "STOPPED" else "FAILED"
            cls._seal_interaction(task, now)
        if cancel and task["cancel_state"] == "NONE":
            if task["remote_state"] == "NOT_SENT" or task["remote_state"] in REMOTE_TERMINAL:
                task["cancel_state"] = "NO_ACTION"
            else:
                task.update(cancel_state="INTENT", reconcile_until=now + LONG_CANCEL_WINDOW, next_check=now)

    def close_long(self, dispatch, key, state, reason, *, cancel=False):
        with self._long_scope(dispatch.execution_id, key, dispatch) as (row, call, task, now):
            if task.get("resume"):
                self._owned(row, dispatch)
            if task["local_state"] not in LOCAL_TERMINAL:
                self._end_long(call, now, state, reason, cancel=cancel)

    def _timeout_long(self, call, now):
        task = call["long_task"]
        if task["local_state"] not in LOCAL_TERMINAL:
            phase = task.get("interaction", {}).get("phase")
            reason = (
                "INPUT_TIMEOUT"
                if phase == "WAITING_INPUT"
                else "SUBMIT_TIMEOUT"
                if phase == "SUBMIT_QUEUED"
                else "SUBMIT_UNKNOWN"
                if phase in {"SUBMIT_IN_FLIGHT", "SUBMIT_UNKNOWN"}
                else "START_TIMEOUT"
                if task["remote_state"] == "NOT_SENT"
                else "START_UNKNOWN"
                if not call.get("agent_run_id")
                else "RESULT_UNAVAILABLE"
                if task["remote_state"] == "SUCCEEDED"
                else "RUN_TIMEOUT"
            )
            self._end_long(call, now, "TIMED_OUT", reason, cancel=True)
        return task.get("reason")

    def timeout_long(self, dispatch, key):
        with self._long_scope(dispatch.execution_id, key, dispatch) as (row, call, task, now):
            if task.get("resume"):
                self._owned(row, dispatch)
            return self._timeout_long(call, now)

    def assert_long_graph_live(self, dispatch):
        with self.transaction() as session:
            row = self._execution(session, dispatch.execution_id)
            self._owned(row, dispatch)
            item = row.dispatches[dispatch.dispatch_id]
            if item["kind"] == "LONG_TASK_RESUME" and self.clock() >= item["lease_until"]:
                raise PlatformAgentExecutionError()
            if any(
                call.get("long_task", {}).get("local_state") in {"TIMED_OUT", "STOPPED", "FAILED"}
                for call in row.calls.values()
            ):
                raise PlatformAgentExecutionError()

    @contextmanager
    def output_scope(self, dispatch, node_id, ordinal, config):
        with self.transaction() as session:
            row = self._execution(session, dispatch.execution_id)
            self._owned(row, dispatch)
            if row.actor_reference.get("environment") != self.environment(config) or config.mode == "disabled":
                raise PlatformAgentEnvironmentError()
            key = f"{node_id}:{ordinal}"
            calls = deepcopy(row.calls)
            call = calls.get(key, {})
            if call.get("state") != "DISPATCHING" or call.get("dispatch_id") != dispatch.dispatch_id:
                raise PlatformAgentExecutionError()
            task = call.get("long_task")
            if task is not None and (task["local_state"] != "WAITING_RESULT" or not task.get("result_ready")):
                raise PlatformAgentExecutionError()
            now = self.clock()
            expired = call["deadline"] <= now
            if expired:
                if task is None:
                    raise PlatformAgentExecutionError()
                self._timeout_long(call, now)
            else:
                yield
                call["state"] = "SUCCEEDED"
                if task is not None:
                    task.update(local_state="SUCCEEDED", retain_until=now + LONG_SUMMARY_WINDOW)
                    self._seal_interaction(task, now)
            row.calls = calls
            session.add(row)
        if expired:
            raise PlatformAgentUnknownError()

    def finish_call(self, dispatch, node_id, ordinal, state):
        if state not in {"FAILED", "UNKNOWN"}:
            raise PlatformAgentExecutionError()
        with self.transaction() as session:
            row = self._execution(session, dispatch.execution_id)
            self._owned(row, dispatch)
            calls = deepcopy(row.calls)
            call = calls.get(f"{node_id}:{ordinal}")
            if call and call["state"] == "DISPATCHING":
                call["state"] = state
                row.calls = calls
                session.add(row)

    def record_response(self, dispatch, node_id, ordinal, agent_run_id):
        with self.transaction() as session:
            row = self._execution(session, dispatch.execution_id)
            calls = deepcopy(row.calls)
            call = calls.get(f"{node_id}:{ordinal}")
            if (
                row.dispatches.get(dispatch.dispatch_id, {}).get("owner") != dispatch.owner
                or not call
                or call.get("dispatch_id") != dispatch.dispatch_id
            ):
                raise PlatformAgentExecutionError()
            call["agent_run_id"] = agent_run_id
            row.calls = calls
            session.add(row)

    def request_stop(self, execution_id, *, cancel_long=False):
        with self.transaction() as session:
            row = self._execution(session, execution_id)
            calls = deepcopy(row.calls)
            now = self.clock()
            for key, call in calls.items():
                task = call.get("long_task")
                if task is not None and task["local_state"] != "SUCCEEDED":
                    resume = task.get("resume")
                    if resume and self._long_resume_active(row, task) and now >= call["deadline"]:
                        self._finish_long_resume(row, call, resume, now)
                    else:
                        self._end_long(call, now, "STOPPED", "LOCAL_STOP", cancel=cancel_long)
                        if resume:
                            self._seal_long_resume(row, call, resume)
                    self._version_long_resume(row.calls[key], call)
            if row.state in {"READY", "RUNNING", "WAITING"}:
                for call in calls.values():
                    if call["state"] == "DISPATCHING" and "long_task" not in call:
                        call.update(state="ABANDONED", remote_result_unknown=True)
                row.stop_requested = True
                row.state = "ABORTED"
            if row.calls != calls:
                row.calls = calls
            if session.is_modified(row):
                session.add(row)

    @staticmethod
    def _valid_long_lease(task, lease, now):
        return task.get("lease") == lease and now < task.get("lease_until", 0)

    @staticmethod
    def _interaction_receipt_pending(interaction):
        # W2 记录没有传输标记。只读查回在途记录仍然安全。
        started = interaction.get("phase") in {"SUBMIT_IN_FLIGHT", "SUBMIT_UNKNOWN"}
        return interaction.get("next_receipt_check", 0 if started else None) is not None and (
            "remote_receipt" not in interaction
        )

    @classmethod
    def _interaction_receipt_due(cls, call, interaction, now):
        return (
            cls._interaction_receipt_pending(interaction)
            and interaction.get("next_receipt_check", 0) <= now < interaction.get("receipt_until", call["deadline"])
            and now >= interaction.get("receipt_lease", {}).get("until", 0)
        )

    @staticmethod
    def _interaction_delivery_due(row, call, interaction, now):
        return (
            row.state == "WAITING"
            and not row.stop_requested
            and interaction.get("phase") == "SUBMIT_QUEUED"
            and interaction.get("next_dispatch_at", 0) <= now < call["deadline"]
            and row.dispatches.get(interaction["dispatch_id"], {}).get("state") == "ACCEPTED"
        )

    def claim_interaction_redelivery(self, execution_id, key, tenant_id):
        with self._long_scope(execution_id, key) as (row, call, task, now):
            interaction = task.get("interaction", {})
            if row.tenant_id != tenant_id or row.provider_mode != "mock":
                raise PlatformAgentExecutionError()
            if not self._interaction_delivery_due(row, call, interaction, now):
                return None
            interaction["next_dispatch_at"] = now + INTERACTION_RECONCILE_INTERVAL
            return interaction["interaction_id"], interaction["dispatch_id"]

    def claim_interaction_receipt_check(self, execution_id, key, tenant_id):
        with self._long_scope(execution_id, key) as (row, call, task, now):
            interaction = task.get("interaction", {})
            if row.tenant_id != tenant_id or row.provider_mode != "mock":
                raise PlatformAgentExecutionError()
            if not self._interaction_receipt_due(call, interaction, now):
                return None
            lease = uuid4().hex
            deadline = min(now + 5, interaction.get("receipt_until", call["deadline"]))
            interaction["receipt_lease"] = {"id": lease, "until": deadline}
            interaction["next_receipt_check"] = now + INTERACTION_RECONCILE_INTERVAL
            return lease, deadline

    def finish_interaction_receipt_check(self, execution_id, key, lease, receipt):
        with self._long_scope(execution_id, key) as (_, call, task, now):
            interaction = task["interaction"]
            current = interaction.get("receipt_lease", {})
            if current.get("id") != lease or now >= current["until"]:
                return
            interaction.pop("receipt_lease", None)
            if receipt is not None and self._matches_interaction_receipt(call, interaction, receipt):
                interaction["remote_receipt"] = receipt.status

    @staticmethod
    def _finish_expired_interaction(row, interaction):
        if row.state not in {"WAITING", "RUNNING"}:
            return
        dispatch_id = interaction.get("dispatch_id")
        if dispatch_id:
            row.dispatches = {**row.dispatches, dispatch_id: {**row.dispatches[dispatch_id], "state": "DONE"}}
        row.state = "FAILED"

    def claim_long_reconcile(self, execution_id, key, tenant_id):
        with self._long_scope(execution_id, key) as (row, call, task, now):
            if row.tenant_id != tenant_id or row.provider_mode != "mock":
                raise PlatformAgentExecutionError()
            interaction = task.get("interaction")
            resume = task.get("resume")
            if now >= call["deadline"]:
                if resume and self._long_resume_active(row, task):
                    self._finish_long_resume(row, call, resume, now)
                elif not resume and task["local_state"] not in LOCAL_TERMINAL:
                    self._timeout_long(call, now)
                    if row.state == "RUNNING" and not interaction:
                        row.state = "FAILED"
                if interaction:
                    self._finish_expired_interaction(row, interaction)
            if interaction and task["local_state"] in LOCAL_TERMINAL:
                self._seal_interaction(task, task.get("retain_until", now) - LONG_SUMMARY_WINDOW)
            if task["cancel_state"] not in {"INTENT", "SENT", "ACCEPTED"}:
                if "retain_until" in task and now >= task["retain_until"]:
                    for field in ("progress", "lease", "lease_until", "next_check", "cancel_attempts", "retain_until"):
                        task.pop(field, None)
                    if interaction:
                        for field in (
                            "answer_digest",
                            "submission_digest",
                            "remote_interaction",
                            "remote_key",
                            "receipt_until",
                            "next_receipt_check",
                            "receipt_lease",
                        ):
                            interaction.pop(field, None)
                return None
            if now >= task["reconcile_until"]:
                task["cancel_state"] = "UNCONFIRMED"
                return None
            if now < max(task.get("lease_until", 0), task.get("next_check", 0)):
                return None
            lease = uuid4().hex
            task.update(lease=lease, lease_until=min(now + 10, task["reconcile_until"]))
            return lease

    def permit_long_cancel(self, execution_id, key, lease):
        with self._long_scope(execution_id, key) as (_, call, task, now):
            if not self._valid_long_lease(task, lease, now):
                return False
            if (
                task["cancel_state"] not in {"INTENT", "SENT"}
                or not call.get("agent_run_id")
                or task["remote_state"] in REMOTE_TERMINAL
                or task.get("cancel_attempts", 0) >= 2
            ):
                return False
            task.update(cancel_state="SENT", cancel_attempts=task.get("cancel_attempts", 0) + 1)
            return True

    def finish_long_reconcile(self, execution_id, key, lease, status=None):
        with self._long_scope(execution_id, key) as (_, _, task, now):
            if not self._valid_long_lease(task, lease, now):
                return
            if task["cancel_state"] != "CONFIRMED":
                if status:
                    task["cancel_state"] = status
                elif task["remote_state"] in REMOTE_TERMINAL:
                    task["cancel_state"] = "NO_ACTION"
            task.pop("lease", None)
            task.pop("lease_until", None)
            task["next_check"] = now + 1

    def due_long_calls(
        self, tenant_id, after=None, limit=50, *, interaction_recovery=False, redeliver=False,
        resume_recovery=False, resume_redeliver=False
    ):
        with self.transaction() as session:
            stmt = (
                select(PlatformAgentExecution)
                .where(build_tenant_filter_clause(PlatformAgentExecution.tenant_id))
                .order_by(PlatformAgentExecution.execution_id)
                .limit(limit)
            )
            if after:
                stmt = stmt.where(PlatformAgentExecution.execution_id > after)
            rows = session.exec(stmt).all()
            now = self.clock()
            due = [
                (row.execution_id, key)
                for row in rows
                if row.tenant_id == tenant_id and row.provider_mode == "mock"
                for key, call in row.calls.items()
                if (task := call.get("long_task"))
                and (
                    (
                        now >= call["deadline"]
                        and (
                            task["local_state"] not in LOCAL_TERMINAL
                            or (task.get("interaction") and row.state in {"WAITING", "RUNNING"})
                        )
                    )
                    or (task["cancel_state"] in {"INTENT", "SENT", "ACCEPTED"} and now >= task.get("next_check", 0))
                    or ("retain_until" in task and now >= task["retain_until"])
                    or (
                        interaction_recovery
                        and (interaction := task.get("interaction"))
                        and (
                            self._interaction_receipt_due(call, interaction, now)
                            or (task["local_state"] in LOCAL_TERMINAL and interaction["phase"] != "TERMINAL")
                        )
                    )
                    or (redeliver and self._interaction_delivery_due(row, call, task.get("interaction", {}), now))
                    or (resume_recovery and self._long_resume_poll_due(row, call, task, task.get("resume"), now))
                    or (resume_redeliver and self._long_resume_delivery_due(row, call, task, task.get("resume"), now))
                )
            ]
            return due, rows[-1].execution_id if len(rows) == limit else None

    def fail_execution(self, dispatch):
        """仅结束仍属于该 owner 的执行。旧任务的异常不能覆盖新状态。"""
        with self.transaction() as session:
            row = self._execution(session, dispatch.execution_id)
            item = row.dispatches.get(dispatch.dispatch_id, {})
            if (
                row.stop_requested
                or row.state != "RUNNING"
                or item.get("owner") != dispatch.owner
                or item.get("state") != "CLAIMED"
            ):
                return False
            calls = deepcopy(row.calls)
            for key, call in calls.items():
                task = call.get("long_task", {})
                if call.get("dispatch_id") == dispatch.dispatch_id and (resume := task.get("resume")):
                    self._end_long(call, self.clock(), "FAILED", "RUN_FAILED", cancel=True)
                    self._seal_long_resume(row, call, resume)
                    self._version_long_resume(row.calls[key], call)
                    continue
                if call.get("dispatch_id") == dispatch.dispatch_id and call["state"] == "DISPATCHING":
                    if task.get("interaction"):
                        self._end_long(call, self.clock(), "FAILED", "RUN_FAILED", cancel=True)
                    else:
                        call.update(state="UNKNOWN", remote_result_unknown=True)
            row.calls = calls
            dispatches = deepcopy(row.dispatches)
            dispatches[dispatch.dispatch_id]["state"] = "DONE"
            row.dispatches = dispatches
            row.state = "FAILED"
            session.add(row)
            return True

    def finish_execution(self, dispatch, state):
        if state not in {"SUCCEEDED", "FAILED", "WAITING"}:
            raise PlatformAgentExecutionError()
        with self.transaction() as session:
            row = self._execution(session, dispatch.execution_id)
            self._owned(row, dispatch)
            dispatches = deepcopy(row.dispatches)
            dispatches[dispatch.dispatch_id]["state"] = "DONE"
            row.dispatches = dispatches
            row.state = state
            session.add(row)

    def prepare_resume(self, execution_id, actor):
        with self.transaction() as session:
            row = self._execution(session, execution_id)
            if (
                row.state != "WAITING"
                or uses_agent_interaction(row.graph_snapshot)
                or any(item.get("long_task_resume") for item in row.dispatches.values())
                or row.stop_requested
                or row.actor_reference.get("token_version") != actor.token_version
                or (row.user_id, row.tenant_id) != (actor.user_id, actor.tenant_id)
            ):
                raise PlatformAgentExecutionError()
            dispatch_id = uuid4().hex
            row.dispatches = {**row.dispatches, dispatch_id: {"state": "ACCEPTED", "kind": "RESUME"}}
            row.state = "READY"
            session.add(row)
            return dispatch_id
