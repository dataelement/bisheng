"""Prepare and run the F048 BENCH-01 permission performance contract.

The script only accepts a non-production environment and an explicitly pinned
OpenFGA Store.  It never creates or switches a Store, never runs the F048 data
migration, and never maintains an old/new authorization-model pair.  Historical
latency samples are read from the signed fixture; every live request uses the
single F048 model supplied by ``--model-id``.

Examples (run from ``src/backend``):

    PYTHONPATH=./ .venv/bin/python scripts/benchmark_f048_permission_paths.py \
      prepare --environment performance --api-url http://127.0.0.1:8080 \
      --store-id <dedicated-benchmark-store> --apply

    PYTHONPATH=./ .venv/bin/python scripts/benchmark_f048_permission_paths.py \
      run --environment performance --api-url http://127.0.0.1:8080 \
      --store-id <same-store> --model-id <prepare-output-model-id> \
      --openfga-log /path/to/openfga-benchmark.jsonl --output report.json

The bundled fixture is synthetic and can only exercise the harness.  A formal
release run must supply a checksum-pinned, production-derived sanitized fixture.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

import httpx

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from bisheng.core.openfga.authorization_model_f048 import (  # noqa: E402
    authorization_model_checksum,
    build_authorization_model_f048,
)

OPENFGA_VERSION = "1.15.1"
WRITE_BATCH_SIZE = 90
BATCH_CHECK_SIZES = (20, 50, 100)
CONTRACT_VERSION = "f048-bench-01-v1"
EXIT_OK = 0
EXIT_INVALID_CONTRACT = 2
EXIT_GATE_FAILED = 3
EXIT_RUNTIME_ERROR = 4
DEFAULT_FIXTURE = Path(_BACKEND_ROOT) / "test" / "permission" / "fixtures" / "f048_bench_contract.synthetic.json"
_PRODUCTION_ENVIRONMENTS = {
    "prod",
    "production",
    "live",
    "online",
    "正式",
    "生产",
}


class BenchmarkContractError(ValueError):
    """The fixture, environment, or runtime pin is not safe to execute."""


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def checksum(value: Any) -> str:
    return sha256(canonical_json(value)).hexdigest()


def contract_checksum(contract: dict[str, Any]) -> str:
    unsigned = dict(contract)
    unsigned.pop("contract_checksum", None)
    return checksum(unsigned)


def validate_environment(environment: str) -> str:
    normalized = environment.strip().casefold()
    if not normalized:
        raise BenchmarkContractError("environment is required")
    if normalized in _PRODUCTION_ENVIRONMENTS or "prod" in normalized:
        raise BenchmarkContractError(
            "BENCH-01 refuses production; use a dedicated implementation/release verification environment"
        )
    return normalized


def nearest_rank_percentile(values: Iterable[float], percentile: int) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise BenchmarkContractError("cannot calculate a percentile without samples")
    rank = max(1, math.ceil((percentile / 100) * len(ordered)))
    return round(ordered[rank - 1], 6)


def summarize(values: Iterable[float]) -> dict[str, float | int]:
    samples = tuple(float(value) for value in values)
    return {
        "count": len(samples),
        "p50_ms": nearest_rank_percentile(samples, 50),
        "p95_ms": nearest_rank_percentile(samples, 95),
        "p99_ms": nearest_rank_percentile(samples, 99),
    }


def object_keys(scenario: dict[str, Any]) -> list[str]:
    resource_type = str(scenario["resource_type"])
    prefix = str(scenario["resource_id_prefix"])
    return [f"{resource_type}:{prefix}{index:04d}" for index in range(1, int(scenario["result_count"]) + 1)]


def object_set_checksum(scenario: dict[str, Any]) -> str:
    return checksum(sorted(object_keys(scenario)))


def _base_release_tuples(profile: dict[str, Any]) -> list[dict[str, str]]:
    catalog = f"permission_catalog_release:{profile['catalog_release_id']}"
    release = f"permission_model_release:{profile['model_release_id']}"
    model = f"permission_model:{profile['permission_model_id']}"
    actions = sorted({str(item["action"]) for item in profile["scenarios"]})
    tuples = [
        {"user": "user:*", "relation": "active", "object": catalog},
        {"user": catalog, "relation": "catalog", "object": release},
        {"user": "user:*", "relation": "enabled_marker", "object": release},
        {"user": release, "relation": "release", "object": model},
    ]
    tuples.extend({"user": "user:*", "relation": f"{action}_marker", "object": release} for action in actions)
    return tuples


def _grant_tuples(
    *,
    profile: dict[str, Any],
    scenario: dict[str, Any],
    resource: str,
    actor: str,
    suffix: str = "",
) -> list[dict[str, str]]:
    model = f"permission_model:{profile['permission_model_id']}"
    grant_id = resource.replace(":", "-") + suffix
    grant = f"permission_grant:{grant_id}"
    subject_kind = str(scenario["subject_kind"])
    tuples = [
        {"user": model, "relation": "model", "object": grant},
        {"user": grant, "relation": "grant", "object": resource},
    ]
    if subject_kind == "department":
        department = f"department:bench-{scenario['name']}"
        tuples.extend(
            (
                {"user": actor, "relation": "member", "object": department},
                {
                    "user": f"{department}#member",
                    "relation": "ordinary_assignee",
                    "object": grant,
                },
            )
        )
    elif subject_kind == "group":
        group = f"user_group:bench-{scenario['name']}"
        tuples.extend(
            (
                {"user": actor, "relation": "member", "object": group},
                {
                    "user": f"{group}#member",
                    "relation": "ordinary_assignee",
                    "object": grant,
                },
            )
        )
    else:
        tuples.append(
            {
                "user": actor,
                "relation": "ordinary_assignee",
                "object": grant,
            }
        )
    return tuples


def build_dataset_tuples(contract: dict[str, Any]) -> list[dict[str, str]]:
    """Expand the compact fixture into deterministic OpenFGA tuple keys."""

    profile = contract["dataset"]["profile"]
    tuples = _base_release_tuples(profile)
    for scenario in profile["scenarios"]:
        actor = f"user:{scenario['actor_id']}"
        resources = object_keys(scenario)
        if scenario["subject_kind"] == "inherit":
            parent = f"knowledge_space:bench-parent-{scenario['name']}"
            parent_scenario = dict(scenario, subject_kind="direct")
            tuples.extend(
                _grant_tuples(
                    profile=profile,
                    scenario=parent_scenario,
                    resource=parent,
                    actor=actor,
                )
            )
            tuples.extend(
                (
                    {
                        "user": "user:*",
                        "relation": "permission_enabled",
                        "object": parent,
                    },
                    {
                        "user": "user:*",
                        "relation": "custom_mode",
                        "object": parent,
                    },
                )
            )
            for resource in resources:
                tuples.extend(
                    (
                        {
                            "user": "user:*",
                            "relation": "permission_enabled",
                            "object": resource,
                        },
                        {
                            "user": "user:*",
                            "relation": "inherit_mode",
                            "object": resource,
                        },
                        {"user": parent, "relation": "parent", "object": resource},
                    )
                )
            continue

        for resource in resources:
            tuples.extend(
                _grant_tuples(
                    profile=profile,
                    scenario=scenario,
                    resource=resource,
                    actor=actor,
                )
            )
            if scenario["subject_kind"] == "multi_grant":
                tuples.extend(
                    _grant_tuples(
                        profile=profile,
                        scenario=dict(scenario, subject_kind="direct"),
                        resource=resource,
                        actor=actor,
                        suffix="-second",
                    )
                )
            tuples.extend(
                (
                    {
                        "user": "user:*",
                        "relation": "permission_enabled",
                        "object": resource,
                    },
                    {
                        "user": "user:*",
                        "relation": "custom_mode",
                        "object": resource,
                    },
                )
            )
    deduplicated = {(item["user"], item["relation"], item["object"]): item for item in tuples}
    return [deduplicated[key] for key in sorted(deduplicated)]


def dataset_checksum(contract: dict[str, Any]) -> str:
    return checksum(build_dataset_tuples(contract))


def load_contract(
    path: Path,
    *,
    expected_checksum: str | None = None,
) -> dict[str, Any]:
    try:
        contract = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkContractError(f"cannot read BENCH-01 fixture: {exc}") from exc
    if contract.get("contract_version") != CONTRACT_VERSION:
        raise BenchmarkContractError("unsupported BENCH-01 contract_version")
    embedded = str(contract.get("contract_checksum", ""))
    calculated = contract_checksum(contract)
    if embedded != calculated:
        raise BenchmarkContractError(f"fixture checksum mismatch: expected {embedded}, calculated {calculated}")
    if expected_checksum and expected_checksum != calculated:
        raise BenchmarkContractError("fixture does not match --expected-contract-checksum")
    model_checksum = authorization_model_checksum(build_authorization_model_f048())
    if contract.get("authorization_model_checksum") != model_checksum:
        raise BenchmarkContractError("fixture authorization model checksum drift")
    calculated_dataset = dataset_checksum(contract)
    if contract["dataset"].get("dataset_checksum") != calculated_dataset:
        raise BenchmarkContractError("fixture expanded dataset checksum drift")
    scenarios = contract["dataset"]["profile"]["scenarios"]
    names = {str(item["name"]) for item in scenarios}
    required = {
        "direct",
        "department",
        "group",
        "inherit",
        "multi_grant",
        "result_10",
        "result_100",
        "result_1000",
    }
    if not required.issubset(names):
        raise BenchmarkContractError(f"fixture lacks required scenarios: {sorted(required - names)}")
    for scenario in scenarios:
        if scenario.get("expected_object_checksum") != object_set_checksum(scenario):
            raise BenchmarkContractError(f"object checksum drift for scenario {scenario['name']}")
    baseline_sizes = {int(value) for value in contract["baseline"]["batch_check_ms"]}
    if baseline_sizes != set(BATCH_CHECK_SIZES):
        raise BenchmarkContractError("baseline must contain BatchCheck 20/50/100")
    return contract


@dataclass(slots=True)
class RequestSample:
    operation: str
    scenario: str
    elapsed_ms: float
    request_ids: tuple[str, ...]
    error: str | None = None
    result_count: int | None = None
    result_checksum: str | None = None


class InstrumentedOpenFGAClient:
    """Minimal benchmark-only REST client with request-id correlation."""

    def __init__(
        self,
        *,
        api_url: str,
        store_id: str,
        model_id: str,
        timeout: float,
    ) -> None:
        self.store_id = store_id
        self.model_id = model_id
        self._http = httpx.AsyncClient(
            base_url=api_url.rstrip("/"),
            timeout=httpx.Timeout(timeout),
        )

    async def close(self) -> None:
        await self._http.aclose()

    async def health(self) -> None:
        response = await self._http.get("/healthz")
        response.raise_for_status()
        if response.json().get("status") != "SERVING":
            raise BenchmarkContractError("OpenFGA health status is not SERVING")

    async def verify_model(self, expected_checksum: str) -> None:
        response = await self._http.get(f"/stores/{self.store_id}/authorization-models/{self.model_id}")
        response.raise_for_status()
        value = response.json().get("authorization_model", response.json())
        model = {
            "schema_version": value["schema_version"],
            "type_definitions": value["type_definitions"],
        }
        if authorization_model_checksum(model) != expected_checksum:
            raise BenchmarkContractError("live OpenFGA model checksum mismatch")

    async def _post(self, path: str, body: dict[str, Any]) -> tuple[dict, str]:
        request_id = f"f048-bench-{uuid4().hex}"
        response = await self._http.post(
            path,
            json=body,
            headers={"X-Request-ID": request_id},
        )
        response.raise_for_status()
        return response.json(), request_id

    async def check(self, query: dict[str, str]) -> tuple[bool, str]:
        data, request_id = await self._post(
            f"/stores/{self.store_id}/check",
            {
                "tuple_key": query,
                "authorization_model_id": self.model_id,
            },
        )
        return bool(data.get("allowed")), request_id

    async def batch_check(
        self,
        queries: list[dict[str, str]],
    ) -> tuple[list[bool], str]:
        data, request_id = await self._post(
            f"/stores/{self.store_id}/batch-check",
            {
                "authorization_model_id": self.model_id,
                "checks": [{"tuple_key": query, "correlation_id": str(index)} for index, query in enumerate(queries)],
            },
        )
        result = data.get("result", {})
        return [bool(result.get(str(index), {}).get("allowed")) for index in range(len(queries))], request_id

    async def list_objects(
        self,
        *,
        user: str,
        relation: str,
        resource_type: str,
    ) -> tuple[list[str], str]:
        data, request_id = await self._post(
            f"/stores/{self.store_id}/list-objects",
            {
                "user": user,
                "relation": relation,
                "type": resource_type,
                "authorization_model_id": self.model_id,
            },
        )
        return list(data.get("objects", ())), request_id


class DatasetPreparer:
    def __init__(self, *, api_url: str, store_id: str, timeout: float) -> None:
        self.store_id = store_id
        self._http = httpx.AsyncClient(
            base_url=api_url.rstrip("/"),
            timeout=httpx.Timeout(timeout),
        )

    async def close(self) -> None:
        await self._http.aclose()

    async def prepare(self, contract: dict[str, Any]) -> dict[str, Any]:
        health = await self._http.get("/healthz")
        health.raise_for_status()
        model = build_authorization_model_f048()
        response = await self._http.post(
            f"/stores/{self.store_id}/authorization-models",
            json=model,
        )
        response.raise_for_status()
        model_id = response.json()["authorization_model_id"]
        tuples = build_dataset_tuples(contract)
        for offset in range(0, len(tuples), WRITE_BATCH_SIZE):
            batch = tuples[offset : offset + WRITE_BATCH_SIZE]
            write = await self._http.post(
                f"/stores/{self.store_id}/write",
                json={
                    "authorization_model_id": model_id,
                    "writes": {"tuple_keys": batch},
                },
            )
            write.raise_for_status()
        return {
            "store_id": self.store_id,
            "model_id": model_id,
            "authorization_model_checksum": authorization_model_checksum(model),
            "dataset_checksum": dataset_checksum(contract),
            "tuple_count": len(tuples),
        }


def _scenario_map(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item["name"]): item for item in contract["dataset"]["profile"]["scenarios"]}


def _query(scenario: dict[str, Any], object_key: str) -> dict[str, str]:
    return {
        "user": f"user:{scenario['actor_id']}",
        "relation": f"can_{scenario['action']}",
        "object": object_key,
    }


async def _timed_call(
    *,
    operation: str,
    scenario: str,
    call,
    validate,
) -> RequestSample:
    started = perf_counter()
    try:
        result, request_id = await call()
        validate(result)
        return RequestSample(
            operation=operation,
            scenario=scenario,
            elapsed_ms=(perf_counter() - started) * 1000,
            request_ids=(request_id,),
            result_count=(len(result) if isinstance(result, list) else None),
            result_checksum=(checksum(sorted(result)) if isinstance(result, list) else None),
        )
    except Exception as exc:
        return RequestSample(
            operation=operation,
            scenario=scenario,
            elapsed_ms=(perf_counter() - started) * 1000,
            request_ids=(),
            error=f"{type(exc).__name__}: {exc}",
        )


async def run_workloads(
    client: InstrumentedOpenFGAClient,
    contract: dict[str, Any],
    *,
    iterations: int,
    warmup: int,
) -> list[RequestSample]:
    scenarios = _scenario_map(contract)
    samples: list[RequestSample] = []
    await client.health()
    await client.verify_model(contract["authorization_model_checksum"])

    async def run_once(record: bool) -> None:
        for name, scenario in scenarios.items():
            first = object_keys(scenario)[0]
            sample = await _timed_call(
                operation="check",
                scenario=name,
                call=lambda s=scenario, o=first: client.check(_query(s, o)),
                validate=lambda allowed: (
                    None if allowed else (_ for _ in ()).throw(BenchmarkContractError("expected Check ALLOW"))
                ),
            )
            if record:
                samples.append(sample)

        batch_scenario = scenarios["result_1000"]
        batch_objects = object_keys(batch_scenario)
        for size in BATCH_CHECK_SIZES:
            queries = [_query(batch_scenario, object_key) for object_key in batch_objects[:size]]
            sample = await _timed_call(
                operation="batch_check",
                scenario=str(size),
                call=lambda q=queries: client.batch_check(q),
                validate=lambda allowed, expected=size: (
                    None
                    if len(allowed) == expected and all(allowed)
                    else (_ for _ in ()).throw(BenchmarkContractError(f"BatchCheck {expected} result mismatch"))
                ),
            )
            if record:
                samples.append(sample)

        for name, scenario in scenarios.items():
            expected_objects = object_keys(scenario)
            sample = await _timed_call(
                operation="list_objects",
                scenario=name,
                call=lambda s=scenario: client.list_objects(
                    user=f"user:{s['actor_id']}",
                    relation=f"can_{s['action']}",
                    resource_type=str(s["resource_type"]),
                ),
                validate=lambda objects, expected=expected_objects: (
                    None
                    if sorted(objects) == sorted(expected)
                    else (_ for _ in ()).throw(BenchmarkContractError("ListObjects result set mismatch or truncation"))
                ),
            )
            if record:
                samples.append(sample)

        cursor_contract = contract["dataset"]["profile"]["business_cursor"]
        cursor_scenario = scenarios[str(cursor_contract["scenario"])]
        candidates = object_keys(cursor_scenario)[: int(cursor_contract["candidate_count"])]
        page_size = int(cursor_contract["page_size"])
        started = perf_counter()
        request_ids: list[str] = []
        visible: list[str] = []
        error: str | None = None
        try:
            for offset in range(0, len(candidates), page_size):
                page = candidates[offset : offset + page_size]
                allowed, request_id = await client.batch_check([_query(cursor_scenario, item) for item in page])
                request_ids.append(request_id)
                visible.extend(item for item, is_allowed in zip(page, allowed, strict=True) if is_allowed)
            if visible != candidates:
                raise BenchmarkContractError("business cursor fingerprint mismatch")
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        if record:
            samples.append(
                RequestSample(
                    operation="business_cursor",
                    scenario=str(cursor_contract["scenario"]),
                    elapsed_ms=(perf_counter() - started) * 1000,
                    request_ids=tuple(request_ids),
                    error=error,
                    result_count=len(visible),
                    result_checksum=checksum(visible),
                )
            )

    for _ in range(warmup):
        await run_once(False)
    for _ in range(iterations):
        await run_once(True)
    return samples


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _merged_log_fields(value: dict[str, Any]) -> dict[str, Any]:
    merged = dict(value)
    for key in ("fields", "attributes", "resource", "body"):
        nested = value.get(key)
        if isinstance(nested, dict):
            merged.update(nested)
    return merged


def read_openfga_metrics(
    path: Path,
    request_ids: set[str],
) -> dict[str, dict[str, int]]:
    metrics: dict[str, dict[str, int]] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise BenchmarkContractError(f"cannot read OpenFGA JSON log: {exc}") from exc
    for line in lines:
        try:
            fields = _merged_log_fields(json.loads(line))
        except (json.JSONDecodeError, TypeError):
            continue
        request_id = str(fields.get("request_id") or fields.get("request.id") or fields.get("x-request-id") or "")
        if request_id not in request_ids:
            continue
        dispatch = _coerce_int(fields.get("dispatch_count"))
        reads = _coerce_int(fields.get("datastore_query_count") or fields.get("datastore_read_count"))
        if dispatch is not None and reads is not None:
            metrics[request_id] = {
                "dispatch_count": dispatch,
                "datastore_query_count": reads,
            }
    return metrics


def _sample_payload(sample: RequestSample) -> dict[str, Any]:
    return {
        "operation": sample.operation,
        "scenario": sample.scenario,
        "elapsed_ms": round(sample.elapsed_ms, 6),
        "request_ids": list(sample.request_ids),
        "error": sample.error,
        "result_count": sample.result_count,
        "result_checksum": sample.result_checksum,
    }


def evaluate(
    contract: dict[str, Any],
    samples: list[RequestSample],
    metrics: dict[str, dict[str, int]],
) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[RequestSample]] = defaultdict(list)
    for sample in samples:
        grouped[(sample.operation, sample.scenario)].append(sample)
    successful = [sample for sample in samples if sample.error is None]
    error_rate = 1 - (len(successful) / len(samples)) if samples else 1.0
    baseline = contract["baseline"]
    limits = contract["limits"]

    check_values = [sample.elapsed_ms for sample in successful if sample.operation == "check"]
    check_summary = summarize(check_values)
    old_check = summarize(baseline["check_ms"])
    check_limit = max(
        old_check["p95_ms"] * float(limits["check_p95_multiplier"]),
        old_check["p95_ms"] + float(limits["check_p95_absolute_ms"]),
    )
    check_gate = check_summary["p95_ms"] <= check_limit and error_rate < float(limits["max_error_rate"])

    batch_report: dict[str, Any] = {}
    batch_gate = True
    for size in BATCH_CHECK_SIZES:
        values = [
            sample.elapsed_ms
            for sample in successful
            if sample.operation == "batch_check" and sample.scenario == str(size)
        ]
        summary = summarize(values)
        old = summarize(baseline["batch_check_ms"][str(size)])
        limit = old["p95_ms"] * float(limits["batch_p95_multiplier"])
        passed = summary["p95_ms"] <= limit
        batch_gate = batch_gate and passed
        batch_report[str(size)] = {
            "new": summary,
            "baseline": old,
            "p95_limit_ms": round(limit, 6),
            "passed": passed,
        }

    scenario_by_name = _scenario_map(contract)
    list_report: dict[str, Any] = {}
    list_gate = True
    for name, scenario in scenario_by_name.items():
        group = grouped[("list_objects", name)]
        valid = bool(group) and all(
            sample.error is None
            and sample.result_count == int(scenario["result_count"])
            and sample.result_checksum == scenario["expected_object_checksum"]
            for sample in group
        )
        list_gate = list_gate and valid
        list_report[name] = {
            "latency": summarize(sample.elapsed_ms for sample in group if sample.error is None),
            "expected_count": int(scenario["result_count"]),
            "expected_checksum": scenario["expected_object_checksum"],
            "passed": valid,
        }

    cursor = [sample for sample in successful if sample.operation == "business_cursor"]
    cursor_summary = summarize(sample.elapsed_ms for sample in cursor)
    old_cursor = summarize(baseline["business_cursor_ms"])
    cursor_limit = old_cursor["p95_ms"] * float(limits["business_cursor_p95_multiplier"])
    cursor_contract = contract["dataset"]["profile"]["business_cursor"]
    expected_cursor_objects = object_keys(scenario_by_name[str(cursor_contract["scenario"])])[
        : int(cursor_contract["candidate_count"])
    ]
    cursor_gate = (
        cursor_summary["p95_ms"] <= cursor_limit
        and bool(cursor)
        and all(
            sample.result_count == len(expected_cursor_objects)
            and sample.result_checksum == checksum(expected_cursor_objects)
            for sample in cursor
        )
    )

    request_ids = {request_id for sample in samples for request_id in sample.request_ids}
    observed_ids = request_ids.intersection(metrics)
    observability_gate = bool(request_ids) and observed_ids == request_ids
    metric_report = {
        "request_count": len(request_ids),
        "observed_request_count": len(observed_ids),
        "dispatch": (summarize(metrics[item]["dispatch_count"] for item in observed_ids) if observed_ids else None),
        "datastore_reads": (
            summarize(metrics[item]["datastore_query_count"] for item in observed_ids) if observed_ids else None
        ),
        "passed": observability_gate,
    }
    fixture_gate = bool(contract["dataset"]["production_derived"])
    performance_passed = all(
        (
            check_gate,
            batch_gate,
            list_gate,
            cursor_gate,
            observability_gate,
            error_rate < float(limits["max_error_rate"]),
        )
    )
    return {
        "contract_version": contract["contract_version"],
        "contract_checksum": contract["contract_checksum"],
        "dataset_checksum": contract["dataset"]["dataset_checksum"],
        "authorization_model_checksum": contract["authorization_model_checksum"],
        "openfga_version": OPENFGA_VERSION,
        "dataset_source": contract["dataset"]["source"],
        "production_derived": fixture_gate,
        "error_rate": round(error_rate, 8),
        "check": {
            "new": check_summary,
            "baseline": old_check,
            "p95_limit_ms": round(check_limit, 6),
            "passed": check_gate,
        },
        "batch_check": batch_report,
        "list_objects": list_report,
        "business_cursor": {
            "new": cursor_summary,
            "baseline": old_cursor,
            "p95_limit_ms": round(cursor_limit, 6),
            "passed": cursor_gate,
        },
        "openfga_observability": metric_report,
        "performance_passed": performance_passed,
        "release_ready": performance_passed and fixture_gate,
        "samples": [_sample_payload(sample) for sample in samples],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "run"):
        command = subparsers.add_parser(name)
        command.add_argument("--environment", required=True)
        command.add_argument("--api-url", required=True)
        command.add_argument("--store-id", required=True)
        command.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
        command.add_argument("--expected-contract-checksum")
        command.add_argument("--timeout", type=float, default=30)
    prepare = subparsers.choices["prepare"]
    prepare.add_argument(
        "--apply",
        action="store_true",
        required=True,
        help="Required acknowledgement for benchmark Store writes",
    )
    run = subparsers.choices["run"]
    run.add_argument("--model-id", required=True)
    run.add_argument("--iterations", type=int)
    run.add_argument("--warmup", type=int)
    run.add_argument("--openfga-log", type=Path, required=True)
    run.add_argument("--output", type=Path)
    run.add_argument(
        "--allow-synthetic",
        action="store_true",
        help="Harness smoke only; report remains release_ready=false",
    )
    return parser.parse_args(argv)


async def execute(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    validate_environment(args.environment)
    contract = load_contract(
        args.fixture,
        expected_checksum=args.expected_contract_checksum,
    )
    if args.command == "prepare":
        preparer = DatasetPreparer(
            api_url=args.api_url,
            store_id=args.store_id,
            timeout=args.timeout,
        )
        try:
            return EXIT_OK, await preparer.prepare(contract)
        finally:
            await preparer.close()

    if not contract["dataset"]["production_derived"] and not args.allow_synthetic:
        raise BenchmarkContractError(
            "formal BENCH-01 requires a production-derived sanitized fixture; "
            "use --allow-synthetic only to smoke-test the harness"
        )
    iterations = args.iterations or int(contract["run"]["iterations"])
    warmup = args.warmup if args.warmup is not None else int(contract["run"]["warmup"])
    if iterations < 1 or warmup < 0:
        raise BenchmarkContractError("iterations must be positive and warmup non-negative")
    client = InstrumentedOpenFGAClient(
        api_url=args.api_url,
        store_id=args.store_id,
        model_id=args.model_id,
        timeout=args.timeout,
    )
    try:
        samples = await run_workloads(
            client,
            contract,
            iterations=iterations,
            warmup=warmup,
        )
    finally:
        await client.close()
    request_ids = {request_id for sample in samples for request_id in sample.request_ids}
    metrics = read_openfga_metrics(args.openfga_log, request_ids)
    report = evaluate(contract, samples, metrics)
    if args.output:
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    passed = report["performance_passed"] and (report["release_ready"] or args.allow_synthetic)
    return (EXIT_OK if passed else EXIT_GATE_FAILED), report


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        exit_code, payload = asyncio.run(execute(args))
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return exit_code
    except BenchmarkContractError as exc:
        print(f"BENCH-01 contract error: {exc}", file=sys.stderr)
        return EXIT_INVALID_CONTRACT
    except Exception:
        import traceback

        traceback.print_exc()
        return EXIT_RUNTIME_ERROR


if __name__ == "__main__":
    sys.exit(main())
