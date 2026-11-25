"""T056 artifact gate. Run with F026_REQUIRE_RELEASE=1 and F026_RELEASE_EVIDENCE=<CI bundle dir>.

This is a completeness/integrity check on trusted, reviewed CI artifacts, not a
signature verifier, deployment action or substitute for running the real tests.
"""

import hashlib
import json
import os
import re
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

LEDGER = {
    f"{case}[{db}]"
    for db in ("sqlite", "mysql", "dm8")
    for case in (
        "test_replay_and_same_key_different_hash",
        "test_expired_sender_can_only_be_reconciled_by_new_owner",
        "test_racing_claims_and_recovery_after_reconnect",
    )
}
LIVE = {
    f"test_fixture_{case}[{provider}]" for case in ("retrieval", "citation_click") for provider in ("native", "weknora")
}
QA = {f"TC-KSP-{n:03d}" for n in range(1, 56)}


def require(condition, problem):
    if not condition:
        raise ValueError(problem)


def blob(root, entry):
    # Evidence is an immutable CI export. Do not resolve URLs, execute commands,
    # traverse out of the bundle, or include fixture contents in error output.
    require(isinstance(entry, dict), "invalid artifact record")
    name = entry.get("file", "")
    require(isinstance(name, str) and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}", name), "invalid artifact name")
    p = root / name
    require(not p.is_symlink() and p.is_file() and 0 < p.stat().st_size <= 8_000_000, "artifact unavailable")
    data = p.read_bytes()
    require(hashlib.sha256(data).hexdigest() == entry.get("sha256"), "artifact digest mismatch")
    return data


def check_junit(data, required, module):
    xml = ET.fromstring(data)
    require(xml.tag in {"testsuite", "testsuites"}, "invalid JUnit root")
    # Each dedicated job runs exactly one suite. Reject reports whose counters
    # contradict their rows, including a zero-test report with copied case names.
    suites = list(xml.iter("testsuite"))
    require(len(suites) == 1, "expected one dedicated suite")
    suite = suites[0]
    require(suite.get("tests") == str(len(required)), "incorrect suite size")
    require(all(suite.get(k) == "0" for k in ("errors", "failures", "skipped")), "nonpassing release suite")
    require(not any(t.tag in {"skipped", "error", "failure"} for t in xml.iter()), "nonpassing release suite")
    rows = suite.findall("testcase")
    require(len(rows) == len(required) and {t.get("name") for t in rows} == required, "unexpected release case set")
    require(all((t.get("classname") or "").split(".")[-1] == module for t in rows), "unexpected release module")


def check_bundle(root):
    p = root / "manifest.json"
    require(
        not p.is_symlink() and p.is_file() and 0 < p.stat().st_size <= 128000, "release manifest missing or invalid"
    )
    m = json.loads(p.read_bytes())
    require(m.get("feature") == "F026" and m.get("environment") == "dedicated-integration", "wrong release environment")
    for k in ("bisheng_commit", "weknora_commit"):
        require(isinstance(m.get(k), str) and re.fullmatch("[0-9a-f]{40}", m[k]), "missing deployed commit")
    require(
        m["weknora_commit"] != "f17ee8a8da901bd658a4cb25f40b5fd41adbfdd7", "pristine upstream is not the extended build"
    )
    for k in ("bisheng_image", "weknora_image"):
        require(
            isinstance(m.get(k), str) and re.fullmatch("sha256:[0-9a-f]{64}", m[k]), "missing immutable deployed build"
        )
    ledger_run = json.loads(blob(root, m["ledger_provenance"]))
    require(
        ledger_run.get("bisheng_commit") == m["bisheng_commit"] and ledger_run.get("ledger") == m["ledger"],
        "ledger build or digest mismatch",
    )
    require(
        all(re.fullmatch(r"[1-9][0-9]*", str(ledger_run.get(k, ""))) for k in ("run_id", "run_attempt")),
        "missing ledger CI run",
    )
    check_junit(blob(root, m["ledger"]), LEDGER, "test_f026_ledger")
    check_junit(blob(root, m["live"]), LIVE, "test_e2e_f026_provider_release")
    # Manual/fault/UI cases must point to reviewed observations for the SAME run.
    qa = json.loads(blob(root, m["qa"]))
    for k in ("bisheng_commit", "weknora_commit", "bisheng_image", "weknora_image"):
        require(qa.get(k) == m[k], "QA build mismatch")
    require(qa.get("live") == m["live"], "live report does not match reviewed run")
    require(set(qa["cases"]) == QA, "incomplete acceptance matrix")
    for case in QA:
        row = qa["cases"][case]
        require(
            row.get("outcome") == "passed" and bool(str(row.get("reviewer") or "").strip()),
            f"{case}: missing reviewed outcome",
        )
        blob(root, row["observation"])


