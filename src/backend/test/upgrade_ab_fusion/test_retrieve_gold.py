"""检索金标: remap 后 overlap@k 与 top1."""

from test.upgrade_ab_fusion._packutil import ensure_pack_path

ensure_pack_path()
from fusion.retrieve_gold import score_case, score_jobs


def test_score_ok_when_top1_and_overlap():
    scored = score_case(
        b_hits=[{"file_id": 12}, {"file_id": 13}, {"document_id": 14}],
        a_hits=[{"file_id": 20}, {"file_id": 21}, {"file_id": 22}],
        file_map={"12": "20", "13": "21", "14": "22"},
        k=5,
        min_overlap=0.8,
    )
    assert scored["ok"] is True
    assert scored["expected"] == ["20", "21", "22"]
    assert scored["top1"] is True


def test_score_fails_top1_mismatch():
    scored = score_case(
        b_hits=[{"file_id": 12}, {"file_id": 13}],
        a_hits=[{"file_id": 21}, {"file_id": 20}],
        file_map={"12": "20", "13": "21"},
        k=5,
        min_overlap=0.5,
    )
    assert scored["ok"] is False
    assert scored["top1"] is False


def test_a_hits_are_not_remapped():
    scored = score_case(
        b_hits=[{"file_id": "12"}],
        a_hits=[{"file_id": "20"}],
        file_map={"12": "20", "20": "99"},
        k=1,
        min_overlap=1.0,
    )
    assert scored["ok"] is True
    assert scored["actual"] == ["20"]


def test_score_jobs_counts_failures():
    out = score_jobs(
        [
            {
                "b_id": "5",
                "a_collection": "b5_c",
                "b_hits": [{"file_id": 12}],
                "a_hits": [{"file_id": 20}],
            },
            {
                "b_id": "6",
                "a_collection": "b6_c",
                "b_hits": [{"file_id": 12}],
                "a_hits": [{"file_id": 21}],
            },
        ],
        file_map={"12": "20"},
        k=1,
        min_overlap=1.0,
    )
    assert out["total"] == 2
    assert out["failed"] == 1
    assert out["ok"] is False
