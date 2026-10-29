"""Bounded v1 content safety facts; never accept model bodies or credentials."""

import json
import re
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator

from bisheng.dsh.domain.schemas.model_audit_context import AUDIT_FIELDS, parse_audit_context

MAX_EVENT_BYTES = 64 * 1024
MAX_JSON_DEPTH = 16
MAX_RULE_REFS = 20
MAX_INT64 = 9223372036854775807
ContentSafetyState = Literal["PASSED", "BLOCKED", "ERROR", "DISABLED", "NOT_APPLICABLE", "UNREPORTED"]
SensitiveDirection = Literal["INPUT", "OUTPUT", "BOTH"]
SafetyDetailsStatus = Literal["AVAILABLE", "PENDING", "PURGED", "UNREPORTED"]
DrainStatus = Literal["NOT_REQUIRED", "RUNNING", "FINISHED", "TIMED_OUT", "LIMITED", "DISCONNECTED"]


def _positive_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]{0,18}", value) or int(value) > MAX_INT64:
        raise ValueError("Expected a positive int64 decimal string")
    return value


def _uuid(value):
    if not isinstance(value, str) or len(value) != 36:
        raise ValueError("Expected a UUID string")
    try:
        parsed = UUID(value)
    except ValueError:
        raise ValueError("Expected a UUID string") from None
    if str(parsed) != value.lower():
        raise ValueError("Expected a UUID string")
    return value


def _utc_time(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?(?:Z|\+00:00)", value
    ):
        raise ValueError("Expected an RFC3339 UTC timestamp")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        raise ValueError("Expected an RFC3339 UTC timestamp") from None
    # Preserve the signed timestamp spelling for event hashing and retries.
    return value


PositiveId = Annotated[str, BeforeValidator(_positive_id)]
UuidText = Annotated[str, BeforeValidator(_uuid)]
UtcTimestamp = Annotated[str, BeforeValidator(_utc_time)]
Version = Annotated[int, Field(ge=0, le=MAX_INT64)]
RuleRef = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")]


class SafetyDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True, frozen=True)


class SafetyConversation(SafetyDTO):
    conversation_id: str | None = None
    request_kind: Literal["chat", "compaction", "session-title"] | None = None
    session_origin: Literal["main", "subagent"] | None = None
    parent_conversation_id: str | None = None

    @model_validator(mode="before")
    @classmethod
    def clean_hints(cls, value):
        if not isinstance(value, dict):
            return value
        allowed = set(AUDIT_FIELDS) - {"message_sources"}
        if set(value) - allowed:
            raise ValueError("Unexpected conversation fields")
        try:
            size = len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf8"))
        except (UnicodeError, TypeError, ValueError):
            return {}
        if size > 4096:
            return {}
        context = parse_audit_context({key: item for key, item in value.items() if item is not None}, allowed)
        return {key: getattr(context, key) for key in allowed if getattr(context, key) is not None}


class StageResults(SafetyDTO):
    input: ContentSafetyState
    output: ContentSafetyState


class StageVersions(SafetyDTO):
    input: Version
    output: Version


class MatchedWords(SafetyDTO):
    input: tuple[str, ...] = Field(max_length=MAX_RULE_REFS)
    output: tuple[str, ...] = Field(max_length=MAX_RULE_REFS)

    @field_validator("input", "output", mode="before")
    @classmethod
    def bounded_words(cls, value):
        if not isinstance(value, (list, tuple)):
            return value
        if len(value) > MAX_RULE_REFS:
            raise ValueError("Matched word summary exceeds limit")
        for word in value:
            if not isinstance(word, str) or not word.strip() or len(word) > 256:
                raise ValueError("Invalid matched word")
            try:
                word.encode("utf8")
            except UnicodeError:
                raise ValueError("Invalid matched word Unicode") from None
        if len(set(value)) != len(value):
            raise ValueError("Duplicate matched words")
        return tuple(value)

    @model_validator(mode="after")
    def bounded_total(self):
        if len(self.input) + len(self.output) > MAX_RULE_REFS:
            raise ValueError("Matched word summary exceeds limit")
        return self


