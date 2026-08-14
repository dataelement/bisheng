"""BENCH-01 single-slot visibility performance contracts.

覆盖 AC: AC-160, AC-161, AC-162, AC-163, AC-168, AC-175, AC-176
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bisheng.core.openfga.authorization_model_f048 import build_authorization_model_f048
from scripts.benchmark_f048_permission_paths import (
    CONTRACT_VERSION,
    DEFAULT_FIXTURE,
    RESOURCE_SCALES,
    SOURCE_KINDS,
    VISIBLE_RESULT_SIZES,
    BenchmarkContractError,
    RequestSample,
    build_dataset_tuples,
    contract_checksum,
    dataset_checksum,
    evaluate,
    load_contract,
    model_has_ab_slots,
    nearest_rank_percentile,
    object_keys,
    run_workloads,
    source_checksum,
    strategy_metrics,
    validate_environment,
    visible_checksum,
)


@pytest.fixture(scope="module")
def contract() -> dict:
    return load_contract(DEFAULT_FIXTURE)


def test_fixed_fixture_covers_resource_visibility_and_source_matrix(
    contract: dict,
) -> None:
    assert contract["contract_version"] == CONTRACT_VERSION
    assert contract_checksum(contract) == (
        "80a80489bf4f3ae01f5b1f3519cd275b10a92f16dd58df5fa1378de48c608912"
    )
    assert dataset_checksum(contract) == (
        "d083c56febda9eb055e9ae5356f800ca837a1e534628fdeda623dc4b8063ab22"
    )
    assert source_checksum(contract) == (
        "9e2e7699dbe65851de0b04651ee8bdb009e2a85ac16e8c12a5b9e5092c220df0"
    )
    assert visible_checksum(contract) == (
        "f185c204418fbd98d41c15b0bac7759060c2df73da8c8c4fcf381f0a02c1994e"
    )
    assert len(build_dataset_tuples(contract)) == 41_666

    scenarios = contract["dataset"]["scenarios"]
    assert {
        (int(item["resource_count"]), int(item["visible_count"]))
        for item in scenarios
    } == {
        (resource_count, visible_count)
        for resource_count in RESOURCE_SCALES
        for visible_count in VISIBLE_RESULT_SIZES
    }
    assert {item["source_kind"] for item in scenarios} == SOURCE_KINDS
    assert contract["dataset"]["production_derived"] is False
    assert contract["dataset"]["representative_distribution"] is True


def test_target_model_and_dataset_have_no_ab_visibility_slots(
    contract: dict,
) -> None:
    assert model_has_ab_slots(build_authorization_model_f048()) is False
    assert not any(
        relation in {"visible_a", "visible_b", "slot_a", "slot_b"}
        for relation in (item["relation"] for item in build_dataset_tuples(contract))
    )


def test_fixture_checksum_and_distribution_drift_fail_closed(
    contract: dict,
    tmp_path: Path,
) -> None:
    tampered = json.loads(json.dumps(contract))
    tampered["dataset"]["scenarios"][0]["actor_id"] = 9999
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


def test_strategy_metrics_record_n_db_v_p_and_scan_amplification() -> None:
    sparse = strategy_metrics(
        n_db=100_000,
        visible_total=100,
        page_size=20,
        scanned_count=20,
    )
    assert sparse == {
        "n_db": 100_000,
        "visible_total": 100,
        "selectivity": 0.001,
        "scanned_count": 20,
        "scan_amplification": 1.0,
    }
    candidate = strategy_metrics(
        n_db=100_000,
        visible_total=5_000,
        page_size=50,
        scanned_count=100,
    )
    assert candidate["selectivity"] == 0.05
    assert candidate["scan_amplification"] == 2.0


class FakeBenchmarkClient:
    def __init__(self, contract: dict, *, truncate: bool = False) -> None:
        self.contract = contract
        self.truncate = truncate
        self.batch_sizes: list[int] = []
        self.stream_relations: list[str] = []
        self._sequence = 0
        self._by_actor = {
            f"user:{item['actor_id']}": item
            for item in contract["dataset"]["scenarios"]
        }
        self._visible = {
            object_key
            for item in contract["dataset"]["scenarios"]
            for object_key in object_keys(item)
        }

    def _request_id(self) -> str:
        self._sequence += 1
        return f"request-{self._sequence}"

    async def health(self) -> None:
        return None

    async def verify_model(self, expected_checksum: str) -> None:
        assert expected_checksum == self.contract["authorization_model_checksum"]

    async def check(self, query: dict) -> tuple[bool, str]:
        assert query["relation"] == "visible"
        return query["object"] in self._visible, self._request_id()

    async def batch_check(self, queries: list[dict]) -> tuple[list[bool], str]:
        self.batch_sizes.append(len(queries))
        assert len(queries) <= 50
        assert all(query["relation"] == "visible" for query in queries)
        return [query["object"] in self._visible for query in queries], self._request_id()

    async def stream_list_objects(
        self,
        *,
        user: str,
        relation: str,
        resource_type: str,
    ) -> tuple[list[str], str, bool]:
        scenario = self._by_actor[user]
        self.stream_relations.append(relation)
        assert relation == "visible"
        assert resource_type == scenario["resource_type"]
        objects = object_keys(scenario)
        if self.truncate:
            objects = objects[:-1]
        return objects, self._request_id(), True


def _with_one_iteration(contract: dict) -> dict:
    value = json.loads(json.dumps(contract))
    value["run"]["iterations"] = 1
    value["run"]["warmup"] = 0
    return value


def _metrics(samples: list[RequestSample]) -> dict[str, dict[str, int]]:
    return {
        request_id: {"dispatch_count": 2, "datastore_query_count": 1}
        for sample in samples
        for request_id in sample.request_ids
    }


async def test_workload_uses_single_slot_stream_batch_and_business_paths(
    contract: dict,
) -> None:
    runtime_contract = _with_one_iteration(contract)
    client = FakeBenchmarkClient(runtime_contract)
    samples = await run_workloads(
        client,
        runtime_contract,
        iterations=1,
        warmup=0,
    )
    assert len([item for item in samples if item.operation == "check"]) == 8
    assert len(
        [item for item in samples if item.operation == "stream_list_objects"]
    ) == 8
    assert [
        item.scenario for item in samples if item.operation == "batch_check"
    ] == ["20", "50", "100"]
    assert {item.scenario for item in samples if item.operation == "business_path"} == {
        "joined",
        "department",
        "file",
    }
    assert set(client.stream_relations) == {"visible"}
    assert all(item.error is None for item in samples)
    assert all(
        item.stream_completed is True
        for item in samples
        if item.operation == "stream_list_objects"
    )

    paths = {
        item.scenario: item
        for item in samples
        if item.operation == "business_path"
    }
    assert paths["joined"].strategy == "visible_id_first"
    assert paths["joined"].n_db == 100_000
    assert paths["joined"].visible_total == 100
    assert paths["department"].strategy == "candidate_first"
    assert paths["department"].selectivity == 0.5
    assert paths["department"].candidate_pass_rate == 0.5
    assert paths["file"].strategy == "candidate_first"
    assert paths["file"].selectivity == 0.05
    assert paths["file"].candidate_pass_rate == 0.95
    assert paths["file"].scan_amplification is not None
    assert {20, 50}.issubset(set(client.batch_sizes))
    assert client.batch_sizes.count(50) >= 2
    assert max(client.batch_sizes) == 50


async def test_complete_stream_and_metrics_are_release_gate(
    contract: dict,
) -> None:
    runtime_contract = _with_one_iteration(contract)
    samples = await run_workloads(
        FakeBenchmarkClient(runtime_contract),
        runtime_contract,
        iterations=1,
        warmup=0,
    )
    report = evaluate(runtime_contract, samples, _metrics(samples))
    assert report["performance_passed"] is True
    assert report["release_ready"] is True
    assert report["production_derived"] is False
    assert report["representative_distribution"] is True
    assert all(
        item["stream_completed"] and item["passed"]
        for item in report["streamed_list_objects"].values()
    )
    assert all(item["passed"] for item in report["business_paths"].values())

    truncated = await run_workloads(
        FakeBenchmarkClient(runtime_contract, truncate=True),
        runtime_contract,
        iterations=1,
        warmup=0,
    )
    truncated_report = evaluate(runtime_contract, truncated, _metrics(truncated))
    assert truncated_report["performance_passed"] is False
    assert truncated_report["release_ready"] is False

    missing_metrics = evaluate(runtime_contract, samples, {})
    assert missing_metrics["openfga_observability"]["passed"] is False
    assert missing_metrics["performance_passed"] is False
