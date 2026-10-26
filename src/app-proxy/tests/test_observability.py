"""T097 — the three §7 events, asserted by **name and field set**, never by text.

Asserting on log *text* is how observability tests become a tax: the first
person who reformats a message breaks a test that was never about wording. So
every assertion here reads ``record.event`` and ``record.fields`` — the
structured payload a JSON handler would ship — and the message string is left
free to change.

What is actually pinned:

* every emitter fills the whole field set declared in ``EVENT_FIELDS`` (the
  declaration and the emitters cannot drift apart);
* a real forwarded request, a real refusal and a real fallback each produce the
  event they are supposed to produce, with the visitor and the outcome in it;
* ``app_proxy.header_strip`` is a **WARNING** carrying the forged header names —
  it is the only production observable of AC-32, and an INFO would sink it.
"""

from __future__ import annotations

import logging

import pytest

from app_proxy.observability import (
    EVENT_FALLBACK,
    EVENT_FIELDS,
    EVENT_HEADER_STRIP,
    EVENT_REQUEST,
    log_fallback,
    log_header_strip,
    log_request,
)
from tests.conftest import NAVIGATE_HEADERS
from tests.fakes import DEFAULT_APP_ID, deny_response


@pytest.fixture()
def events(caplog):
    """Collect the structured records, in order, whatever logger emitted them."""
    caplog.set_level(logging.DEBUG, logger="app_proxy")

    def _of(event: str) -> list[logging.LogRecord]:
        return [record for record in caplog.records if getattr(record, "event", None) == event]

    return _of


def _fields(record: logging.LogRecord) -> dict:
    return record.fields


class TestContract:
    @pytest.mark.parametrize("event", sorted(EVENT_FIELDS))
    def test_declared_fields_are_emitted(self, event, events, caplog):
        """Each emitter fills its declared field set — the lockstep check.

        Written as one parametrised case per event so a newly declared field
        names the event that failed rather than "something in the registry".
        """
        emit = {
            EVENT_REQUEST: lambda: log_request(
                logging.getLogger("app_proxy.test"),
                request_id="r1",
                slug="foo",
                user_id="42",
                decision="allow",
                reason="",
                cache_hit=False,
                upstream_status=200,
                latency_ms=1.0,
            ),
            EVENT_HEADER_STRIP: lambda: log_header_strip(
                logging.getLogger("app_proxy.test"), request_id="r1", slug="foo", stripped=["X-BiSheng-User-Id"]
            ),
            EVENT_FALLBACK: lambda: log_fallback(
                logging.getLogger("app_proxy.test"), request_id="r1", slug="foo", kind="recovering", reason="no_route"
            ),
        }[event]
        emit()

        record = events(event)[0]
        missing = set(EVENT_FIELDS[event]) - set(_fields(record))
        assert not missing, f"{event} emitted without {sorted(missing)}"

    def test_extra_fields_ride_along_without_displacing_the_contract(self, events):
        """``protocol=ws`` and friends are additions, not replacements."""
        log_request(
            logging.getLogger("app_proxy.test"),
            request_id="r1",
            slug="foo",
            user_id=None,
            decision="allow",
            reason="",
            cache_hit=True,
            upstream_status=None,
            latency_ms=0.0,
            protocol="ws",
        )
        fields = _fields(events(EVENT_REQUEST)[0])
        assert fields["protocol"] == "ws"
        assert set(EVENT_FIELDS[EVENT_REQUEST]) <= set(fields)


