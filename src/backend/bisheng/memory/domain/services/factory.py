"""Production wiring of the memory services (tasks.md "生产装配").

Every integration point (four scenes, management API, workers, workflow node)
takes its service instances from here and never constructs its own.
"""

from __future__ import annotations

_instances: dict = {}


def reset() -> None:
    """Drop cached instances (tests)."""
    _instances.clear()


def _get(name, build):
    if name not in _instances:
        _instances[name] = build()
    return _instances[name]


def get_kv():
    from bisheng.memory.domain.services.kv import RedisKV

    return _get("kv", RedisKV)


def get_index():
    from bisheng.memory.domain.services.index import PlatformMemoryIndex

    return _get("index", PlatformMemoryIndex)


def get_detail_store():
    from bisheng.memory.domain.services.detail_store import MinioDetailStore

    return _get("details", MinioDetailStore)


def get_metrics():
    from bisheng.memory.domain.services.metrics import MemoryMetrics

    return _get("metrics", lambda: MemoryMetrics(get_kv()))


def get_memory_llm():
    from bisheng.memory.domain.services.llm import PlatformMemoryLLM

    return _get("llm", PlatformMemoryLLM)


def get_memory_service():
    from bisheng.memory.domain.services.audit import MemoryAudit
    from bisheng.memory.domain.services.memory_service import MemoryService

    return _get(
        "service",
        lambda: MemoryService(
            index=get_index(), details=get_detail_store(), kv=get_kv(), audit=MemoryAudit(), metrics=get_metrics()
        ),
    )


def get_search_service():
    from bisheng.memory.domain.services.search import SearchService

    return _get("search", lambda: SearchService(index=get_index(), details=get_detail_store(), metrics=get_metrics()))


def get_resident_service():
    from bisheng.memory.domain.services.resident import ResidentService

    return _get("resident", lambda: ResidentService(kv=get_kv(), metrics=get_metrics()))


def get_consolidator():
    from bisheng.memory.domain.services.consolidation_content import ConsolidationContent
    from bisheng.memory.domain.services.consolidation_linsight import LinsightRoundConsolidation
    from bisheng.memory.domain.services.consolidator import Consolidator

    def _build():
        content = ConsolidationContent(get_memory_llm())
        service = get_memory_service()
        return Consolidator(
            service=service,
            kv=get_kv(),
            metrics=get_metrics(),
            content_fn=content,
            # Deep-research rounds are consolidated per round, not by message watermark (R8).
            extra_steps=[LinsightRoundConsolidation(service=service, content=content)],
        )

    return _get("consolidator", _build)
