"""F056 T027 / AC-34 — administrators have exactly one audit query entry.

The behavioural half (a low-frequency governance event and a high-frequency
runtime event told apart only by the ``event_type`` filter on the same call)
is in ``test/audit/test_audit_scope_and_roles.py``. This is the structural
half: a census of the whole route table, so that adding a per-family query page
— an access-record list, a model-call list — fails here instead of being
noticed in review.

It lives under ``test/api/`` rather than next to its sibling because the audit
unit tests stub ``bisheng.api.router`` / ``bisheng.telemetry_search`` into
``sys.modules`` in order to exercise the DAO without the application, and those
stubs make ``bisheng.main`` unimportable for the rest of the session. This
package imports the real app, like ``test_route_path_naming.py`` next to it.
"""

from fastapi.routing import APIRoute

from bisheng.main import app

#: Reads on the audit face. ``/session`` is chat forensics — a different object
#: (conversations), not an event-type view of the audit log — and predates the
#: app factory.
EXPECTED_AUDIT_READS = {
    "/api/v1/audit",
    "/api/v1/audit/apps",
    "/api/v1/audit/export/data",
    "/api/v1/audit/operators",
    "/api/v1/audit/session",
    "/api/v1/audit/session/export/data",
}


def _audit_reads() -> set[str]:
    return {
        route.path
        for route in app.routes
        if isinstance(route, APIRoute)
        and "GET" in route.methods
        and (route.path == "/api/v1/audit" or route.path.startswith("/api/v1/audit/"))
    }


def test_audit_reads_are_one_route_family():
    assert _audit_reads() == EXPECTED_AUDIT_READS


def test_no_separate_query_page_for_the_high_frequency_families():
    """Access records, model calls and runtime capability calls are reached by
    event type on the face above — not by a page of their own (AC-34).

    They are the three families whose volume tempts a dedicated list. A second
    page would satisfy "the data is somewhere" while breaking the promise the
    AC actually makes: that an administrator does not have to know which page
    holds which event.
    """
    suspects = {
        route.path
        for route in app.routes
        if isinstance(route, APIRoute)
        and "GET" in route.methods
        and any(word in route.path for word in ("access-log", "access_log", "call-record", "call_record"))
    }
    assert suspects == set()
