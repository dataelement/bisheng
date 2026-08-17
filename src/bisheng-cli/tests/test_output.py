"""T005 — the output layer.

AC-04 in one sentence: usable with no TTY, parseable by a machine, and never
echoing key material. Everything here is one of those three.
"""

from __future__ import annotations

import io
import json

import pytest

from bisheng_cli.output import STAGE_LABELS, Emitter, mask, stage_label, wrap_stream
from tests.helpers.platform_mock import FAKE_KEY


def _emitter(**kw):
    out, err = io.StringIO(), io.StringIO()
    kw.setdefault("json_mode", True)
    kw.setdefault("is_tty", False)
    return Emitter(stdout=out, stderr=err, **kw), out, err


def _lines(buf: io.StringIO) -> list[str]:
    return [line for line in buf.getvalue().splitlines() if line.strip()]


def test_json_mode_machine_events_go_to_stdout_human_text_to_stderr() -> None:
    em, out, err = _emitter()
    em.stage("deploy", "precheck_build", "running")
    em.progress("deploy", "upload", 100, 100)
    em.result("deploy", ok=True, exit_code=0)
    # Every stdout line must parse; one stray progress sentence there would blow
    # up the agent's `jq` pipeline on its first read.
    for line in _lines(out):
        json.loads(line)
    assert _lines(err), "the human watching the terminal must still see the run"


def test_result_event_is_always_the_last_line_and_appears_exactly_once() -> None:
    em, out, _ = _emitter()
    em.stage("deploy", "received", "running")
    em.result("deploy", ok=False, exit_code=10)
    em.result("deploy", ok=True, exit_code=0)  # a second call must not double-emit
    events = [json.loads(line) for line in _lines(out)]
    assert [e["event"] for e in events].count("result") == 1
    assert events[-1]["event"] == "result"
    assert events[-1]["exit_code"] == 10


def test_event_shapes_are_exactly_three() -> None:
    em, out, _ = _emitter()
    em.stage("deploy", "received", "running")
    em.progress("deploy", "upload", 50, 100)
    em.result("deploy", ok=True, exit_code=0)
    kinds = {json.loads(line)["event"] for line in _lines(out)}
    assert kinds == {"stage", "progress", "result"}


def test_non_tty_degrades_to_milestones() -> None:
    em, out, _ = _emitter(is_tty=False)
    for sent in range(0, 101):
        em.progress("deploy", "upload", sent, 100)
    percents = [int(json.loads(line)["sent_bytes"]) for line in _lines(out) if json.loads(line)["event"] == "progress"]
    assert percents == [25, 50, 75, 100]


def test_tty_reports_every_progress_call() -> None:
    em, out, _ = _emitter(is_tty=True)
    for sent in (10, 20, 30):
        em.progress("deploy", "upload", sent, 100)
    assert len([line for line in _lines(out) if json.loads(line)["event"] == "progress"]) == 3


def test_mask_never_emits_key_material() -> None:
    em, out, err = _emitter()
    em.stage("deploy", "received", "running", failure={"message": FAKE_KEY, "details": {"header": FAKE_KEY}})
    em.info(f"Authorization: Bearer {FAKE_KEY}")
    em.result("deploy", ok=False, exit_code=4, data={"echo": FAKE_KEY})
    blob = out.getvalue() + err.getvalue()
    assert FAKE_KEY not in blob
    assert "bs-sak-****" in blob


def test_verbose_masks_authorization_header() -> None:
    em, _, err = _emitter(verbose=True)
    em.debug(f"GET /api/v2/auth/whoami 200 12ms Authorization: Bearer {FAKE_KEY}")
    text = err.getvalue()
    assert FAKE_KEY not in text
    assert "/api/v2/auth/whoami" in text and "200" in text


def test_debug_is_silent_without_verbose() -> None:
    em, _, err = _emitter(verbose=False)
    em.debug("should not appear")
    assert err.getvalue() == ""


def test_scan_hits_print_file_line_without_value() -> None:
    from bisheng_cli.output import format_scan_hits

    hits = [{"rule_id": "generic-key", "name_i18n_key": "scan.generic_key", "file": "app/conf.py", "line": 12}]
    text = format_scan_hits(hits)
    assert "app/conf.py:12" in text
    # The server deliberately withholds even a redacted value; the CLI must not
    # reopen the local file to "helpfully" put it back.
    assert "value" not in text and FAKE_KEY not in text


def test_utf8_wrapper_survives_gbk_console() -> None:
    raw = io.BytesIO()
    console = io.TextIOWrapper(raw, encoding="cp936", errors="strict", write_through=True)
    wrapped = wrap_stream(console)
    wrapped.write("缺 app:manage 位，请联系管理员 — 甯\n")
    wrapped.flush()
    assert raw.getvalue()


def test_unknown_stage_is_printed_verbatim() -> None:
    assert stage_label("received") == STAGE_LABELS["received"]
    assert stage_label("brand_new_stage") == "brand_new_stage"


@pytest.mark.parametrize("text", ["nothing to mask", ""])
def test_mask_is_identity_on_clean_text(text: str) -> None:
    assert mask(text) == text
