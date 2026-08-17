"""F056 T015 — every ``app.*`` audit action is registered in all four places.

An audit action has to appear in four unrelated files before a written event is
findable: the backend whitelist, the action enum, the platform filter list and
the three locale files. Miss one and the row lands in the database and never
shows up on the 系统操作 page — no exception, no log line, nothing to notice
until someone goes looking for an event that "should be there".

AC-27 ("no event type that is written but cannot be found") is judged against
this feature, but three other features do the writing. Machine-checking it here
is the only way that verdict survives them: a missing registration fails in CI
instead of surfacing months later as a compliance gap.

The i18n leaf key is *derived*, never chosen: ``actionToI18nKey`` splits on
``.`` and ``_`` and camel-cases, so ``app.visibility_change`` can only be
``appVisibilityChange``. A hand-picked key silently falls back to the raw action
string on screen, because the render call passes a ``defaultValue``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bisheng.app_runtime.domain.constants import AppAuditAction
from bisheng.database.models.audit_log import _UI_VISIBLE_V2_ACTIONS

_FRONTEND = Path(__file__).resolve().parents[3] / "frontend" / "platform"
_LOG_CONTROLLER = _FRONTEND / "src" / "controllers" / "API" / "log.ts"
_LOCALES = ("zh-Hans", "en-US", "ja")

#: Every ``app.release.*`` action, asserted like the rest.
#:
#: These were briefly pinned ``xfail(strict=True)`` while the backend whitelist
#: had them and the frontend did not — publish events were written and then
#: could not be found on the audit page at all. The frontend half landed
#: 2026-08-18 and all sixteen XPASSed, which is exactly what the strict marker
#: is for: it forced the pending entry to be deleted rather than quietly
#: outliving the gap it described.
_RELEASE_ACTIONS = frozenset(
    action for action in _UI_VISIBLE_V2_ACTIONS if action.startswith("app.release.")
)


def _i18n_key(action: str) -> str:
    """Mirror of platform ``actionToI18nKey`` (systemLog/index.tsx)."""
    head, *rest = [part for part in action.replace(".", "_").split("_") if part]
    return head + "".join(part[:1].upper() + part[1:] for part in rest)


def _locale_event_types(language: str) -> dict:
    payload = json.loads((_FRONTEND / "public" / "locales" / language / "bs.json").read_text(encoding="utf-8"))
    return payload["log"]["eventTypeEnum"]


def _assert_registered(action: str) -> None:
    assert action in _UI_VISIBLE_V2_ACTIONS, f"{action} is missing from the audit page whitelist"

    controller = _LOG_CONTROLLER.read_text(encoding="utf-8")
    assert f"'{action}'" in controller, f"{action} is missing from platform controllers/API/log.ts"

    key = _i18n_key(action)
    for language in _LOCALES:
        event_types = _locale_event_types(language)
        assert key in event_types, f"{action} has no log.eventTypeEnum.{key} in {language}"
        assert event_types[key].strip(), f"log.eventTypeEnum.{key} is blank in {language}"


@pytest.mark.parametrize("action", sorted(member.value for member in AppAuditAction))
def test_owned_app_actions_registered_everywhere(action):
    """Everything F054 and F056 write is findable on the audit page."""
    _assert_registered(action)


@pytest.mark.parametrize("action", sorted(_RELEASE_ACTIONS))
def test_release_actions_registered_everywhere(action):
    _assert_registered(action)


def test_visibility_change_key_is_derived_not_invented():
    """The one key F056 adds is exactly what the frontend will look up."""
    assert _i18n_key(AppAuditAction.VISIBILITY_CHANGE.value) == "appVisibilityChange"


@pytest.mark.parametrize("language", _LOCALES)
def test_object_type_app_has_copy(language):
    """The audit list's object column renders ``app`` as a word, not as ``app``.

    Without this key ``renderObjectType`` falls back to the raw ``target_type``
    — readable enough to survive review, and wrong in all three languages.
    """
    payload = json.loads((_FRONTEND / "public" / "locales" / language / "bs.json").read_text(encoding="utf-8"))
    object_types = payload["log"]["objectTypeEnum"]
    assert "app" in object_types
    assert object_types["app"].strip()
