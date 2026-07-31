"""BENCH-01 fixed-fixture, workload, threshold, and safety contracts.

覆盖 AC: AC-28, AC-29, AC-30, AC-31, AC-32, AC-33, AC-34, AC-35, AC-69
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.benchmark_f048_permission_paths import (
    BATCH_CHECK_SIZES,
    CONTRACT_VERSION,
    DEFAULT_FIXTURE,
    BenchmarkContractError,
    RequestSample,
    build_dataset_tuples,
    checksum,
    contract_checksum,
    dataset_checksum,
    evaluate,
    load_contract,
    nearest_rank_percentile,
    object_keys,
    read_openfga_metrics,
    run_workloads,
    validate_environment,
)


@pytest.fixture(scope="module")
def contract() -> dict:
    return load_contract(DEFAULT_FIXTURE)


def test_fixed_fixture_checksums_and_required_distribution(contract: dict) -> None:
    assert contract["contract_version"] == CONTRACT_VERSION
    assert contract_checksum(contract) == ("12654227efbcdb9ebc2effdd1da5c668723cdcd96c4333eb621f0229b190dc14")
    assert dataset_checksum(contract) == ("ad302adc12b1807080f85c238b36c7e93a75ef1c39165e6250a3138710f6e54b")
    assert len(build_dataset_tuples(contract)) == 5823
    scenarios = {item["name"]: item for item in contract["dataset"]["profile"]["scenarios"]}
    assert {
        "direct",
        "department",
        "group",
        "inherit",
        "multi_grant",
        "result_10",
        "result_100",
        "result_1000",
    } == set(scenarios)
    assert [scenarios[f"result_{size}"]["result_count"] for size in (10, 100, 1000)] == [
        10,
        100,
        1000,
    ]
    assert set(map(int, contract["baseline"]["batch_check_ms"])) == set(BATCH_CHECK_SIZES)
    assert contract["dataset"]["production_derived"] is False


def test_fixture_checksum_drift_fails_closed(
    contract: dict,
    tmp_path: Path,
) -> None:
    tampered = json.loads(json.dumps(contract))
    tampered["dataset"]["profile"]["scenarios"][0]["actor_id"] = 9999
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(BenchmarkContractError, match="fixture checksum mismatch"):
        load_contract(path)

    with pytest.raises(
        BenchmarkContractError,
        match="expected-contract-checksum",
    ):
        load_contract(DEFAULT_FIXTURE, expected_checksum="0" * 64)


@pytest.mark.parametrize(
    "environment",
    ("production", "prod", "prod-blue", "live", "生产"),
)
def test_benchmark_refuses_production(environment: str) -> None:
    with pytest.raises(BenchmarkContractError, match="refuses production"):
        validate_environment(environment)
    assert validate_environment("release-verification") == "release-verification"


def test_nearest_rank_percentiles_are_deterministic() -> None:
    samples = list(range(1, 101))
    assert nearest_rank_percentile(samples, 50) == 50
    assert nearest_rank_percentile(samples, 95) == 95
    assert nearest_rank_percentile(samples, 99) == 99
    with pytest.raises(BenchmarkContractError):
        nearest_rank_percentile([], 95)


def _passing_samples(contract: dict) -> list[RequestSample]:
    samples: list[RequestSample] = []
    scenarios = contract["dataset"]["profile"]["scenarios"]
    for index, scenario in enumerate(scenarios):
        samples.append(
            RequestSample(
                operation="check",
                scenario=scenario["name"],
                elapsed_ms=1,
                request_ids=(f"check-{index}",),
            )
        )
        objects = object_keys(scenario)
        samples.append(
            RequestSample(
                operation="list_objects",
                scenario=scenario["name"],
                elapsed_ms=2,
                request_ids=(f"list-{index}",),
                result_count=len(objects),
                result_checksum=checksum(sorted(objects)),
            )
        )
    for size in BATCH_CHECK_SIZES:
        samples.append(
            RequestSample(
                operation="batch_check",
                scenario=str(size),
                elapsed_ms=3,
                request_ids=(f"batch-{size}",),
                result_count=size,
            )
        )
    cursor_contract = contract["dataset"]["profile"]["business_cursor"]
    scenario = next(item for item in scenarios if item["name"] == cursor_contract["scenario"])
    visible = object_keys(scenario)[: cursor_contract["candidate_count"]]
    samples.append(
        RequestSample(
            operation="business_cursor",
            scenario=scenario["name"],
            elapsed_ms=4,
            request_ids=("cursor-1", "cursor-2"),
            result_count=len(visible),
            result_checksum=checksum(visible),
        )
    )
    return samples


def _metrics(samples: list[RequestSample]) -> dict[str, dict[str, int]]:
    return {
        request_id: {"dispatch_count": 2, "datastore_query_count": 1}
        for sample in samples
        for request_id in sample.request_ids
    }


def test_threshold_report_passes_performance_but_not_release_fixture(
    contract: dict,
) -> None:
    samples = _passing_samples(contract)
    report = evaluate(contract, samples, _metrics(samples))
    assert report["check"]["passed"] is True
    assert all(item["passed"] for item in report["batch_check"].values())
    assert all(item["passed"] for item in report["list_objects"].values())
    assert report["business_cursor"]["passed"] is True
    assert report["openfga_observability"]["passed"] is True
    assert report["performance_passed"] is True
    assert report["production_derived"] is False
    assert report["release_ready"] is False


def test_missing_openfga_metrics_and_list_truncation_fail_gate(
    contract: dict,
) -> None:
    samples = _passing_samples(contract)
    result_1000 = next(item for item in samples if item.operation == "list_objects" and item.scenario == "result_1000")
    result_1000.result_count = 999
    result_1000.result_checksum = checksum(["workflow:truncated"])
    report = evaluate(contract, samples, {})
    assert report["list_objects"]["result_1000"]["passed"] is False
    assert report["openfga_observability"]["passed"] is False
    assert report["performance_passed"] is False


def test_openfga_json_log_correlates_dispatch_and_datastore_reads(
    tmp_path: Path,
) -> None:
    path = tmp_path / "openfga.jsonl"
    path.write_text(
        "\n".join(
            (
                json.dumps(
                    {
                        "fields": {
                            "request_id": "wanted",
                            "dispatch_count": 17,
                            "datastore_query_count": 3,
                        }
                    }
                ),
                json.dumps(
                    {
                        "request_id": "unrelated",
                        "dispatch_count": 99,
                        "datastore_query_count": 99,
                    }
                ),
                "not-json",
            )
        ),
        encoding="utf-8",
    )
    assert read_openfga_metrics(path, {"wanted"}) == {"wanted": {"dispatch_count": 17, "datastore_query_count": 3}}


class FakeBenchmarkClient:
    def __init__(self, contract: dict) -> None:
        self.contract = contract
        self.batch_sizes: list[int] = []
        self._sequence = 0
        self._by_actor = {f"user:{item['actor_id']}": item for item in contract["dataset"]["profile"]["scenarios"]}

    def _request_id(self) -> str:
        self._sequence += 1
        return f"request-{self._sequence}"

    async def health(self) -> None:
        return None

    async def verify_model(self, expected_checksum: str) -> None:
        assert expected_checksum == self.contract["authorization_model_checksum"]

    async def check(self, query: dict) -> tuple[bool, str]:
        assert query["relation"].startswith("can_")
        return True, self._request_id()

    async def batch_check(self, queries: list[dict]) -> tuple[list[bool], str]:
        self.batch_sizes.append(len(queries))
        assert len(queries) <= 100
        return [True] * len(queries), self._request_id()

    async def list_objects(
        self,
        *,
        user: str,
        relation: str,
        resource_type: str,
    ) -> tuple[list[str], str]:
        scenario = self._by_actor[user]
        assert relation == f"can_{scenario['action']}"
        assert resource_type == scenario["resource_type"]
        return object_keys(scenario), self._request_id()


async def test_workload_executes_check_batch_list_and_bounded_business_cursor(
    contract: dict,
) -> None:
    client = FakeBenchmarkClient(contract)
    samples = await run_workloads(client, contract, iterations=1, warmup=0)
    assert len([item for item in samples if item.operation == "check"]) == 8
    assert len([item for item in samples if item.operation == "list_objects"]) == 8
    assert [item.scenario for item in samples if item.operation == "batch_check"] == [
        "20",
        "50",
        "100",
    ]
    # Three explicit BatchCheck samples plus five pages of 20 candidates.
    assert client.batch_sizes == [20, 50, 100, 20, 20, 20, 20, 20]
    assert all(item.error is None for item in samples)
