"""Exercise live loopback business APIs and published deterministic Skill code.

This does NOT run a BISHENG Agent, authenticate a platform user, call an LLM, or
prove the platform selected/read a Skill. Native report verification is never
fabricated: pass --verified-report-id only after a real platform run completes.
"""

from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def http(base, path, payload=None, token=None, expected=200):
    if urlsplit(base).hostname != "127.0.0.1":
        raise ValueError("Acceptance driver permits loopback only")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = Request(
        base.rstrip("/") + path,
        None if payload is None else json.dumps(payload).encode(),
        headers,
    )
    try:
        with urlopen(req, timeout=40) as response:
            code, raw = response.status, response.read()
    except HTTPError as error:
        code, raw = error.code, error.read()
    assert code == expected, (
        f"HTTP status {code}, expected {expected} for {path.split('?')[0]}"
    )
    try:
        return json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return raw


def env_value(runtime, name, key):
    values = dict(
        line.split("=", 1)
        for line in (runtime / name).read_text().splitlines()
        if "=" in line
    )
    return values[key]


def execute(script, request, workspace, *arguments, environment=None):
    process = subprocess.run(
        [sys.executable, str(script), *arguments],
        input=json.dumps(request).encode(),
        capture_output=True,
        cwd=workspace,
        env=environment or os.environ.copy(),
        timeout=40,
    )
    assert process.returncode == 0, f"Fixed executor returned {process.returncode}"
    return json.loads(process.stdout)


def ended(result):
    assert (
        result["terminal"] is True
        and result["next_action"] == "none"
        and result["answer"]
    )
    assert result.get("outcome") not in {
        "execution_error",
        "api_error",
        "state_error",
        "invalid_request",
        "file_or_state_error",
    }, result.get("outcome")


def procurement(args, runtime, work):
    credentials = json.loads((runtime / "procurement/credentials.json").read_text())
    token = http(args.procurement_base, "/authapi/getToken", credentials)[
        "access_token"
    ]
    path = "/openapi/tic-definition/integrationInterface/call?functionCode=mock_procurement_history_v1"
    script = runtime / "skills/procurement-history/scripts/procurement.py"
    results = []
    for model, buyer, supplier in [
        ("DEMO-QPL-001", "空客", "合成QPL供应商甲"),
        ("DEMO-QSL-001", "商飞", "合成QSL供应商甲"),
    ]:
        response = http(
            args.procurement_base,
            path,
            {"requestQuery": {"model": model, "match_mode": "exact"}},
            token,
        )
        assert response["data"]["data"]["totalElements"] == 2
        target = work / ("uploads/procurement-api/" + model + ".json")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(response, ensure_ascii=False))
        value = execute(
            script,
            {
                "action": "suppliers",
                "model": model,
                "match_mode": "exact",
                "page_files": [target.relative_to(work).as_posix()],
                "purchaser": buyer,
                "sort": "price_asc",
            },
            work,
        )
        ended(value)
        assert supplier in value["answer"]
        assert ("QPL" if buyer == "空客" else "QSL") in value["answer"]
        confirmed = execute(
            script, {"action": "confirm", "supplier_name": supplier}, work
        )
        ended(confirmed)
        ledger = execute(script, {"action": "confirmations"}, work)
        ended(ledger)
        # Read the deterministic confirmation id from the workspace, not an LLM claim.
        index = json.loads(
            (work / "uploads/procurement-runtime/confirmations/index.json").read_text()
        )
        ident = index["records"][-1]["id"]
        cancelled = execute(
            script, {"action": "unconfirm", "confirmation_id": ident}, work
        )
        ended(cancelled)
        assert "撤销" in cancelled["answer"]
        results.append(
            {
                "model": model,
                "buyer": buyer,
                "history_rows": 2,
                "confirmation_revoked": True,
            }
        )
    near = http(
        args.procurement_base,
        path,
        {"requestQuery": {"model": r"DEMO-NEAR-00[12]", "match_mode": "regex"}},
        token,
    )
    assert near["data"]["data"]["matchedModelCount"] == 2
    empty = http(
        args.procurement_base,
        path,
        {"requestQuery": {"model": "DEMO-ABSENT-999", "match_mode": "exact"}},
        token,
    )
    assert empty["data"]["data"]["totalElements"] == 0
    http(
        args.procurement_base,
        path,
        {"requestQuery": {"model": "DEMO-QPL-001"}},
        "invalid-local-token",
        expected=401,
    )
    return {
        "cases": results,
        "regex_models": 2,
        "empty_records": 0,
        "invalid_token_status": 401,
    }


