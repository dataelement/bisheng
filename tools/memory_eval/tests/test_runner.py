"""Memory evaluation runner self-test with a stub backend (AC-104, AC-105)."""

import json

from memory_eval.runner import Case, StubBackend, TurnResult, judge, load_cases, run_cases


def _case(**kw):
    base = {
        "id": "demo-01",
        "acs": ["AC-29"],
        "turns": [
            {"user": "我下周二有个重要会议，你记录一下", "new_session": False, "expect_write": True},
        ],
        "question": {"user": "我最近有什么重要安排？", "new_session": True},
        "rules": {"must_contain_any": ["会议"], "must_not_contain": ["不知道"]},
    }
    base.update(kw)
    return Case.from_dict(base)


def test_two_conditions_scores_and_comparison():
    """AC-105: the same case under with-memory and without-memory, compared."""
    backend = StubBackend(
        script={
            ("demo-01", True): [TurnResult(answer="好的，已记下", wrote=True), TurnResult(answer="你 2026-11-17 有重要会议")],
            ("demo-01", False): [TurnResult(answer="好的", wrote=False), TurnResult(answer="我不知道你的安排")],
        }
    )
    report = run_cases([_case()], backend)
    assert report["cases"]["demo-01"]["with_memory"]["passed"] is True
    assert report["cases"]["demo-01"]["without_memory"]["passed"] is False
    assert report["per_ac"]["AC-29"] == {"with_memory": 1.0, "without_memory": 0.0, "n": 1}
    assert report["summary"]["with_memory"]["score"] == 1.0
    assert report["summary"]["without_memory"]["score"] == 0.0


def test_ac104_two_counters():
    """AC-104: claims a write without writing; writes without being asked."""
    case = _case(
        turns=[
            {"user": "记一下我对花生过敏", "expect_write": True},
            {"user": "今天天气怎么样", "expect_write": False},
        ]
    )
    backend = StubBackend(
        script={
            ("demo-01", True): [
                TurnResult(answer="已经帮你记住了", wrote=False),
                TurnResult(answer="晴天", wrote=True),
                TurnResult(answer="你对会议过敏"),
            ],
            ("demo-01", False): [TurnResult(answer="好"), TurnResult(answer="晴"), TurnResult(answer="不清楚")],
        }
    )
    report = run_cases([case], backend)
    assert report["summary"]["with_memory"]["claimed_but_not_written"] == 1
    assert report["summary"]["with_memory"]["unrequested_writes"] == 1


def test_judge_rules():
    assert judge({"must_contain_any": ["会议"]}, "有个会议")
    assert not judge({"must_contain_all": ["会议", "周二"]}, "有个会议")
    assert not judge({"must_not_contain": ["密码"]}, "你的密码是")
    assert judge({"regex": r"2026-11-1\d"}, "2026-11-17")


def test_load_cases_from_directory(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps(_case().to_dict(), ensure_ascii=False), encoding="utf-8")
    assert [c.id for c in load_cases(tmp_path)] == ["demo-01"]
