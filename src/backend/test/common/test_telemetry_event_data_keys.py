"""Regression: telemetry ``event_data`` keys must be prefixed with the event
name's *value* (e.g. ``application_process_app_id``), not the Enum member's
repr (``BaseTelemetryTypeEnum.APPLICATION_PROCESS_app_id``).

Root cause guarded here: since Python 3.11, f-string formatting of a
``str``-mixed Enum member returns ``str(member)`` (the repr
``ClassName.MEMBER``) instead of the member's value. ``base_telemetry_schema``
builds the per-field keys by prefixing ``event_name``; it must use
``event_name.value`` so the keys stay stable across Python versions.
"""

from bisheng.common.constants.enums.telemetry import (
    ApplicationTypeEnum,
    BaseTelemetryTypeEnum,
)
from bisheng.common.schemas.telemetry.base_telemetry_schema import (
    BaseTelemetryEvent,
    UserContext,
)
from bisheng.common.schemas.telemetry.event_data_schema import (
    ApplicationProcessEventData,
    UserLoginEventData,
)


def _user_context() -> UserContext:
    return UserContext(user_id=1, user_name="alice")


def test_application_process_event_data_keys_use_enum_value():
    event = BaseTelemetryEvent(
        event_type=BaseTelemetryTypeEnum.APPLICATION_PROCESS,
        user_context=_user_context(),
        trace_id="trace-1",
        event_data=ApplicationProcessEventData(
            app_id="cc7351",
            app_name="zgq",
            app_type=ApplicationTypeEnum.WORKFLOW,
            chat_id="",
            start_time=1781512034,
            end_time=1781512035,
            process_time=1288,
        ),
    )

    event_data = event.model_dump()["event_data"]

    assert event_data == {
        "application_process_app_id": "cc7351",
        "application_process_app_name": "zgq",
        "application_process_app_type": "workflow",
        "application_process_chat_id": "",
        "application_process_start_time": 1781512034,
        "application_process_end_time": 1781512035,
        "application_process_process_time": 1288,
    }
    # Belt-and-suspenders: no key should leak the Enum class name.
    assert all("BaseTelemetryTypeEnum" not in key for key in event_data)


def test_event_data_key_prefix_is_event_name_value():
    """Every event_data key must start with ``<event_name_value>_``."""
    event = BaseTelemetryEvent(
        event_type=BaseTelemetryTypeEnum.USER_LOGIN,
        user_context=_user_context(),
        trace_id="trace-2",
        event_data=UserLoginEventData(method="password"),
    )

    event_data = event.model_dump()["event_data"]

    prefix = f"{BaseTelemetryTypeEnum.USER_LOGIN.value}_"
    assert event_data == {"user_login_method": "password"}
    assert all(key.startswith(prefix) for key in event_data)


def test_event_data_absent_keeps_payload_untouched():
    event = BaseTelemetryEvent(
        event_type=BaseTelemetryTypeEnum.USER_LOGIN,
        user_context=_user_context(),
        trace_id="trace-3",
        event_data=None,
    )

    assert event.model_dump()["event_data"] is None