class TestRequestEvent:
    def test_request_log_fields_complete(self, logged_in, events, echo_upstream):
        """A forwarded request logs who, where, how it went and how long it took."""
        # ``/apps/foo/`` — the app's own root. The slash-less form is a 308
        # first (and a line of its own), which would make "one request, one
        # line" assert over two requests.
        assert logged_in.get("/apps/foo/", headers=NAVIGATE_HEADERS).status_code == 200
        assert echo_upstream.requests, "precondition: the request really reached the app"

        records = events(EVENT_REQUEST)
        assert len(records) == 1, "one request, one line"
        fields = _fields(records[0])
        assert set(EVENT_FIELDS[EVENT_REQUEST]) <= set(fields)
        assert fields["slug"] == "foo"
        assert fields["decision"] == "allow"
        assert fields["user_id"] == "42", "the visitor the app was told about"
        assert fields["upstream_status"] == 200
        assert fields["latency_ms"] >= 0.0

    def test_refusal_is_logged_with_its_reason_and_no_upstream_status(self, proxy_client, fake_backend, events):
        """``upstream_status=None`` is what separates "the app said 403" from
        "the app never saw this request"."""
        fake_backend.response = deny_response("forbidden")

        proxy_client.get("/apps/foo", headers=NAVIGATE_HEADERS)

        fields = _fields(events(EVENT_REQUEST)[0])
        assert fields["decision"] == "forbidden"
        assert fields["upstream_status"] is None
        assert set(EVENT_FIELDS[EVENT_REQUEST]) <= set(fields)

    def test_an_impossible_slug_is_still_one_request_line(self, proxy_client, events, fake_backend):
        """Answered locally, but it is still traffic somebody may have to explain."""
        proxy_client.get("/apps/..%2f..", headers=NAVIGATE_HEADERS)

        records = events(EVENT_REQUEST)
        assert records, "a locally refused request is not an unlogged request"
        assert _fields(records[0])["reason"] == "invalid_slug"
        assert not fake_backend.calls, "precondition: no RPC was made"

    def test_a_refused_socket_upgrade_is_logged_too(self, proxy_client, fake_backend, events):
        """The socket half of the same rule.

        An invalid slug on ``/apps/{slug}/ws`` used to close silently, so a
        client stuck in a reconnect loop against a mistyped address left no
        trace at all — the one shape of traffic most likely to be reported as
        "the app is down".
        """
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect):
            with proxy_client.websocket_connect("/apps/..%2f../ws"):
                pass

        fields = _fields(events(EVENT_REQUEST)[0])
        assert fields["reason"] == "invalid_slug"
        assert fields["protocol"] == "ws"
        assert not fake_backend.calls, "precondition: no RPC was made"

    def test_the_trailing_slash_redirect_is_its_own_line(self, logged_in, events):
        """The visitor's *first* hit on an app is the 308, not what follows it.

        Leaving it unlogged puts the wrong URL and the wrong timestamp at the
        start of every「打不开」 investigation, because the only line left is
        the redirected request.
        """
        assert logged_in.get("/apps/foo", headers=NAVIGATE_HEADERS, follow_redirects=False).status_code == 308

        records = events(EVENT_REQUEST)
        assert len(records) == 1
        fields = _fields(records[0])
        assert fields["reason"] == "trailing_slash_redirect"
        assert fields["decision"] == "allow"
        assert set(EVENT_FIELDS[EVENT_REQUEST]) <= set(fields)

    def test_a_refusal_names_the_visitor_it_refused(self, proxy_client, fake_backend, events):
        """``user_id`` is a §7 field, and "who could not get in" is the question
        it exists for — so it has to survive the path where there is no identity
        material to read it out of."""
        payload = deny_response("forbidden")
        payload["user_id"] = 42

        fake_backend.response = payload
        proxy_client.get("/apps/foo", headers=NAVIGATE_HEADERS)

        assert _fields(events(EVENT_REQUEST)[0])["user_id"] == "42"


class TestHeaderStrip:
    def test_header_strip_logged_at_warning_with_forged_names(self, logged_in, events):
        """AC-32's only production observable — see the module docstring."""
        logged_in.get(
            "/apps/foo",
            headers={
                **NAVIGATE_HEADERS,
                "X_BiSheng_User_Id": "1",
                "x-bisheng-user-name": "root",
            },
        )

        records = events(EVENT_HEADER_STRIP)
        assert len(records) == 1
        assert records[0].levelno == logging.WARNING, "an INFO here would never be alerted on"
        stripped = _fields(records[0])["stripped"].lower()
        assert "x_bisheng_user_id" in stripped and "x-bisheng-user-name" in stripped

    def test_clean_request_logs_no_strip_event(self, logged_in, events):
        """The signal is only useful if the quiet case is quiet."""
        logged_in.get("/apps/foo", headers=NAVIGATE_HEADERS)
        assert events(EVENT_HEADER_STRIP) == []


class TestFallback:
    def test_fallback_type_recorded(self, logged_in, fake_manager, events):
        """§7 wants the distribution over page kinds, so the kind is a field."""
        fake_manager.routes[DEFAULT_APP_ID] = None

        response = logged_in.get("/apps/foo", headers=NAVIGATE_HEADERS)
        assert response.status_code == 200, "precondition: a page, not a 502"

        records = events(EVENT_FALLBACK)
        assert len(records) == 1
        fields = _fields(records[0])
        assert set(EVENT_FIELDS[EVENT_FALLBACK]) <= set(fields)
        assert fields["kind"] == "recovering"
        assert fields["reason"] == "no_route"
        assert records[0].levelno == logging.WARNING

    def test_deploying_page_is_a_distinct_kind(self, logged_in, fake_manager, events):
        """「发布中」 and 「恢复中」 are different operational stories (D7)."""
        from tests.fakes import DEPLOYING_ROUTE

        fake_manager.routes[DEFAULT_APP_ID] = DEPLOYING_ROUTE

        logged_in.get("/apps/foo", headers=NAVIGATE_HEADERS)

        fields = _fields(events(EVENT_FALLBACK)[0])
        assert fields["kind"] == "deploying"
        assert fields["reason"] == "deploy_in_flight"

    def test_fallback_also_closes_the_request_line(self, logged_in, fake_manager, events):
        """A visitor who got a fallback page still produced one request line."""
        fake_manager.routes[DEFAULT_APP_ID] = None

        logged_in.get("/apps/foo/", headers=NAVIGATE_HEADERS)

        fields = _fields(events(EVENT_REQUEST)[0])
        assert fields["upstream_status"] is None
        assert fields["reason"] == "no_route"
