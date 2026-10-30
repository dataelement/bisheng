"""171 看板 component/query 接口对拍.

DASHBOARD_QUERY_MODE=capture 把当前线上响应写成基线.
DASHBOARD_QUERY_MODE=compare 用同一批请求重放, 数字和展示名必须一致.
只在 BISHENG_E2E=1 时连接 171.
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("BISHENG_E2E") != "1",
    reason="只在明确跑 e2e 时连接毕昇和 171",
)

CHINA = ZoneInfo("Asia/Shanghai")
ROOT = Path(__file__).resolve().parent
BASELINE_PATH = Path(os.environ.get("DASHBOARD_QUERY_BASELINE", ROOT / "baseline.json"))
MODE = os.environ.get("DASHBOARD_QUERY_MODE", "compare")
NON_CHART_TYPES = {"query", "dimension-filter", "filter"}
DOCUMENT_METRICS = (
    "total_file_count",
    "new_file_count",
    "knowledge_contribution_ratio",
    "called_document_count",
    "document_usage_ratio",
)
DATASETS = (
    "mid_user_increment",
    "mid_active_user",
    "mid_app_increment",
    "mid_sessions_increment",
    "mid_session_run_dtl",
    "mid_tool_call_dtl",
    "mid_knowledge_increment",
    "mid_knowledge_file_increment",
    "mid_knowledge_space_content_stat",
    "mid_doc_parse_dtl",
    "mid_model_call_dtl",
    "mid_user_interact_dtl",
    "mid_realtime_qa_question_fact",
    "mid_user_daily_participation",
)
LOGIN_METRICS = (
    "participation_rate",
    "logged_in_employee_count",
    "active_employee_count",
)


def _engine():
    from sqlalchemy import create_engine

    from bisheng.common.services.config_service import settings

    return create_engine(settings.database_url)


def _admin_token() -> str:
    from sqlalchemy import text

    from bisheng.user.domain.services.auth import AuthJwt

    with _engine().connect() as conn:
        row = conn.execute(
            text(
                "SELECT user_name, token_version FROM user WHERE user_id = 1 AND `delete` = 0"
            )
        ).one()
    return AuthJwt().create_access_token(
        {
            "user_id": 1,
            "user_name": row.user_name,
            "tenant_id": 1,
            "token_version": int(row.token_version or 0),
        }
    )


def _access_token() -> str:
    token = os.environ.get("BISHENG_E2E_TOKEN", "").strip()
    token_file = os.environ.get("BISHENG_E2E_TOKEN_FILE", "").strip()
    if not token and token_file:
        token = Path(token_file).read_text(encoding="utf-8").strip()
    return token or _admin_token()


def _client():
    import httpx

    base = os.environ.get("BISHENG_BASE_URL", "http://192.168.106.171:7860").rstrip("/")
    return httpx.Client(
        base_url=base,
        timeout=float(os.environ.get("DASHBOARD_QUERY_TIMEOUT", "300")),
        cookies={"access_token_cookie": _access_token()},
    )


def _frozen_window() -> dict:
    now = datetime.now(CHINA)
    end = datetime(now.year, now.month, now.day, 23, 59, 59, tzinfo=CHINA)
    start = end - timedelta(days=6)
    return {
        "mode": "fixed",
        "type": "custom",
        "startDate": int(start.timestamp()),
        "endDate": int(end.timestamp()),
    }


def _rows(payload: dict) -> list:
    data = payload.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        return data["data"]
    return []


def _linked_filters(components: list[dict], chart_id: str) -> tuple[list, list]:
    time_filters = []
    dimension_filters = []
    for component in components:
        config = component.get("data_config") or {}
        linked = config.get("linkedComponentIds") or []
        if chart_id not in linked:
            continue
        if component.get("type") == "query":
            conditions = config.get("queryConditions") or {}
            if conditions.get("hasDefaultValue") and conditions.get("defaultValue"):
                time_filters.append(conditions["defaultValue"])
            for field in config.get("dimensionFields") or []:
                values = field.get("defaultValues") or []
                if values:
                    dimension_filters.append(
                        {"fieldId": field.get("fieldId"), "values": values}
                    )
        if component.get("type") == "dimension-filter":
            for field in config.get("fields") or []:
                values = field.get("defaultValues") or []
                if values:
                    dimension_filters.append(
                        {"fieldId": field.get("fieldId"), "values": values}
                    )
    return time_filters, dimension_filters


def _is_chart(component: dict) -> bool:
    if component.get("type") in NON_CHART_TYPES:
        return False
    metrics = (component.get("data_config") or {}).get("metrics") or []
    return bool(metrics)


def _supplement(
    dashboard_id: int, dataset: str, metric: str, *, filters=None, dimensions=None
) -> dict:
    dimension_name = "-".join(item["fieldId"] for item in dimensions or []) or "none"
    filter_name = "-".join(item["fieldId"] for item in filters or []) or "none"
    return {
        "name": f"supplement-{dataset}-{metric}-{dimension_name}-{filter_name}",
        "payload": {
            "dashboard_id": dashboard_id,
            "component_data": {
                "dashboard_id": dashboard_id,
                "id": "e2e-supplement",
                "title": "e2e",
                "type": "line",
                "dataset_code": dataset,
                "style_config": {},
                "data_config": {
                    "metrics": [{"fieldId": metric, "isVirtual": True}],
                    "dimensions": dimensions or [],
                    "filters": filters or [],
                    "filtersLogic": "and",
                    "timeFilter": _frozen_window(),
                    "isConfigured": True,
                },
            },
            "time_filters": [],
            "dimension_filters": [],
        },
    }


def _dataset_metrics() -> dict[str, list[str]]:
    from bisheng.telemetry_search.domain.init_dataset import DASHBOARD_DATASET

    found = {}
    for dataset in DASHBOARD_DATASET:
        metrics = dataset.schema_config.get("metrics") or []
        found[dataset.dataset_code] = [
            item.get("field") for item in metrics if item.get("field")
        ]
    return found


def _dashboard_ids() -> list[int]:
    from sqlalchemy import text

    with _engine().connect() as conn:
        return [
            int(row[0])
            for row in conn.execute(text("SELECT id FROM dashboard ORDER BY id"))
        ]


def collect_cases(client) -> list[dict]:
    cases = []
    covered: set[tuple[str, str]] = set()
    anchor = None
    for dashboard_id in _dashboard_ids():
        detail = client.get(f"/api/v1/telemetry/dashboard/{dashboard_id}")
        if detail.status_code != 200:
            continue
        payload = detail.json()
        if payload.get("status_code") != 200 or not isinstance(
            payload.get("data"), dict
        ):
            continue
        dashboard = payload["data"]
        anchor = anchor or dashboard["id"]
        components = dashboard.get("components") or []
        for chart in components:
            if not _is_chart(chart):
                continue
            time_filters, dimension_filters = _linked_filters(components, chart["id"])
            config_text = json.dumps(chart.get("data_config") or {}, ensure_ascii=False)
            cases.append(
                {
                    "name": f"dashboard-{dashboard['id']}-{chart['id']}",
                    "dataset": chart.get("dataset_code"),
                    "metrics": [
                        metric.get("fieldId")
                        for metric in (chart.get("data_config") or {}).get("metrics")
                        or []
                    ],
                    "has_level_day": "space_level_name" in config_text
                    and "timestamp" in config_text,
                    "payload": {
                        "dashboard_id": dashboard["id"],
                        "component_id": chart["id"],
                        "time_filters": time_filters,
                        "dimension_filters": dimension_filters,
                    },
                }
            )
            for metric in (chart.get("data_config") or {}).get("metrics") or []:
                covered.add((chart.get("dataset_code"), metric.get("fieldId")))
    assert anchor is not None, "171 上没有可访问的看板"
    catalog = _dataset_metrics()
    window_dimensions = [{"fieldId": "timestamp", "timeGranularity": "day"}]
    level_filter = [
        {
            "id": "e2e-level",
            "fieldId": "space_level_name",
            "operator": "in",
            "value": ["公共库", "团队库", "科室库", "部门库"],
        }
    ]
    has_level_day = any(
        case.get("dataset") == "mid_knowledge_space_content_stat"
        and "total_file_count" in (case.get("metrics") or [])
        and case.get("has_level_day")
        for case in cases
    )
    for dataset in DATASETS:
        metrics = catalog.get(dataset) or []
        if dataset == "mid_user_daily_participation":
            required = [
                metric
                for metric in LOGIN_METRICS
                if metric in metrics and (dataset, metric) not in covered
            ]
        elif dataset == "mid_knowledge_space_content_stat":
            required = [
                metric
                for metric in DOCUMENT_METRICS
                if (dataset, metric) not in covered
            ]
        else:
            required = (
                [] if any(code == dataset for code, _metric in covered) else metrics[:1]
            )
        for metric in required:
            cases.append(
                _supplement(anchor, dataset, metric, dimensions=window_dimensions)
            )
    if not has_level_day:
        cases.append(
            _supplement(
                anchor,
                "mid_knowledge_space_content_stat",
                "total_file_count",
                dimensions=window_dimensions,
                filters=level_filter,
            )
        )
    return cases


def _execute(client, case: dict) -> dict:
    response = client.post(
        "/api/v1/telemetry/dashboard/component/query", json=case["payload"]
    )
    content_type = response.headers.get("content-type", "")
    if "json" not in content_type:
        return {
            "http_status": response.status_code,
            "gateway": True,
            "body": response.text[:180],
        }
    body = response.json()
    data = body.get("data") if isinstance(body, dict) else None
    return {
        "http_status": response.status_code,
        "gateway": False,
        "status_code": body.get("status_code") if isinstance(body, dict) else None,
        "status_message": body.get("status_message")
        if isinstance(body, dict)
        else None,
        "dimensions": (data or {}).get("dimensions")
        if isinstance(data, dict)
        else None,
        "value": (data or {}).get("value") if isinstance(data, dict) else None,
        "rollups": (data or {}).get("rollups") if isinstance(data, dict) else None,
        "dimension_labels": (data or {}).get("dimension_labels")
        if isinstance(data, dict)
        else None,
    }


def _same(left, right) -> bool:
    if isinstance(left, float) or isinstance(right, float):
        if left is None or right is None:
            return left is right
        return math.isclose(float(left), float(right), rel_tol=0, abs_tol=1e-9)
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            _same(left[key], right[key]) for key in left
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _same(a, b) for a, b in zip(left, right, strict=True)
        )
    return left == right


def test_component_query_parity():
    client = _client()
    try:
        if MODE == "capture":
            cases = collect_cases(client)
            recorded = []
            for case in cases:
                print(f"capture {case['name']}", flush=True)
                recorded.append({**case, "result": _execute(client, case)})
            BASELINE_PATH.write_text(
                json.dumps(recorded, ensure_ascii=False), encoding="utf-8"
            )
            assert recorded, "没有采集到任何图表请求"
            return
        assert BASELINE_PATH.is_file(), f"缺少基线 {BASELINE_PATH}"
        recorded = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
        mismatches = []
        for case in recorded:
            actual = _execute(client, case)
            expected = case["result"]
            if expected.get("gateway") and expected.get("http_status") in {
                502,
                503,
                504,
            }:
                if actual.get("http_status") != 200 or actual.get("status_code") != 200:
                    mismatches.append(
                        (
                            case["name"],
                            "gateway-recovered",
                            expected.get("http_status"),
                            actual,
                        )
                    )
                elif not isinstance(actual.get("value"), list):
                    mismatches.append((case["name"], "missing-value", actual))
                continue
            if not _same(expected, actual):
                mismatches.append(
                    (
                        case["name"],
                        expected.get("status_code"),
                        actual.get("status_code"),
                    )
                )
        assert not mismatches, mismatches[:8]
    finally:
        client.close()


def test_document_export_still_returns_file():
    if MODE != "compare":
        pytest.skip("导出只在新版本重放时检查")
    client = _client()
    try:
        chart = None
        dashboard_id = None
        for candidate in (10, 11, 12, 14, 15, 16):
            detail = client.get(f"/api/v1/telemetry/dashboard/{candidate}")
            if detail.status_code != 200:
                continue
            dashboard = detail.json().get("data") or {}
            for item in dashboard.get("components") or []:
                metrics = (item.get("data_config") or {}).get("metrics") or []
                if any(
                    metric.get("fieldId") == "total_file_count" for metric in metrics
                ):
                    chart = item
                    dashboard_id = candidate
                    break
            if chart:
                break
        assert chart is not None and dashboard_id is not None
        response = client.post(
            f"/api/v1/telemetry/dashboard/component/{chart['id']}/export-all",
            json={
                "dashboard_id": dashboard_id,
                "time_filters": [],
                "dimension_filters": [],
            },
        )
        assert response.status_code == 200, response.text[:400]
        body = response.json()
        assert body.get("status_code") == 200, body
        assert body["data"]["file_url"]
    finally:
        client.close()