def transport(args, runtime, work):
    token = env_value(runtime, "transport.env", "TRANSPORT_MOCK_TOKEN")
    dataset = json.loads((runtime / "transport/snapshot.json").read_text())
    seed_row = next(
        row for row in dataset["details"] if row["house_no"] == "DEMO-TRN-001"
    )
    seed_bill = next(
        bill for bill in dataset["bills"] if bill["bill_no"] == seed_row["bill_no"]
    )
    members = [
        row for row in dataset["details"] if row["bill_no"] == seed_bill["bill_no"]
    ]

    def call(request, context=""):
        return http(
            args.transport_native_base,
            "/transport/execute",
            {"request_json": json.dumps(request), "context_id": context},
            token,
        )

    history = call({"action": "history", "query": {"house_numbers": ["DEMO-TRN-001"]}})
    ended(history)
    assert (
        "DEMO-TRN-002" in history["answer"]
        and f"{seed_bill['foreign_total']:,}" in history["answer"]
    )
    assert history["bills"][0]["coverage_count"] == len(members)
    assert "recommendation" not in history, "Ordinary history must not recommend"
    detail = call({"action": "detail", "reference": "F01"}, history["context_id"])
    ended(detail)
    assert "DEMO-TB-001" in detail["answer"]
    inquiry = call(
        {
            "action": "inquiry",
            "target": {
                "origin": "JFK",
                "destination": "TFU",
                "model": "683-3-2/X-310A",
                "gross_weight_kg": 120,
                "length_cm": 107,
                "width_cm": 61,
                "height_cm": 61,
                "mode": "空运",
                "dangerous_goods": "危化品",
            },
        }
    )
    ended(inquiry)
    assert "合成运输商甲" in inquiry["answer"] and inquiry["recommendation"]
    shortcut = call({"action": "history", "query": {"house_numbers": ["ELC24018561"]}})
    ended(shortcut)
    assert (
        shortcut["counts"]["matched_details"] == 1 and "recommendation" not in shortcut
    )
    missing = call({"action": "inquiry", "target": {"origin": "JFK"}})
    assert missing["status"] == "user_clarification" and missing["terminal"] is True
    bad = call({"action": "detail", "reference": "F01"}, "f" * 48)
    assert bad["outcome"] == "expired_context" and bad["terminal"] is True
    http(
        args.transport_native_base,
        "/transport/execute",
        {"request_json": "{}", "context_id": ""},
        "invalid-local-token",
        expected=401,
    )
    return {
        "history_shared_members": len(members),
        "detail": True,
        "new_inquiry": True,
        "shortcut_synthetic_hit": True,
        "ordinary_history_has_no_recommendation": True,
        "clarification": True,
        "old_context_rejected": True,
        "invalid_token_status": 401,
    }


def customs(args, runtime, work):
    script = runtime / "skills/customs-history/scripts/tool_adapter.py"
    token = env_value(runtime, "customs.env", "CUSTOMS_MOCK_TOKEN")
    environment = {**os.environ, "CUSTOMS_MOCK_TOKEN": token}
    dataset = json.loads((runtime / "customs/snapshot.json").read_text())
    seed_row = next(
        row for row in dataset["details"] if row["house_no"] == "DEMO-CUS-001"
    )
    seed_bill = next(
        bill for bill in dataset["bills"] if bill["bill_no"] == seed_row["bill_no"]
    )
    members = [
        row for row in dataset["details"] if row["bill_no"] == seed_bill["bill_no"]
    ]

    def call(request):
        target = work / "customs-request.json"
        target.write_text(json.dumps({"request": request}))
        return execute(
            script,
            {},
            work,
            "--arguments-file",
            str(target),
            "--workspace",
            str(work),
            "--base-url",
            args.customs_base,
            environment=environment,
        )

    history = call({"action": "history", "query": {"house_numbers": ["DEMO-CUS-001"]}})
    ended(history)
    assert (
        history["bills"][0]["house_count"] == len({row["house_no"] for row in members})
        and f"{seed_bill['customs_fee_amount']:,}" in history["answer"]
    ), "Shared customs coverage or total differs"
    assert history["bills"][0]["customs_fee_amount"] == seed_bill["customs_fee_amount"]
    assert "recommendation" not in history, "Ordinary history must not recommend"
    # Bind the validated current query id, as the published backend adapter does.
    state = json.loads((work / "uploads/customs-runtime/session.json").read_text())
    detail = call(
        {"action": "detail", "reference": "F01", "query_id": state["query_id"]}
    )
    ended(detail)
    assert "DEMO-CB-001" in detail["answer"] and "DEMO-CUS-002" in detail["answer"], (
        "Customs detail lost complete shared membership"
    )
    inquiry = call(
        {
            "action": "inquiry",
            "target": {
                "destination": "PVG",
                "model": "BMS10-146 TYPE I",
                "gross_weight_kg": 100,
                "length_cm": 100,
                "width_cm": 80,
                "height_cm": 60,
                "package_count": 1,
                "dangerous_goods": "危化品",
            },
        }
    )
    ended(inquiry)
    assert "合成报关代理甲" in inquiry["answer"]
    for house, amount in (
        ("DFS26080009", 420),
        ("DEMO-CUS-ZERO", 0),
        ("DEMO-CUS-MISSING", None),
    ):
        result = call({"action": "history", "query": {"house_numbers": [house]}})
        ended(result)
        assert (
            result["counts"]["matched_details"] == 1 and "recommendation" not in result
        )
        assert result["bills"][0]["customs_fee_amount"] == amount
    missing = call({"action": "inquiry", "target": {"destination": "PVG"}})
    assert missing["status"] == "user_clarification" and missing["terminal"] is True
    path = "/openapi/tic-definition/integrationInterface/call?functionCode=mock_customs_history_v1"
    http(
        args.customs_base,
        path,
        {"requestQuery": {"conditions": {"house_numbers": ["DEMO-CUS-001"]}}},
        "invalid-local-token",
        expected=401,
    )
    return {
        "history_shared_members": len(members),
        "detail": True,
        "new_inquiry": True,
        "shortcut_synthetic_hit": True,
        "zero_and_missing_fee_distinguished": True,
        "ordinary_history_has_no_recommendation": True,
        "clarification": True,
        "invalid_token_status": 401,
    }


