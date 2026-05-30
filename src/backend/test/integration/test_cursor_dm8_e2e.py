"""T021 — DM8 end-to-end cursor smoke (AC-01..06 on a live DM8 connection).

Skipped unless a DM8 connection is reachable (env var ``BISHENG_DM8_DSN`` or
the standard local-dev DM8 fixture). T001's dialect smoke test (no DB) has
already validated that SQLAlchemy ``tuple_()`` row-value comparison compiles
under the DM stub dialect — this file proves the *runtime* path also works on
a real DM8 instance, mirroring the F021 ``tests/integration/`` pattern.

Three flows are exercised against each of the F027 list endpoints:

1. First page (no cursor) → assert ``has_more``, capture ``next_cursor``
2. Continue paging until ``has_more=False`` → assert (a) no duplicates by id
   across all pages and (b) all DB rows accounted for (no rows lost)
3. Inject a deliberately tampered cursor → assert HTTP body carries the
   matching ``*InvalidCursorError`` business code

Mark all tests with ``@pytest.mark.dm8`` so CI's default selectors skip them
unless DM8 is available.

Note: this file is a *skeleton*. The harness (DM8 fixtures, app TestClient
configured against DM8, seeded data for each endpoint) is not yet wired up;
when the integration env is ready, fill in ``dm8_app_client`` and remove the
``pytest.skip`` guards.
"""
from __future__ import annotations

import os

import pytest


pytestmark = pytest.mark.dm8


def _dm8_available() -> bool:
    return bool(os.environ.get("BISHENG_DM8_DSN"))


@pytest.fixture
def dm8_app_client():
    if not _dm8_available():
        pytest.skip("DM8 not configured (set BISHENG_DM8_DSN to run)")
    # TODO: wire FastAPI TestClient against a DM8-backed engine.
    raise NotImplementedError("DM8 TestClient fixture pending")


@pytest.mark.parametrize(
    "endpoint, error_code",
    [
        ("/api/v1/knowledge", 10991),
        ("/api/v1/workflow/list", 10550),
        # space_id is parametric — fixture should pick a seeded space
        ("/api/v1/knowledge/space/{space_id}/children", 18070),
    ],
)
def test_first_page_then_paginate_to_end_no_dupes(dm8_app_client, endpoint, error_code):
    pytest.skip("DM8 integration harness pending")


def test_tampered_cursor_returns_invalid_cursor_error_code(dm8_app_client):
    pytest.skip("DM8 integration harness pending")
