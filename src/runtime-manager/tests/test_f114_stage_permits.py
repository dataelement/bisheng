"""A deployment may affect the old writer only after a confirmed maintenance fact."""

from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from runtime_manager.config import Config
from runtime_manager.operations import OperationExecutor
from runtime_manager.platform_client import PlatformError


class Platform:
    def __init__(self, events, refuse=None, lost_reply=False):
        self.events, self.refuse, self.lost_reply = events, refuse, lost_reply
        self.op = {
            "operation_id": "new",
            "tenant_id": 1,
            "app_id": "app",
            "version_id": "v",
            "node_id": "node",
            "generation": 2,
            "owner_epoch": 1,
            "kind": "deploy",
            "status": "running",
            "stage": "admitted",
            "deadline": (datetime.utcnow() + timedelta(minutes=1)).isoformat(),
            "fact_sequence": 0,
            "payload": {"uses_sqlite": True, "migration_plan": [{"create": "table"}]},
        }

    def operation(self, _):
        return deepcopy(self.op)

    def authorize_step(self, operation, phase, *, controller=None):
        self.events.append("allow:" + phase)
        if self.refuse == phase:
            raise PlatformError("runtime_authorization_refused", 409)
        return {
            **{
                k: operation[k]
                for k in ("operation_id", "tenant_id", "app_id", "version_id", "node_id", "generation", "owner_epoch")
            },
            "phase": phase,
            "stage": self.op["stage"],
            "valid_until": (datetime.utcnow() + timedelta(seconds=5)).isoformat(),
        }

    def fact(self, operation, sequence, phase, **kwargs):
        self.events.append("fact:" + phase)
        self.op.update(stage=phase, fact_sequence=sequence, result=kwargs.get("detail", {}))
        if phase == "maintenance":
            self.op["payload"]["maintenance_transition"] = {
                "operation_id": "new",
                "generation": 2,
                "owner_epoch": 1,
                "fact_sequence": sequence,
            }
            if self.lost_reply:
                self.lost_reply = False
                raise PlatformError("response_lost", 503)
        if phase == "ready":
            self.op["stage"] = "serving"
        return {"operation_id": "new", "phase": phase, "sequence": sequence}


def runner(tmp_path, *, refuse=None, lost_reply=False):
    events = []
    platform = Platform(events, refuse, lost_reply)

    def data(_op, action, args):
        events.append("data:" + action)
        return {}

    runtime = SimpleNamespace(data=data, retire_others=lambda op: None, cleanup_preparation=lambda op: None)
    executor = OperationExecutor(Config(data_root=tmp_path, node_id="node"), platform=platform, runtime=runtime)
    executor.stop_instances = lambda *a, **k: events.append("stop-old")
    executor._launch = lambda *a, **k: {"exec_ref": "new-exec", "target": {"host": "10.0.0.1", "port": 8080}}
    return executor, platform, events


def test_denied_maintenance_does_not_touch_old_writer(tmp_path):
    executor, platform, events = runner(tmp_path, refuse="maintenance")
    try:
        with pytest.raises(PlatformError):
            executor._deploy(platform.op)
        assert events == ["allow:maintenance"]
    finally:
        executor.close()


def test_deploy_asks_each_step_and_accepts_proven_fact_reply_loss(tmp_path):
    executor, platform, events = runner(tmp_path, lost_reply=True)
    try:
        executor._deploy(platform.op)
        assert events.index("allow:maintenance") < events.index("fact:maintenance") < events.index("stop-old")
        assert events.index("allow:data_write") < events.index("data:backup")
        assert events.index("allow:starting") < events.index("fact:starting") < events.index("fact:ready")
        assert events.count("fact:maintenance") == 1
        assert events.count("data:migrate") == 1
    finally:
        executor.close()


def test_revocation_after_maintenance_blocks_new_data_and_launch(tmp_path):
    executor, platform, events = runner(tmp_path, refuse="data_write")
    try:
        with pytest.raises(PlatformError):
            executor._deploy(platform.op)
        assert "stop-old" in events
        assert "data:migrate" not in events and "fact:starting" not in events
    finally:
        executor.close()