def forecast(args, runtime, work):
    http(args.forecast_base, "/api/health")
    http(args.forecast_base, "/api/catalog")
    results = []
    for spec, expected_state in (
        ("189A1002-1", "predicted"),
        ("BACB30YP8K9", "unpredictable"),
        ("DEMO-NO-HISTORY", "no_history"),
        ("ZERO-PRED-001", "predicted"),
    ):
        created = http(
            args.forecast_base,
            "/api/runs",
            {"spec": spec, "customer": "all", "start_month": "2026-12", "months": 2},
            expected=201,
        )
        runid, token = created["run_id"], created["token"]
        prepared = http(
            args.forecast_base,
            "/api/skill-execute",
            {
                "request_json": json.dumps(
                    {"run_id": runid, "token": token, "action": "prepare"}
                )
            },
        )
        assert (
            prepared.get("action") == "prepare"
            or prepared.get("receipt", {}).get("action") == "prepare"
        )
        assert prepared["facts"]["status"] == expected_state, "Forecast branch differs"
        if spec == "ZERO-PRED-001":
            assert prepared["facts"]["forecast"]["summary"]["quantity"] == 0
        # A raw API caller cannot manufacture a verified report.
        http(args.forecast_base, f"/api/reports/{runid}/result.json", expected=404)
        results.append({"spec": spec, "prepare": True, "unverified_report_status": 404})
    http(
        args.forecast_base,
        "/api/forecast?spec=TEST-API-ERROR&customer=all&start_month=2026-12&months=2",
        expected=503,
    )
    reports = "not_verified_no_native_run_supplied"
    if args.verified_report_id:
        assert re.fullmatch("[a-f0-9]{32}", args.verified_report_id)
        for name in ("report.html", "report.md", "result.json"):
            http(args.forecast_base, f"/api/reports/{args.verified_report_id}/{name}")
        reports = "three_native_report_formats_downloaded"
    return {"branches": results, "api_failure_status": 503, "reports": reports}