class ContentSafetyEvent(SafetyDTO):
    schema_version: Literal[1]
    source_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")
    event_id: UuidText
    gateway_request_id: UuidText
    backend_request_id: UuidText | None = None
    tenant_id: PositiveId
    user_id: PositiveId
    model_id: PositiveId
    session_id: UuidText | None = None
    protocol: Literal["CHAT", "RESPONSES"]
    event_kind: Literal["DECISION", "FINAL", "DRAIN"]
    event_version: int = Field(ge=1, le=MAX_INT64)
    request_started_at: UtcTimestamp
    occurred_at: UtcTimestamp
    stage_results: StageResults
    stage_versions: StageVersions
    policy_version: Version
    builtin_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    hit_count: int = Field(ge=0, le=MAX_INT64)
    hit_count_truncated: bool
    rule_refs: tuple[RuleRef, ...] = Field(max_length=MAX_RULE_REFS)
    matched_words: MatchedWords | None = None
    forwarded: bool
    drain_status: DrainStatus
    conversation: SafetyConversation | None = None

    @field_validator("rule_refs", mode="before")
    @classmethod
    def immutable_refs(cls, value):
        if isinstance(value, list):
            return tuple(value)
        return value

    @field_validator("schema_version", mode="before")
    @classmethod
    def integer_schema_version(cls, value):
        if type(value) is not int:
            raise ValueError("Expected integer schema version")
        return value

    @model_validator(mode="after")
    def validate_stage_versions(self):
        for direction in ("input", "output"):
            version = getattr(self.stage_versions, direction)
            state = getattr(self.stage_results, direction)
            if self.matched_words is not None and getattr(self.matched_words, direction) and state != "BLOCKED":
                raise ValueError("Matched words require a blocked stage")
            if version > self.event_version or (state == "UNREPORTED") != (version == 0):
                raise ValueError("Invalid stage version")
        start = datetime.fromisoformat(self.request_started_at.replace("Z", "+00:00"))
        occurred = datetime.fromisoformat(self.occurred_at.replace("Z", "+00:00"))
        if (start - occurred).total_seconds() > 5:
            raise ValueError("Event time precedes request start")
        return self


class ContentSafetyEnvelope(SafetyDTO):
    sent_at: UtcTimestamp
    event: ContentSafetyEvent

    @classmethod
    def model_validate_json(cls, json_data, *, strict=None, context=None):
        try:
            encoded = json_data.encode("utf8") if isinstance(json_data, str) else json_data
            size = len(encoded)
        except (TypeError, UnicodeError):
            raise ValueError("Invalid event JSON") from None
        if size > MAX_EVENT_BYTES:
            raise ValueError("Event JSON exceeds size limit")
        return super().model_validate_json(json_data, strict=strict, context=context)

    @model_validator(mode="before")
    @classmethod
    def bounded_json(cls, value):
        if isinstance(value, dict):
            pending = [(value, 1)]
            while pending:
                item, depth = pending.pop()
                if isinstance(item, (dict, list, tuple)):
                    if depth > MAX_JSON_DEPTH:
                        raise ValueError("Event JSON exceeds depth limit")
                    children = item.values() if isinstance(item, dict) else item
                    pending.extend((child, depth + 1) for child in children)
            try:
                size = len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf8"))
            except (TypeError, ValueError, UnicodeError):
                raise ValueError("Invalid event JSON") from None
            if size > MAX_EVENT_BYTES:
                raise ValueError("Event JSON exceeds size limit")
        return value

    @model_validator(mode="after")
    def validate_observed_times(self):
        sent = datetime.fromisoformat(self.sent_at.replace("Z", "+00:00"))
        for value in (self.event.request_started_at, self.event.occurred_at):
            observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if (observed - sent).total_seconds() > 300:
                raise ValueError("Observed time exceeds send time allowance")
        return self


class ContentSafetyReceipt(SafetyDTO):
    event_id: UuidText
    receipt: Literal["COMMITTED"]
    duplicate: bool
    association_status: Literal["ASSOCIATED", "UNASSOCIATED"]
    audit_request_id: UuidText | None = None
