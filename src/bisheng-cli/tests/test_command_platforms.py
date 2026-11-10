"""T047 — `bisheng platforms list` / `bisheng platforms use`.

The store has been multi-profile since T012; these tests pin the interaction on
top of it: the listing never shows a key, `use` re-points `current` and refuses
to invent a profile, and a bare `platforms` is a usage error with no request.
"""

from __future__ import annotations

import io
import json

from bisheng_cli import credentials
from bisheng_cli.errors import EXIT_NOT_LOGGED_IN, EXIT_OK, EXIT_USAGE
from bisheng_cli.main import run as main_run
from tests.helpers.platform_mock import FAKE_KEY, FAKE_KEY_MASK

BASE = "http://platform.test"
OTHER = "http://other.test"


def _profile(**overrides) -> dict:
    payload = {
        "api_key": FAKE_KEY,
        "key_mask": FAKE_KEY_MASK,
        "actor_kind": "service_account",
        "actor_id": 123,
        "actor_name": "问卷小队开发号",
        "expires_at": "2026-12-31T00:00:00",
    }
    payload.update(overrides)
    return payload


def _run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    code = main_run(argv, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_list_marks_current_and_never_prints_the_key(home_dir) -> None:
    credentials.save_profile(BASE, _profile())
    credentials.save_profile(OTHER, _profile(actor_name="另一个号"))
    code, out, err = _run(["platforms", "list", "--json"])
    assert code == EXIT_OK
    assert f"* {OTHER}" in err and f"  {BASE}" in err
    assert "问卷小队开发号" in err and "另一个号" in err and FAKE_KEY_MASK in err
    assert FAKE_KEY not in err and FAKE_KEY not in out
    result = json.loads(out.strip().splitlines()[-1])
    assert result["event"] == "result" and result["ok"] is True
    rows = result["data"]["platforms"]
    assert [(r["base_url"], r["current"]) for r in rows] == [(BASE, False), (OTHER, True)]
    assert all("api_key" not in r for r in rows)


def test_list_with_nothing_logged_in_is_ok_and_says_so(home_dir) -> None:
    code, out, err = _run(["platforms", "list", "--json"])
    assert code == EXIT_OK
    assert "bisheng login" in err
    assert json.loads(out.strip().splitlines()[-1])["data"]["platforms"] == []


def test_use_switches_current(home_dir) -> None:
    credentials.save_profile(BASE, _profile())
    credentials.save_profile(OTHER, _profile())
    code, _, err = _run(["platforms", "use", BASE + "/"])
    assert code == EXIT_OK
    assert BASE in err
    assert credentials.load_current().base_url == BASE


def test_use_unknown_platform_is_exit_3_and_leaves_current_alone(home_dir) -> None:
    credentials.save_profile(BASE, _profile())
    code, _, err = _run(["platforms", "use", "http://never.test"])
    assert code == EXIT_NOT_LOGGED_IN
    assert "http://never.test" in err and "bisheng login" in err
    assert credentials.load_current().base_url == BASE


def test_bare_platforms_is_usage_error(home_dir) -> None:
    code, _, err = _run(["platforms"])
    assert code == EXIT_USAGE
    assert "platforms list" in err and "platforms use" in err
