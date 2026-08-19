from __future__ import annotations

from dataclasses import dataclass

import pytest

from bisheng.approval.domain.ports.decision_subscriber import (
    APPROVAL_DECISION_EVENT_VERSION,
    APPROVAL_DECISION_SUBSCRIBER_PROTOCOL_VERSION,
    ApprovalDecisionEvent,
)
from bisheng.approval.domain.ports.scenario_policy import (
    APPROVAL_SCENARIO_POLICY_PROTOCOL_VERSION,
    DECISION_DELIVERY_COMPLETION_MODE,
    ApprovalDecisionContext,
    ApprovalSubmissionCommand,
)
from bisheng.approval.domain.services.approval_registry import ApprovalRegistry

SCENARIO_CODE = "test_decision_delivery"


@dataclass
class StubPolicy:
    scenario_code: str = SCENARIO_CODE
    protocol_version: int = APPROVAL_SCENARIO_POLICY_PROTOCOL_VERSION
    completion_mode: str = DECISION_DELIVERY_COMPLETION_MODE

    async def validate_submission(self, command: ApprovalSubmissionCommand) -> None:
        del command

    async def authorize_decision(self, context: ApprovalDecisionContext) -> None:
        del context


@dataclass
class StubSubscriber:
    scenario_code: str = SCENARIO_CODE
    subscriber_key: str = "test_decision_delivery_subscriber"
    protocol_version: int = APPROVAL_DECISION_SUBSCRIBER_PROTOCOL_VERSION
    event_version: int = APPROVAL_DECISION_EVENT_VERSION
    completion_mode: str = DECISION_DELIVERY_COMPLETION_MODE

    async def accept(self, event: ApprovalDecisionEvent) -> None:
        del event


def _complete_registry() -> tuple[ApprovalRegistry, StubPolicy, StubSubscriber]:
    registry = ApprovalRegistry()
    policy = StubPolicy()
    subscriber = StubSubscriber()
    registry.register_policy(policy)
    registry.register_subscriber(subscriber)
    return registry, policy, subscriber


def test_registers_and_reads_policy_and_subscriber_by_scenario() -> None:
    registry, policy, subscriber = _complete_registry()

    assert registry.get_policy(SCENARIO_CODE) is policy
    assert registry.get_subscriber(SCENARIO_CODE) is subscriber


def test_duplicate_policy_registration_fails() -> None:
    registry = ApprovalRegistry()
    registry.register_policy(StubPolicy())

    with pytest.raises(ValueError, match=r"policy.*already registered"):
        registry.register_policy(StubPolicy())


def test_duplicate_subscriber_registration_fails() -> None:
    registry = ApprovalRegistry()
    registry.register_subscriber(StubSubscriber())

    with pytest.raises(ValueError, match=r"subscriber.*already registered"):
        registry.register_subscriber(StubSubscriber())


def test_freeze_requires_subscriber_for_required_scenario() -> None:
    registry = ApprovalRegistry()
    registry.register_policy(StubPolicy())

    with pytest.raises(ValueError, match=r"subscriber.*missing"):
        registry.freeze_decision_delivery(required_scenario_codes={SCENARIO_CODE})


def test_freeze_requires_policy_for_required_scenario() -> None:
    registry = ApprovalRegistry()
    registry.register_subscriber(StubSubscriber())

    with pytest.raises(ValueError, match=r"policy.*missing"):
        registry.freeze_decision_delivery(required_scenario_codes={SCENARIO_CODE})


def test_freeze_rejects_completion_mode_mismatch() -> None:
    registry = ApprovalRegistry()
    registry.register_policy(StubPolicy(completion_mode=DECISION_DELIVERY_COMPLETION_MODE))
    registry.register_subscriber(StubSubscriber(completion_mode="business_execution"))

    with pytest.raises(ValueError, match=r"completion mode.*mismatch"):
        registry.freeze_decision_delivery(required_scenario_codes={SCENARIO_CODE})


@pytest.mark.parametrize(
    ("policy_version", "subscriber_version", "match"),
    [
        (
            APPROVAL_SCENARIO_POLICY_PROTOCOL_VERSION + 1,
            APPROVAL_DECISION_SUBSCRIBER_PROTOCOL_VERSION,
            "policy.*version",
        ),
        (
            APPROVAL_SCENARIO_POLICY_PROTOCOL_VERSION,
            APPROVAL_DECISION_SUBSCRIBER_PROTOCOL_VERSION + 1,
            "subscriber.*version",
        ),
    ],
)
def test_freeze_rejects_unsupported_protocol_versions(
    policy_version: int,
    subscriber_version: int,
    match: str,
) -> None:
    registry = ApprovalRegistry()
    registry.register_policy(StubPolicy(protocol_version=policy_version))
    registry.register_subscriber(StubSubscriber(protocol_version=subscriber_version))

    with pytest.raises(ValueError, match=match):
        registry.freeze_decision_delivery(required_scenario_codes={SCENARIO_CODE})


def test_freeze_rejects_unsupported_event_version() -> None:
    registry = ApprovalRegistry()
    registry.register_policy(StubPolicy())
    registry.register_subscriber(StubSubscriber(event_version=APPROVAL_DECISION_EVENT_VERSION + 1))

    with pytest.raises(ValueError, match=r"event.*version"):
        registry.freeze_decision_delivery(required_scenario_codes={SCENARIO_CODE})


@pytest.mark.parametrize("registration", ["policy", "subscriber"])
def test_freeze_rejects_later_decision_delivery_registration(registration: str) -> None:
    registry, _, _ = _complete_registry()
    registry.freeze_decision_delivery(required_scenario_codes={SCENARIO_CODE})

    with pytest.raises(RuntimeError, match="frozen"):
        if registration == "policy":
            registry.register_policy(StubPolicy(scenario_code="late_scenario"))
        else:
            registry.register_subscriber(StubSubscriber(scenario_code="late_scenario"))


async def test_freezing_decision_delivery_does_not_change_legacy_handler_registry() -> None:
    registry, _, _ = _complete_registry()
    registry.freeze_decision_delivery(required_scenario_codes={SCENARIO_CODE})
    legacy_handler = object()

    registry.register_handler("legacy_scenario", legacy_handler)

    assert await registry.get_handler("legacy_scenario") is legacy_handler
