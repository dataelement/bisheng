"""AC-17/AC-24/AC-30: independent denominators and separate timing axes."""

from scripts.measure_dsh_model_audit import percentile, summarize


def test_measurement_uses_independent_entered_count_not_written_rows():
    samples = []
    for mode in ("OFF", "METADATA", "CONTENT"):
        samples.append(
            {
                "mode": mode,
                "first_content_ms": 3.0,
                "total_ms": 4.0,
                "metadata_ms": 10.0 if mode == "METADATA" else None,
                "content_ms": None,
                "usage_ms": 5.0,
            }
        )
    report = summarize(samples, entered_count=3)
    assert report["independent_entered_count"] == 3
    assert report["expected_audit_count"] == 2 and report["audit_visible_count"] == 1
    assert report["content_expected_count"] == 1 and report["content_complete_count"] == 0
    assert report["modes"]["OFF"]["metadata_ms"]["count"] == 0
    assert report["modes"]["CONTENT"]["usage_ms"]["p95"] == 5.0
    assert "dsh_model_call" in report["usage_baseline"]


def test_small_sample_percentiles_are_observations_not_sla():
    assert percentile([], 0.95) is None
    assert percentile([1, 2, 3], 0.99) == 3
    assert percentile(list(range(100)), 0.95) == 94