def orders(args, runtime, work):
    expected = json.loads(
        (runtime / "skills/order-tracking/assets/orders.json").read_text()
    )
    dataset = expected["orders"]
    assert dataset and all(order["mock"] is True for order in dataset)
    script = runtime / "skills/order-tracking/scripts/run.py"

    def call(**request):
        result = execute(script, {"as_of": expected["asOf"], **request}, work)
        assert result["action_applied"] is False
        return result

    pages = []
    for offset in range(0, len(dataset), 12):
        page = call(action="overview", limit=12, offset=offset)
        assert page["orders"] == [
            order["number"] for order in dataset[offset : offset + 12]
        ]
        pages.extend(page["orders"])
    assert pages == [order["number"] for order in dataset]
    suppliers = sorted({order["supplier"] for order in dataset})
    for supplier in suppliers:
        result = call(action="orders", supplier=supplier, window="all", limit=30)
        assert result["orders"] == [
            order["number"] for order in dataset if order["supplier"] == supplier
        ]
    for material in ("26DMAC", "ZDA601US"):
        result = call(action="orders", material=material, window="all", limit=30)
        matches = [
            order["number"]
            for order in dataset
            if any(material in line["part"] for line in order["lines"])
        ]
        assert matches and result["orders"] == matches
    asof = date.fromisoformat(expected["asOf"])
    for node, collection, field in (
        ("delivery", "lines", "due"),
        ("payment", "invoices", "due"),
        ("settlement", "settlements", "date"),
    ):
        for window in ("past", "today", "week", "month", "future", "missing"):

            def matches(value):
                if value is None:
                    return window == "missing"
                delta = (date.fromisoformat(value) - asof).days
                return {
                    "past": delta < 0,
                    "today": delta == 0,
                    "week": 0 <= delta <= 7,
                    "month": 0 <= delta <= 30,
                    "future": delta > 30,
                    "missing": False,
                }[window]

            selected = []
            for order in dataset:
                dates = {entry[field] for entry in order[collection]} - {None}
                if any(matches(value) for value in dates or {None}):
                    selected.append(order["number"])
            result = call(action="alerts", node=node, window=window, limit=30)
            assert result["orders"] == selected, (
                f"Order calendar filter differs: {node}/{window}"
            )
    multiple = next(
        order
        for order in dataset
        if len(order["lines"]) > 1 and len(order["invoices"]) > 1
    )
    detail = call(action="detail", order=multiple["number"])
    assert detail["orders"] == [multiple["number"]]
    assert all(
        invoice["number"] in detail["answer"] for invoice in multiple["invoices"]
    )
    assert call(action="detail")["orders"] == [multiple["number"]]
    assert call(action="detail", order="SYNTHETIC-ABSENT")["status"] == "waiting"
    assert call(action="detail")["status"] == "waiting"
    result = {
        "orders": len(dataset),
        "pages": (len(dataset) + 11) // 12,
        "synthetic_suppliers": len(suppliers),
        "calendar_filters": 18,
        "multiple_dates_and_context": True,
    }
    if args.orders_proxy_base:
        value = http(args.orders_proxy_base, "/api/zhgyl/orders")
        assert value == expected
        result.update(
            same_origin_orders=len(value["orders"]), same_dataset_as_skill=True
        )
    else:
        result["same_origin_proxy"] = "not_run_no_orders_proxy_base"
    return result


def source_fingerprint(runtime):
    digest = hashlib.sha256()
    count = 0
    for label, base in (
        ("source", ROOT),
        ("runtime-skills", runtime / "skills"),
        ("runtime-forecast", runtime / "forecast"),
    ):
        for path in sorted(base.rglob("*")):
            if (
                path.is_file()
                and (path.suffix == ".py" or path.name == "SKILL.md")
                and "__pycache__" not in path.parts
            ):
                digest.update(
                    (label + "/" + path.relative_to(base).as_posix()).encode()
                )
                digest.update(b"\0")
                digest.update(hashlib.sha256(path.read_bytes()).digest())
                count += 1
    return {"sha256": digest.hexdigest(), "files": count}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", required=True)
    parser.add_argument(
        "--group",
        choices=["all", "procurement", "transport", "customs", "forecast", "orders"],
        default="all",
    )
    for name, port in [
        ("procurement", 28768),
        ("transport-native", 28771),
        ("customs", 28770),
        ("forecast", 28786),
    ]:
        parser.add_argument("--" + name + "-base", default=f"http://127.0.0.1:{port}")
    parser.add_argument("--orders-proxy-base")
    parser.add_argument("--verified-report-id")
    parser.add_argument("--output")
    args = parser.parse_args()
    runtime = Path(args.runtime).resolve()
    before = source_fingerprint(runtime)
    results = {
        "scope": "real_local_http_and_direct_deterministic_code_only",
        "platform_skill_e2e": False,
        "groups": {},
    }
    with tempfile.TemporaryDirectory(prefix="business-http-", dir=runtime) as directory:
        for name in ("procurement", "transport", "customs", "forecast", "orders"):
            if args.group not in ("all", name):
                continue
            work = Path(directory) / name
            work.mkdir()
            try:
                result = globals()[name](args, runtime, work)
                results["groups"][name] = {
                    "passed": None if "not_run" in result else True,
                    **result,
                }
            except Exception as error:
                # Structural diagnostics only; urllib/request objects may carry credentials.
                results["groups"][name] = {
                    "passed": False,
                    "exception": type(error).__name__,
                    "reason": str(error)
                    if type(error) is AssertionError
                    else "See local dependency/service status",
                }
    results["tested_code"] = before
    results["source_unchanged_during_run"] = source_fingerprint(runtime) == before
    raw = json.dumps(results, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(raw)
    print(raw)
    raise SystemExit(
        0
        if all(group["passed"] is not False for group in results["groups"].values())
        else 1
    )


if __name__ == "__main__":
    main()