@pytest.mark.parametrize(
    "payload",
    [
        b"<testsuite/>",
        b'<testsuite><testcase classname="test_e2e_f026_provider_release" name="test_fixture_retrieval[weknora]"><skipped/></testcase></testsuite>',
    ],
)
def test_local_green_or_skipped_is_not_release_evidence(payload):
    with pytest.raises(ValueError):
        check_junit(payload, LIVE, "test_e2e_f026_provider_release")


@pytest.mark.parametrize("defect", ["false-count", "extra-row", "foreign-module"])
def test_misleading_junit_metadata_is_rejected(defect):
    suite = ET.Element("testsuite", tests=str(len(LIVE)), errors="0", failures="0", skipped="0")
    for name in sorted(LIVE):
        ET.SubElement(suite, "testcase", name=name, classname="test_e2e_f026_provider_release")
    if defect == "false-count":
        suite.set("tests", "0")
    elif defect == "extra-row":
        ET.SubElement(suite, "testcase", name="unrelated", classname="another_suite")
    else:
        suite[0].set("classname", "another_suite")
    with pytest.raises(ValueError):
        check_junit(ET.tostring(suite), LIVE, "test_e2e_f026_provider_release")


def test_artifact_substitution_is_rejected(tmp_path):
    (tmp_path / "result.xml").write_bytes(b"substituted")
    with pytest.raises(ValueError, match="digest"):
        blob(tmp_path, {"file": "result.xml", "sha256": "0" * 64})


def test_gate_checks_reviewed_build_and_fault_evidence(tmp_path):
    """Exercise the validator only; these temporary synthetic artifacts are never exported."""

    def put(name, value):
        data = value if isinstance(value, bytes) else json.dumps(value).encode()
        (tmp_path / name).write_bytes(data)
        return {"file": name, "sha256": hashlib.sha256(data).hexdigest()}

    def suite(module, names):
        root = ET.Element("testsuite", tests=str(len(names)), failures="0", skipped="0", errors="0")
        for name in names:
            ET.SubElement(root, "testcase", classname=module, name=name)
        return ET.tostring(root)

    builds = {
        f"{app}_{field}": prefix + digit * length
        for app, digit in [("bisheng", "1"), ("weknora", "2")]
        for field, prefix, length in [("commit", "", 40), ("image", "sha256:", 64)]
    }
    ledger = put("ledger.xml", suite("test_f026_ledger", LEDGER))
    live = put("live.xml", suite("test_e2e_f026_provider_release", LIVE))
    provenance = put(
        "provenance.json",
        {"bisheng_commit": builds["bisheng_commit"], "ledger": ledger, "run_id": "1", "run_attempt": "1"},
    )
    observation = put("synthetic.txt", b"parser test, not release evidence")
    qa = {
        **builds,
        "live": live,
        "cases": {case: {"outcome": "passed", "observation": observation, "reviewer": "fixture"} for case in QA},
    }
    manifest = {
        **builds,
        "feature": "F026",
        "environment": "dedicated-integration",
        "ledger": ledger,
        "ledger_provenance": provenance,
        "live": live,
        "qa": put("qa.json", qa),
    }
    put("manifest.json", manifest)
    check_bundle(tmp_path)
    del qa["cases"]["TC-KSP-046"]
    manifest["qa"] = put("qa.json", qa)
    put("manifest.json", manifest)
    with pytest.raises(ValueError, match="incomplete acceptance matrix"):
        check_bundle(tmp_path)


def test_target_release_evidence():
    directory = os.getenv("F026_RELEASE_EVIDENCE")
    if not directory:
        if os.getenv("F026_REQUIRE_RELEASE") == "1":
            pytest.fail("T056 BLOCKED: reviewed dedicated-environment evidence bundle missing", pytrace=False)
        pytest.skip("release gate not invoked: no dedicated-environment evidence bundle")
    try:
        check_bundle(Path(directory))
    except (OSError, ValueError, KeyError, TypeError, AttributeError, ET.ParseError) as exc:
        pytest.fail(f"T056 release evidence invalid ({type(exc).__name__})", pytrace=False)
