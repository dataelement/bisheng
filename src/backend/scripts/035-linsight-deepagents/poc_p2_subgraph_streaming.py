"""POC P2 — subgraphs=True 子图事件冒泡父 astream + 并行 namespace 不串流。关联 Track A。
失败影响：子任务步骤流降级。

判定（GREEN 条件）：
1. astream(..., subgraphs=True) 时子图内部节点更新以 (namespace_tuple, chunk) 形式冒泡到父流；
2. namespace 非空且携带子图前缀，可用于 C1 的 ExecStep.namespace 归并；
3. 两个并行子图的事件各自携带独立 namespace，不互相串流。

运行：uv run python scripts/035-linsight-deepagents/poc_p2_subgraph_streaming.py
不依赖外部中间件（纯 langgraph）。
"""

from __future__ import annotations

import asyncio
import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph


class SubState(TypedDict):
    events: Annotated[list[str], operator.add]


def _build_subgraph(tag: str):
    def step_a(state: SubState):
        return {"events": [f"{tag}:a"]}

    def step_b(state: SubState):
        return {"events": [f"{tag}:b"]}

    g = StateGraph(SubState)
    g.add_node("step_a", step_a)
    g.add_node("step_b", step_b)
    g.add_edge(START, "step_a")
    g.add_edge("step_a", "step_b")
    g.add_edge("step_b", END)
    return g.compile()


class ParentState(TypedDict):
    events: Annotated[list[str], operator.add]


def _build_parent():
    sub1 = _build_subgraph("sub1")
    sub2 = _build_subgraph("sub2")

    g = StateGraph(ParentState)
    # two subgraphs as parallel nodes (fan-out from START)
    g.add_node("sub1", sub1)
    g.add_node("sub2", sub2)
    g.add_edge(START, "sub1")
    g.add_edge(START, "sub2")
    g.add_edge("sub1", END)
    g.add_edge("sub2", END)
    return g.compile()


async def main() -> int:
    parent = _build_parent()
    namespaced_chunks: list[tuple] = []

    async for ns, chunk in parent.astream({"events": []}, stream_mode="updates", subgraphs=True):
        namespaced_chunks.append((ns, chunk))

    # collect chunks that carry a non-empty namespace (i.e. emitted inside a subgraph)
    sub_ns = [ns for ns, _ in namespaced_chunks if ns]
    sub1_ns = [ns for ns in sub_ns if any("sub1" in str(p) for p in ns)]
    sub2_ns = [ns for ns in sub_ns if any("sub2" in str(p) for p in ns)]

    ok = True
    print("=== POC P2: subgraph streaming ===")
    print(f" - total chunks: {len(namespaced_chunks)}")
    print(f" - chunks with non-empty namespace (subgraph-bubbled): {len(sub_ns)}")
    print(f" - sub1 namespaces: {sub1_ns}")
    print(f" - sub2 namespaces: {sub2_ns}")

    cond1 = len(sub_ns) > 0
    cond2 = len(sub1_ns) > 0 and len(sub2_ns) > 0
    # cond3: no namespace mixes both subgraph tags (no cross-stream)
    cond3 = all(not (any("sub1" in str(p) for p in ns) and any("sub2" in str(p) for p in ns)) for ns in sub_ns)
    ok = cond1 and cond2 and cond3
    print(f" - C1 子图事件冒泡: {cond1}")
    print(f" - C2 两并行子图各有独立 namespace: {cond2}")
    print(f" - C3 namespace 不交叉串流: {cond3}")
    print(f"\nRESULT P2: {'GREEN' if ok else 'RED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
