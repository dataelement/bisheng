"""Memory evaluation runner (F132 Wave 14, AC-104, AC-105).

Runs each case twice — with memory and without memory — and reports per-case
results, per-AC pass rates, the two-condition comparison, and two counters:
answers that claim a write while nothing was written, and writes the user did
not ask for.

Backends:
- ``StubBackend`` for self-tests;
- ``HttpBackend`` for a real deployment: logs in as an ordinary user, toggles
  "my memory" through ``PUT /api/v1/memory/setting``, talks to the daily-mode
  endpoint and reads ``GET /api/v1/memory/flags`` to know whether a turn wrote.
  The open API does not support memory (spec AC-10), so a logged-in user is
  required. Run it from a machine that can reach the test environment.

Usage (from tools/): python -m memory_eval.runner --base-url ... --token ... --model ... --out report.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

CLAIM_PATTERNS = re.compile(r"(已记下|记下了|记住了|已经记录|已记录|帮你记|I(?:'ve| have) noted|noted it|remembered)", re.I)


@dataclass
class Turn:
    user: str
    new_session: bool = False
    expect_write: bool | None = None


@dataclass
class Case:
    id: str
    acs: list[str]
    turns: list[Turn]
    question: Turn
    rules: dict
    notes: str = ""
    # Automatic consolidation must have run before the question (quiet period).
    requires_consolidation: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> Case:
        return cls(
            id=data["id"],
            acs=list(data["acs"]),
            turns=[Turn(**t) for t in data.get("turns", [])],
            question=Turn(**data["question"]),
            rules=dict(data.get("rules") or {}),
            notes=data.get("notes", ""),
            requires_consolidation=bool(data.get("requires_consolidation", False)),
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TurnResult:
    answer: str
    wrote: bool = False


def judge(rules: dict, answer: str) -> bool:
    text = answer or ""
    if any_of := rules.get("must_contain_any"):
        if not any(s in text for s in any_of):
            return False
    for s in rules.get("must_contain_all") or []:
        if s not in text:
            return False
    for s in rules.get("must_not_contain") or []:
        if s in text:
            return False
    if pattern := rules.get("regex"):
        if not re.search(pattern, text):
            return False
    return True


class StubBackend:
    def __init__(self, script: dict):
        self.script = script

    def run(self, case: Case, with_memory: bool) -> list[TurnResult]:
        return list(self.script[(case.id, with_memory)])


class HttpBackend:  # pragma: no cover - needs a running deployment (T089)
    def __init__(self, base_url: str, token: str, model: str, consolidation_wait: int = 0):
        import httpx

        self.consolidation_wait = consolidation_wait
        self.client = httpx.Client(base_url=base_url.rstrip("/"), timeout=600, cookies={"access_token_cookie": token})
        self.model = model

    def _set_memory(self, enabled: bool):
        self.client.put("/api/v1/memory/setting", json={"enabled": enabled}).raise_for_status()

    def _clear(self):
        self.client.post("/api/v1/memory/items/clear").raise_for_status()

    def _ask(self, chat_id: str, text: str) -> str:
        body = {"clientTimestamp": "", "conversationId": chat_id, "model": self.model, "text": text}
        answer = []
        with self.client.stream("POST", "/api/v1/workstation/chat/completions", json=body) as resp:
            for line in resp.iter_lines():
                if not line.startswith("data:"):
                    continue
                try:
                    data = json.loads(line[5:].strip())
                except ValueError:
                    continue
                msg = (data.get("data") or {}).get("msg") if isinstance(data.get("data"), dict) else None
                if data.get("category") in ("agent_answer", "answer") and isinstance(msg, str):
                    answer.append(msg)
        return "".join(answer)

    def _wrote(self, chat_id: str) -> set[str]:
        flags = self.client.get("/api/v1/memory/flags", params={"chat_id": chat_id}).json().get("data") or {}
        return {k for k, v in flags.items() if v.get("has_write")}

    def run(self, case: Case, with_memory: bool) -> list[TurnResult]:
        self._clear()
        self._set_memory(with_memory)
        results, chat_id, seen = [], uuid.uuid4().hex, set()
        for turn in [*case.turns, case.question]:
            if turn is case.question and case.requires_consolidation and self.consolidation_wait:
                import time

                time.sleep(self.consolidation_wait)  # quiet period + one scan, set to the deployment's values
            if turn.new_session:
                chat_id, seen = uuid.uuid4().hex, set()
            answer = self._ask(chat_id, turn.user)
            wrote_now = self._wrote(chat_id) - seen
            seen |= wrote_now
            results.append(TurnResult(answer=answer, wrote=bool(wrote_now)))
        return results


def _run_condition(case: Case, results: list[TurnResult]) -> dict:
    claimed_not_written = unrequested = 0
    for turn, res in zip([*case.turns, case.question], results):
        if CLAIM_PATTERNS.search(res.answer or "") and not res.wrote:
            claimed_not_written += 1
        if res.wrote and turn.expect_write is False:
            unrequested += 1
    final = results[-1].answer if results else ""
    return {
        "passed": judge(case.rules, final),
        "answer": final,
        "claimed_but_not_written": claimed_not_written,
        "unrequested_writes": unrequested,
    }


def run_cases(cases: list[Case], backend) -> dict:
    report = {"cases": {}, "per_ac": {}, "summary": {}}
    for case in cases:
        report["cases"][case.id] = {
            "acs": case.acs,
            "with_memory": _run_condition(case, backend.run(case, True)),
            "without_memory": _run_condition(case, backend.run(case, False)),
        }
    for cond in ("with_memory", "without_memory"):
        rows = [c[cond] for c in report["cases"].values()]
        n = len(rows) or 1
        report["summary"][cond] = {
            "score": sum(r["passed"] for r in rows) / n,
            "claimed_but_not_written": sum(r["claimed_but_not_written"] for r in rows),
            "unrequested_writes": sum(r["unrequested_writes"] for r in rows),
        }
    acs = sorted({ac for c in cases for ac in c.acs})
    for ac in acs:
        hit = [c for c in report["cases"].values() if ac in c["acs"]]
        report["per_ac"][ac] = {
            "with_memory": sum(c["with_memory"]["passed"] for c in hit) / len(hit),
            "without_memory": sum(c["without_memory"]["passed"] for c in hit) / len(hit),
            "n": len(hit),
        }
    return report


def load_cases(directory: Path) -> list[Case]:
    return [Case.from_dict(json.loads(p.read_text(encoding="utf-8"))) for p in sorted(Path(directory).glob("*.json"))]


def main(argv=None) -> int:  # pragma: no cover - CLI
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--token", required=True, help="access token of an ordinary (non-admin) user")
    parser.add_argument("--model", required=True, help="workstation model id")
    parser.add_argument("--cases", default=str(Path(__file__).parent / "cases"))
    parser.add_argument("--out", default="memory_eval_report.json")
    parser.add_argument("--consolidation-wait", type=int, default=0, help="seconds to wait before questions that need consolidation")
    args = parser.parse_args(argv)
    report = run_cases(load_cases(Path(args.cases)), HttpBackend(args.base_url, args.token, args.model, args.consolidation_wait))
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
