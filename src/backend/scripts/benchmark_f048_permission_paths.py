#!/usr/bin/env python3
"""Run the F048 single-slot visibility BENCH-01 contract.

The harness writes only to an explicitly supplied non-production OpenFGA
Store.  The compact fixture describes database cardinality independently from
the projected visibility tuples so 10k/100k business resource populations do
not require fake invisible OpenFGA objects.  Every enumeration consumes
StreamedListObjects to a normal EOF before it records a successful sample.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import re
import sys
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol
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
OPENFGA_BATCH_CHECK_LIMIT = 50
RESOURCE_SCALES = (10_000, 100_000)
VISIBLE_RESULT_SIZES = (10, 100, 1_000, 5_000)
SOURCE_KINDS = frozenset({"direct", "department", "group", "system", "multi_source"})
CONTRACT_VERSION = "f048-bench-01-v2"
EXIT_OK = 0
EXIT_INVALID_CONTRACT = 2
EXIT_GATE_FAILED = 3
EXIT_RUNTIME_ERROR = 4
DEFAULT_FIXTURE = (
    Path(_BACKEND_ROOT)
    / "test"
    / "permission"
    / "fixtures"
    / "f048_bench_contract.synthetic.json"
)
_PRODUCTION_ENVIRONMENTS = {
    "prod",
    "production",
    "live",
    "online",
    "正式",
    "生产",
}
_AB_RELATION_PATTERN = re.compile(r"(?:^|_)(?:slot_[ab]|visible_[ab]|visibility_switch)(?:$|_)")


class BenchmarkContractError(ValueError):
    """The fixture, environment, or runtime pin is unsafe or incomplete."""


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
    return [
        f"{resource_type}:{prefix}{index:05d}"
        for index in range(1, int(scenario["visible_count"]) + 1)
    ]


def object_set_checksum(scenario: dict[str, Any]) -> str:
    return checksum(sorted(object_keys(scenario)))


def _source_tuples(scenario: dict[str, Any]) -> list[dict[str, str]]:
    actor = f"user:{scenario['actor_id']}"
    name = str(scenario["name"])
    source_kind = str(scenario["source_kind"])
    tuples: list[dict[str, str]] = []
    subject = actor
    if source_kind in {"department", "multi_source"}:
        department = f"department:bench-{name}"
        tuples.append({"user": actor, "relation": "member", "object": department})
        if source_kind == "department":
            subject = f"{department}#member"
    if source_kind in {"group", "multi_source"}:
        group = f"user_group:bench-{name}"
        tuples.append({"user": actor, "relation": "member", "object": group})
        if source_kind == "group":
            subject = f"{group}#member"

    for resource in object_keys(scenario):
        if source_kind == "system":
            tuples.append(
                {
                    "user": "user:*",
                    "relation": "visible",
                    "object": resource,
                }
            )
        elif source_kind == "multi_source":
            tuples.extend(
                (
                    {"user": actor, "relation": "visible", "object": resource},
                    {
                        "user": f"department:bench-{name}#member",
                        "relation": "visible",
                        "object": resource,
                    },
                    {
                        "user": f"user_group:bench-{name}#member",
                        "relation": "visible",
                        "object": resource,
                    },
                )
            )
        else:
            tuples.append(
                {
                    "user": subject,
                    "relation": "visible",
                    "object": resource,
                }
            )
    return tuples


def build_dataset_tuples(contract: dict[str, Any]) -> list[dict[str, str]]:
    """Expand canonical shallow visibility sources into deterministic tuples."""

    tuples: list[dict[str, str]] = []
    for scenario in contract["dataset"]["scenarios"]:
        tuples.extend(_source_tuples(scenario))
        if scenario["source_kind"] != "system":
            for resource in object_keys(scenario):
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
        else:
            for resource in object_keys(scenario):
                tuples.append(
                    {
                        "user": "user:*",
                        "relation": "permission_enabled",
                        "object": resource,
                    }
                )
    deduplicated = {
        (item["user"], item["relation"], item["object"]): item for item in tuples
    }
    return [deduplicated[key] for key in sorted(deduplicated)]


def source_checksum(contract: dict[str, Any]) -> str:
    sources = [
        item
        for item in build_dataset_tuples(contract)
        if item["relation"] not in {"permission_enabled", "custom_mode"}
    ]
    return checksum(sources)


def visible_checksum(contract: dict[str, Any]) -> str:
    return checksum(
        {
            str(item["name"]): object_set_checksum(item)
            for item in contract["dataset"]["scenarios"]
        }
    )


def dataset_checksum(contract: dict[str, Any]) -> str:
    return checksum(build_dataset_tuples(contract))


def model_has_ab_slots(model: dict[str, Any]) -> bool:
    for definition in model["type_definitions"]:
        for relation in definition.get("relations", {}):
            if _AB_RELATION_PATTERN.search(relation):
                return True
    return False


def _validate_distribution(contract: dict[str, Any]) -> None:
    scenarios = contract["dataset"]["scenarios"]
    pairs = {
        (int(item["resource_count"]), int(item["visible_count"]))
        for item in scenarios
    }
    required_pairs = {
        (resource_count, visible_count)
        for resource_count in RESOURCE_SCALES
        for visible_count in VISIBLE_RESULT_SIZES
    }
    if not required_pairs.issubset(pairs):
        raise BenchmarkContractError(
            f"fixture lacks N_db/V scenarios: {sorted(required_pairs - pairs)}"
        )
    kinds = {str(item["source_kind"]) for item in scenarios}
    if not SOURCE_KINDS.issubset(kinds):
        raise BenchmarkContractError(
            f"fixture lacks source kinds: {sorted(SOURCE_KINDS - kinds)}"
        )
    if len({str(item["actor_id"]) for item in scenarios}) != len(scenarios):
        raise BenchmarkContractError("benchmark scenario actors must be unique")
    system_types = {
        str(item["resource_type"])
        for item in scenarios
        if item["source_kind"] == "system"
    }
    other_types = {
        str(item["resource_type"])
        for item in scenarios
        if item["source_kind"] != "system"
    }
    if system_types.intersection(other_types):
        raise BenchmarkContractError(
            "system wildcard scenarios must use isolated resource types"
        )


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
        raise BenchmarkContractError(
            f"fixture checksum mismatch: expected {embedded}, calculated {calculated}"
        )
    if expected_checksum and expected_checksum != calculated:
        raise BenchmarkContractError(
            "fixture does not match --expected-contract-checksum"
        )
    model = build_authorization_model_f048()
    if model_has_ab_slots(model):
        raise BenchmarkContractError("target model contains an A/B visibility relation")
    if contract.get("authorization_model_checksum") != authorization_model_checksum(model):
        raise BenchmarkContractError("fixture authorization model checksum drift")
    _validate_distribution(contract)
    for scenario in contract["dataset"]["scenarios"]:
        if int(scenario["visible_count"]) > int(scenario["resource_count"]):
            raise BenchmarkContractError(
                f"visible_count exceeds resource_count for {scenario['name']}"
            )
        if scenario.get("expected_object_checksum") != object_set_checksum(scenario):
            raise BenchmarkContractError(
                f"object checksum drift for scenario {scenario['name']}"
            )
    calculated_dataset = dataset_checksum(contract)
    if contract["dataset"].get("dataset_checksum") != calculated_dataset:
        raise BenchmarkContractError("fixture expanded dataset checksum drift")
    if contract["dataset"].get("source_checksum") != source_checksum(contract):
        raise BenchmarkContractError("fixture source checksum drift")
    if contract["dataset"].get("visible_checksum") != visible_checksum(contract):
        raise BenchmarkContractError("fixture visible checksum drift")
    if {int(value) for value in contract["limits"]["batch_check_p95_ms"]} != set(
        BATCH_CHECK_SIZES
    ):
        raise BenchmarkContractError("limits must contain BatchCheck 20/50/100")
    if {int(value) for value in contract["limits"]["stream_p95_ms"]} != set(
        VISIBLE_RESULT_SIZES
    ):
        raise BenchmarkContractError("limits must contain visible 10/100/1000/5000")
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
    stream_completed: bool | None = None
    strategy: str | None = None
    n_db: int | None = None
    visible_total: int | None = None
    selectivity: float | None = None
    candidate_pass_rate: float | None = None
    db_rows: int | None = None
    scanned_count: int | None = None
    scan_amplification: float | None = None


def strategy_metrics(
    *,
    n_db: int,
    visible_total: int,
    page_size: int,
    scanned_count: int,
) -> dict[str, float | int]:
    if n_db <= 0 or visible_total < 0 or page_size <= 0 or scanned_count < 0:
        raise BenchmarkContractError("invalid list strategy cardinality")
    selectivity = visible_total / n_db
    returned = min(page_size, visible_total)
    amplification = scanned_count / max(1, returned)
    return {
        "n_db": n_db,
        "visible_total": visible_total,
        "selectivity": round(selectivity, 8),
        "scanned_count": scanned_count,
        "scan_amplification": round(amplification, 8),
    }


class BenchmarkClient(Protocol):
    async def health(self) -> None: ...

    async def verify_model(self, expected_checksum: str) -> None: ...

    async def check(self, query: dict[str, str]) -> tuple[bool, str]: ...

    async def batch_check(
        self,
        queries: list[dict[str, str]],
    ) -> tuple[list[bool], str]: ...

    async def stream_list_objects(
        self,
        *,
        user: str,
        relation: str,
        resource_type: str,
    ) -> tuple[list[str], str, bool]: ...


class InstrumentedOpenFGAClient:
    """Minimal v1.15.1 REST client with request-id correlation."""

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
        response = await self._http.get(
            f"/stores/{self.store_id}/authorization-models/{self.model_id}"
        )
        response.raise_for_status()
        value = response.json().get("authorization_model", response.json())
        model = {
            "schema_version": value["schema_version"],
            "type_definitions": value["type_definitions"],
        }
        if authorization_model_checksum(model) != expected_checksum:
            raise BenchmarkContractError("live OpenFGA model checksum mismatch")

    async def _post(
        self,
        path: str,
        body: dict[str, Any],
    ) -> tuple[dict[str, Any], str]:
        request_id = f"f048-bench-{uuid4().hex}"
        response = await self._http.post(
            path,
            json=body,
            headers={"X-Request-ID": request_id},
        )
        response.raise_for_status()
        return response.json(), response.headers.get("x-request-id", request_id)

    async def check(self, query: dict[str, str]) -> tuple[bool, str]:
        data, request_id = await self._post(
            f"/stores/{self.store_id}/check",
            {
                "tuple_key": query,
                "authorization_model_id": self.model_id,
                "consistency": "HIGHER_CONSISTENCY",
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
                "consistency": "HIGHER_CONSISTENCY",
                "checks": [
                    {"tuple_key": query, "correlation_id": str(index)}
                    for index, query in enumerate(queries)
                ],
            },
        )
        result = data.get("result", {})
        return [
            bool(result.get(str(index), {}).get("allowed"))
            for index in range(len(queries))
        ], request_id

    async def stream_list_objects(
        self,
        *,
        user: str,
        relation: str,
        resource_type: str,
    ) -> tuple[list[str], str, bool]:
        request_id = f"f048-bench-{uuid4().hex}"
        objects: list[str] = []
        async with self._http.stream(
            "POST",
            f"/stores/{self.store_id}/streamed-list-objects",
            json={
                "user": user,
                "relation": relation,
                "type": resource_type,
                "authorization_model_id": self.model_id,
                "consistency": "HIGHER_CONSISTENCY",
            },
            headers={
                "X-Request-ID": request_id,
                "Accept": "application/x-ndjson",
            },
        ) as response:
            response.raise_for_status()
            request_id = response.headers.get("x-request-id", request_id)
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                payload = json.loads(line)
                object_key = payload.get("result", {}).get("object")
                if not isinstance(object_key, str):
                    raise BenchmarkContractError(
                        "StreamedListObjects returned an invalid item"
                    )
                objects.append(object_key)
        return objects, request_id, True


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
            write = await self._http.post(
                f"/stores/{self.store_id}/write",
                json={
                    "authorization_model_id": model_id,
                    "writes": {
                        "tuple_keys": tuples[offset : offset + WRITE_BATCH_SIZE]
                    },
                },
            )
            write.raise_for_status()
        return {
            "store_id": self.store_id,
            "model_id": model_id,
            "authorization_model_checksum": authorization_model_checksum(model),
            "dataset_checksum": dataset_checksum(contract),
            "source_checksum": source_checksum(contract),
            "visible_checksum": visible_checksum(contract),
            "tuple_count": len(tuples),
        }


def _scenario_map(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item["name"]): item for item in contract["dataset"]["scenarios"]
    }


def _query(scenario: dict[str, Any], object_key: str) -> dict[str, str]:
    return {
        "user": f"user:{scenario['actor_id']}",
        "relation": "visible",
        "object": object_key,
    }


def _invisible_object(scenario: dict[str, Any], index: int) -> str:
    return (
        f"{scenario['resource_type']}:{scenario['resource_id_prefix']}"
        f"invisible-{index:05d}"
    )


async def _timed_value(
    *,
    operation: str,
    scenario: str,
    call: Any,
    validate: Any,
) -> RequestSample:
    started = perf_counter()
    try:
        result, request_id = await call()
        validate(result)
        request_ids = (
            (request_id,)
            if isinstance(request_id, str)
            else tuple(request_id)
        )
        return RequestSample(
            operation=operation,
            scenario=scenario,
            elapsed_ms=(perf_counter() - started) * 1000,
            request_ids=request_ids,
            result_count=len(result) if isinstance(result, list) else None,
            result_checksum=checksum(sorted(result)) if isinstance(result, list) else None,
        )
    except Exception as exc:
        return RequestSample(
            operation=operation,
            scenario=scenario,
            elapsed_ms=(perf_counter() - started) * 1000,
            request_ids=(),
            error=f"{type(exc).__name__}: {exc}",
        )


async def _bounded_batch_check(
    client: BenchmarkClient,
    queries: list[dict[str, str]],
) -> tuple[list[bool], tuple[str, ...]]:
    allowed: list[bool] = []
    request_ids: list[str] = []
    for offset in range(0, len(queries), OPENFGA_BATCH_CHECK_LIMIT):
        chunk_allowed, request_id = await client.batch_check(
            queries[offset : offset + OPENFGA_BATCH_CHECK_LIMIT]
        )
        allowed.extend(chunk_allowed)
        request_ids.append(request_id)
    return allowed, tuple(request_ids)


async def _stream_sample(
    client: BenchmarkClient,
    scenario: dict[str, Any],
    *,
    operation: str = "stream_list_objects",
) -> RequestSample:
    started = perf_counter()
    try:
        objects, request_id, completed = await client.stream_list_objects(
            user=f"user:{scenario['actor_id']}",
            relation="visible",
            resource_type=str(scenario["resource_type"]),
        )
        expected = object_keys(scenario)
        if not completed or sorted(set(objects)) != sorted(expected):
            raise BenchmarkContractError(
                "StreamedListObjects result set mismatch, truncation, or abnormal EOF"
            )
        return RequestSample(
            operation=operation,
            scenario=str(scenario["name"]),
            elapsed_ms=(perf_counter() - started) * 1000,
            request_ids=(request_id,),
            result_count=len(set(objects)),
            result_checksum=checksum(sorted(set(objects))),
            stream_completed=True,
        )
    except Exception as exc:
        return RequestSample(
            operation=operation,
            scenario=str(scenario["name"]),
            elapsed_ms=(perf_counter() - started) * 1000,
            request_ids=(),
            error=f"{type(exc).__name__}: {exc}",
            stream_completed=False,
        )


async def _candidate_chain_sample(
    client: BenchmarkClient,
    *,
    name: str,
    scenario: dict[str, Any],
    n_db: int,
    visible_total: int,
    selectivity: float,
    page_size: int,
    batch_size: int,
) -> RequestSample:
    started = perf_counter()
    request_ids: list[str] = []
    visible: list[str] = []
    scanned = 0
    error: str | None = None
    expected_visible = object_keys(scenario)
    if not 0 < selectivity <= 1:
        raise BenchmarkContractError("business path selectivity must be in (0, 1]")
    try:
        visible_index = 0
        invisible_index = 0
        while len(visible) < min(page_size, visible_total) and scanned < n_db:
            candidates: list[str] = []
            for _ in range(min(batch_size, n_db - scanned)):
                position = scanned + len(candidates)
                should_be_visible = (
                    visible_index < visible_total
                    and position % max(1, round(1 / selectivity)) == 0
                )
                if should_be_visible:
                    candidates.append(expected_visible[visible_index])
                    visible_index += 1
                else:
                    invisible_index += 1
                    candidates.append(_invisible_object(scenario, invisible_index))
            allowed, chunk_request_ids = await _bounded_batch_check(
                client,
                [_query(scenario, item) for item in candidates]
            )
            request_ids.extend(chunk_request_ids)
            scanned += len(candidates)
            visible.extend(
                item
                for item, is_allowed in zip(candidates, allowed, strict=True)
                if is_allowed
            )
        visible = visible[:page_size]
        if len(visible) != min(page_size, visible_total):
            raise BenchmarkContractError("candidate-first path did not fill the page")
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    metrics = strategy_metrics(
        n_db=n_db,
        visible_total=visible_total,
        page_size=page_size,
        scanned_count=scanned,
    )
    return RequestSample(
        operation="business_path",
        scenario=name,
        elapsed_ms=(perf_counter() - started) * 1000,
        request_ids=tuple(request_ids),
        error=error,
        result_count=len(visible),
        result_checksum=checksum(visible),
        strategy="candidate_first",
        candidate_pass_rate=selectivity,
        db_rows=scanned,
        **metrics,
    )


async def _id_first_chain_sample(
    client: BenchmarkClient,
    *,
    name: str,
    scenario: dict[str, Any],
    page_size: int,
) -> RequestSample:
    sample = await _stream_sample(client, scenario, operation="business_path")
    visible_total = int(scenario["visible_count"])
    n_db = int(scenario["resource_count"])
    db_rows = visible_total
    metrics = strategy_metrics(
        n_db=n_db,
        visible_total=visible_total,
        page_size=page_size,
        scanned_count=db_rows,
    )
    sample.scenario = name
    sample.strategy = "visible_id_first"
    sample.result_count = min(page_size, visible_total)
    sample.db_rows = db_rows
    sample.n_db = int(metrics["n_db"])
    sample.visible_total = int(metrics["visible_total"])
    sample.selectivity = float(metrics["selectivity"])
    sample.candidate_pass_rate = 1.0
    sample.scanned_count = int(metrics["scanned_count"])
    sample.scan_amplification = float(metrics["scan_amplification"])
    return sample


async def run_workloads(
    client: BenchmarkClient,
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
        for scenario in scenarios.values():
            first = object_keys(scenario)[0]
            sample = await _timed_value(
                operation="check",
                scenario=str(scenario["name"]),
                call=lambda s=scenario, o=first: client.check(_query(s, o)),
                validate=lambda allowed: (
                    None
                    if allowed
                    else (_ for _ in ()).throw(
                        BenchmarkContractError("expected visible Check ALLOW")
                    )
                ),
            )
            if record:
                samples.append(sample)

        batch_scenario = max(
            scenarios.values(), key=lambda item: int(item["visible_count"])
        )
        batch_objects = object_keys(batch_scenario)
        for size in BATCH_CHECK_SIZES:
            queries = [
                _query(batch_scenario, object_key)
                for object_key in batch_objects[:size]
            ]
            sample = await _timed_value(
                operation="batch_check",
                scenario=str(size),
                call=lambda q=queries: _bounded_batch_check(client, q),
                validate=lambda allowed, expected=size: (
                    None
                    if len(allowed) == expected and all(allowed)
                    else (_ for _ in ()).throw(
                        BenchmarkContractError(
                            f"visible BatchCheck {expected} result mismatch"
                        )
                    )
                ),
            )
            if record:
                samples.append(sample)

        for scenario in scenarios.values():
            sample = await _stream_sample(client, scenario)
            if record:
                samples.append(sample)

        paths = contract["dataset"]["business_paths"]
        joined = paths["joined"]
        joined_sample = await _id_first_chain_sample(
            client,
            name="joined",
            scenario=scenarios[str(joined["scenario"])],
            page_size=int(joined["page_size"]),
        )
        department = paths["department"]
        department_sample = await _candidate_chain_sample(
            client,
            name="department",
            scenario=scenarios[str(department["scenario"])],
            n_db=int(department["n_db"]),
            visible_total=int(department["visible_total"]),
            selectivity=float(department["selectivity"]),
            page_size=int(department["page_size"]),
            batch_size=int(department["batch_size"]),
        )
        file_path = paths["file"]
        file_sample = await _candidate_chain_sample(
            client,
            name="file",
            scenario=scenarios[str(file_path["scenario"])],
            n_db=int(file_path["n_db"]),
            visible_total=int(file_path["visible_total"]),
            selectivity=float(file_path["selectivity"]),
            page_size=int(file_path["page_size"]),
            batch_size=int(file_path["batch_size"]),
        )
        if record:
            samples.extend((joined_sample, department_sample, file_sample))

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
        request_id = str(
            fields.get("request_id")
            or fields.get("request.id")
            or fields.get("x-request-id")
            or ""
        )
        if request_id not in request_ids:
            continue
        dispatch = _coerce_int(fields.get("dispatch_count"))
        reads = _coerce_int(
            fields.get("datastore_query_count")
            or fields.get("datastore_read_count")
        )
        if dispatch is not None and reads is not None:
            metrics[request_id] = {
                "dispatch_count": dispatch,
                "datastore_query_count": reads,
            }
    return metrics


def _summary_or_none(values: Iterable[float]) -> dict[str, float | int] | None:
    collected = tuple(values)
    return summarize(collected) if collected else None


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
    limits = contract["limits"]

    check = [sample for sample in successful if sample.operation == "check"]
    check_summary = _summary_or_none(sample.elapsed_ms for sample in check)
    check_passed = (
        check_summary is not None
        and
        len(check) == len(contract["dataset"]["scenarios"])
        * int(contract["run"]["iterations"])
        and check_summary["p95_ms"] <= float(limits["check_p95_ms"])
    )

    batch_report: dict[str, Any] = {}
    for size in BATCH_CHECK_SIZES:
        group = grouped[("batch_check", str(size))]
        summary = _summary_or_none(
            sample.elapsed_ms for sample in group if sample.error is None
        )
        passed = bool(group) and all(sample.error is None for sample in group)
        passed = passed and summary is not None and summary["p95_ms"] <= float(
            limits["batch_check_p95_ms"][str(size)]
        )
        batch_report[str(size)] = {"latency": summary, "passed": passed}

    stream_report: dict[str, Any] = {}
    for scenario in contract["dataset"]["scenarios"]:
        name = str(scenario["name"])
        group = grouped[("stream_list_objects", name)]
        valid = bool(group) and all(
            sample.error is None
            and sample.stream_completed is True
            and sample.result_count == int(scenario["visible_count"])
            and sample.result_checksum == scenario["expected_object_checksum"]
            for sample in group
        )
        latency = _summary_or_none(
            sample.elapsed_ms for sample in group if sample.error is None
        )
        limit = float(limits["stream_p95_ms"][str(scenario["visible_count"])])
        passed = (
            valid
            and latency is not None
            and latency["p95_ms"] <= limit
        )
        stream_report[name] = {
            "resource_count": int(scenario["resource_count"]),
            "visible_count": int(scenario["visible_count"]),
            "source_kind": scenario["source_kind"],
            "latency": latency,
            "p95_limit_ms": limit,
            "stream_completed": valid,
            "passed": passed,
        }

    path_report: dict[str, Any] = {}
    for name in ("joined", "department", "file"):
        group = grouped[("business_path", name)]
        valid = bool(group) and all(sample.error is None for sample in group)
        path_report[name] = {
            "strategy": group[0].strategy if group else None,
            "latency": _summary_or_none(
                sample.elapsed_ms for sample in group if sample.error is None
            ),
            "n_db": group[0].n_db if group else None,
            "visible_total": group[0].visible_total if group else None,
            "selectivity": group[0].selectivity if group else None,
            "candidate_pass_rate": (
                group[0].candidate_pass_rate if group else None
            ),
            "db_rows": _summary_or_none(
                float(sample.db_rows or 0)
                for sample in group
                if sample.error is None
            ),
            "scan_amplification": _summary_or_none(
                float(sample.scan_amplification or 0)
                for sample in group
                if sample.error is None
            ),
            "passed": valid,
        }

    request_ids = {
        request_id for sample in samples for request_id in sample.request_ids
    }
    observed_ids = request_ids.intersection(metrics)
    observability_passed = bool(request_ids) and observed_ids == request_ids
    observability = {
        "request_count": len(request_ids),
        "observed_request_count": len(observed_ids),
        "dispatch": _summary_or_none(
            float(metrics[item]["dispatch_count"]) for item in observed_ids
        ),
        "datastore_reads": _summary_or_none(
            float(metrics[item]["datastore_query_count"]) for item in observed_ids
        ),
        "passed": observability_passed,
    }
    performance_passed = all(
        (
            check_passed,
            all(item["passed"] for item in batch_report.values()),
            all(item["passed"] for item in stream_report.values()),
            all(item["passed"] for item in path_report.values()),
            observability_passed,
            error_rate < float(limits["max_error_rate"]),
        )
    )
    distribution_accepted = bool(
        contract["dataset"].get("production_derived")
        or contract["dataset"].get("representative_distribution")
    )
    return {
        "contract_version": contract["contract_version"],
        "contract_checksum": contract["contract_checksum"],
        "authorization_model_checksum": contract["authorization_model_checksum"],
        "dataset_checksum": contract["dataset"]["dataset_checksum"],
        "source_checksum": contract["dataset"]["source_checksum"],
        "visible_checksum": contract["dataset"]["visible_checksum"],
        "openfga_version": OPENFGA_VERSION,
        "dataset_source": contract["dataset"]["source"],
        "production_derived": bool(contract["dataset"].get("production_derived")),
        "representative_distribution": bool(
            contract["dataset"].get("representative_distribution")
        ),
        "error_rate": round(error_rate, 8),
        "check": {"latency": check_summary, "passed": check_passed},
        "batch_check": batch_report,
        "streamed_list_objects": stream_report,
        "business_paths": path_report,
        "openfga_observability": observability,
        "performance_passed": performance_passed,
        "release_ready": performance_passed and distribution_accepted,
        "samples": [asdict(sample) for sample in samples],
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
        help="Required acknowledgement for writes to the dedicated benchmark Store",
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
        help="Allow the checksum-pinned representative synthetic fixture",
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

    if not contract["dataset"].get("production_derived") and not args.allow_synthetic:
        raise BenchmarkContractError(
            "this BENCH-01 fixture is synthetic; use --allow-synthetic only in a dedicated benchmark environment"
        )
    iterations = args.iterations or int(contract["run"]["iterations"])
    warmup = (
        args.warmup
        if args.warmup is not None
        else int(contract["run"]["warmup"])
    )
    if iterations < 1 or warmup < 0:
        raise BenchmarkContractError(
            "iterations must be positive and warmup non-negative"
        )
    runtime_contract = json.loads(json.dumps(contract))
    runtime_contract["run"]["iterations"] = iterations
    client = InstrumentedOpenFGAClient(
        api_url=args.api_url,
        store_id=args.store_id,
        model_id=args.model_id,
        timeout=args.timeout,
    )
    try:
        samples = await run_workloads(
            client,
            runtime_contract,
            iterations=iterations,
            warmup=warmup,
        )
    finally:
        await client.close()
    request_ids = {
        request_id for sample in samples for request_id in sample.request_ids
    }
    metrics = read_openfga_metrics(args.openfga_log, request_ids)
    report = evaluate(runtime_contract, samples, metrics)
    if args.output:
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return (
        EXIT_OK if report["release_ready"] else EXIT_GATE_FAILED,
        report,
    )


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
