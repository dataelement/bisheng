"""POC P3 — Redis checkpointer park-and-release 隔任意时长 + 跨重启续跑保真（R3）。关联 Track B.
失败影响：HITL 续跑降级 FAILED+retry。

本 POC 拆成两个可独立判定的子问题：
  (A) langgraph interrupt/resume **机制**：图能在 interrupt() 暂停，Command(resume) 后保真续跑；
  (B) **持久化传输**：langgraph-checkpoint-redis 能否在现网 Redis 上跨进程/重启续跑。

关键发现（B）：`langgraph-checkpoint-redis`（AsyncRedisSaver/AsyncShallowRedisSaver）经 redisvl
依赖 **RediSearch 模块**（FT.CREATE/FT._LIST）——即 **Redis Stack**，而现网/配置中的 Redis 是
**plain Redis**（`MODULE LIST` 为空）。因此 C5「复用 RedisManager 的 plain Redis」**不成立**，需决策：
部署 Redis Stack / 自研 plain-Redis checkpointer（checkpoint 序列化进普通 key）/ 换持久化方案。

运行：uv run --directory src/backend python scripts/035-linsight-deepagents/poc_p3_redis_checkpointer_resume.py
依赖：本地 Redis（config.yaml redis_url）。
"""

from __future__ import annotations

import asyncio
import operator
import uuid
from typing import Annotated, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

REDIS_URL = "redis://192.168.106.116:6379/9"


class State(TypedDict):
    log: Annotated[list[str], operator.add]
    answer: str


def _build_graph():
    def before(state: State):
        return {"log": ["before:collected_data"]}

    def ask_human(state: State):
        reply = interrupt({"question": "确认输出语言？"})
        return {"log": [f"resume:{reply}"], "answer": f"report-in-{reply}"}

    def after(state: State):
        return {"log": ["after:finalized"]}

    g = StateGraph(State)
    g.add_node("before", before)
    g.add_node("ask_human", ask_human)
    g.add_node("after", after)
    g.add_edge(START, "before")
    g.add_edge("before", "ask_human")
    g.add_edge("ask_human", "after")
    g.add_edge("after", END)
    return g


async def _check_mechanism() -> bool:
    """(A) interrupt/resume 机制：单 saver 内验证暂停→续跑保真。"""
    svid = f"poc-p3-mech-{uuid.uuid4().hex[:8]}"
    config = {"configurable": {"thread_id": svid}}
    saver = InMemorySaver()
    graph = _build_graph().compile(checkpointer=saver)

    interrupted = False
    async for chunk in graph.astream({"log": [], "answer": ""}, config):
        if "__interrupt__" in chunk:
            interrupted = True
    snap = await graph.aget_state(config)
    parked_next = snap.next

    async for _ in graph.astream(Command(resume="中文"), config):
        pass
    final = (await graph.aget_state(config)).values

    cond = (
        interrupted
        and parked_next == ("ask_human",)
        and final.get("log") == ["before:collected_data", "resume:中文", "after:finalized"]
        and final.get("answer") == "report-in-中文"
    )
    print(" (A) interrupt/resume 机制:")
    print(f"     - parked at interrupt, next={parked_next}, interrupted={interrupted}")
    print(f"     - resumed log={final.get('log')}, answer={final.get('answer')}")
    print(f"     -> {'GREEN' if cond else 'RED'}")
    return cond


async def _check_redis_transport() -> str:
    """(B) langgraph-checkpoint-redis 在现网 Redis 上是否可用。返回 'GREEN'|'BLOCKED'|'RED'。"""
    from redis.asyncio import Redis

    r = Redis.from_url(REDIS_URL)
    try:
        mods = await r.execute_command("MODULE", "LIST")
    finally:
        await r.aclose()
    has_search = any(
        b"search" in bytes(m).lower() if isinstance(m, (bytes, bytearray)) else False
        for sub in (mods or [])
        for m in (sub if isinstance(sub, (list, tuple)) else [sub])
    )
    print(" (B) Redis 持久化传输:")
    print(f"     - MODULE LIST: {mods}  (RediSearch present: {has_search})")

    if not has_search:
        print("     - langgraph-checkpoint-redis 需 RediSearch（Redis Stack）；现网为 plain Redis")
        print("     -> BLOCKED（需部署 Redis Stack 或换 checkpointer）")
        return "BLOCKED"

    # If a stack is present, actually exercise cross-instance resume.
    from langgraph.checkpoint.redis.aio import AsyncRedisSaver

    svid = f"poc-p3-redis-{uuid.uuid4().hex[:8]}"
    config = {"configurable": {"thread_id": svid}}
    builder = _build_graph()
    async with AsyncRedisSaver.from_conn_string(REDIS_URL) as sa:
        await sa.asetup()
        ga = builder.compile(checkpointer=sa)
        async for _ in ga.astream({"log": [], "answer": ""}, config):
            pass
    await asyncio.sleep(0.2)
    async with AsyncRedisSaver.from_conn_string(REDIS_URL) as sb:
        await sb.asetup()
        gb = builder.compile(checkpointer=sb)
        restored = (await gb.aget_state(config)).values
        async for _ in gb.astream(Command(resume="中文"), config):
            pass
        final = (await gb.aget_state(config)).values
    ok = restored.get("log") == ["before:collected_data"] and final.get("log") == [
        "before:collected_data",
        "resume:中文",
        "after:finalized",
    ]
    print(f"     - fresh-saver restored={restored.get('log')}, final={final.get('log')}")
    print(f"     -> {'GREEN' if ok else 'RED'}")
    return "GREEN" if ok else "RED"


async def main() -> int:
    print("=== POC P3: Redis checkpointer park-and-release ===")
    mech = await _check_mechanism()
    transport = await _check_redis_transport()
    print(f"\nRESULT P3: 机制(A)={'GREEN' if mech else 'RED'} · Redis传输(B)={transport}")
    print(
        "结论：interrupt/resume 续跑机制成立；持久化传输被 plain-Redis 阻塞——"
        "C5 需在『部署 Redis Stack』与『自研 plain-Redis checkpointer』间决策（见 RESULTS.md）。"
    )
    # BLOCKED on infra is an informative POC conclusion, not a hard failure of the spike.
    return 0 if mech else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
