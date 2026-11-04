"""Backfill person belonging names onto existing user and QA statistics."""

from elasticsearch import helpers
from loguru import logger

from bisheng.core.logger import trace_id_var
from bisheng.telemetry.domain.mid_table.belonging_organization import (
    belonging_names,
    merge_belonging_backfill,
    organization_department_ids,
    qa_belonging_names,
)
from bisheng.telemetry.domain.mid_table.content_stat_reconcile import ContentStatReconciler
from bisheng.telemetry.domain.mid_table.daily_participation import DailyParticipationFact
from bisheng.telemetry.domain.mid_table.realtime_qa_question import RealtimeQaQuestionFact
from bisheng.telemetry.domain.mid_table.retry_budget import bounded_telemetry_task, checkpoint
from bisheng.utils import generate_uuid
from bisheng.worker.main import bisheng_celery
from bisheng.worker.telemetry.mid_table import (
    _get_departments_by_ids,
    _get_dimension_department_map,
    _load_unique_primary_departments,
)

_BATCH = 200


def _path_map(departments: list) -> dict:
    starts = [department for department in departments if department is not None]
    if not starts:
        return {}
    path_ids: list[int] = []
    for department in starts:
        for department_id in organization_department_ids(department):
            if department_id not in path_ids:
                path_ids.append(department_id)
    return _get_departments_by_ids(path_ids) | _get_dimension_department_map(starts)


def _reconcile(fact, names_by_id: dict[str, dict]) -> dict:
    if not names_by_id:
        return {"checked": 0, "updated": 0, "created": 0, "unchanged": 0}
    reconciler = ContentStatReconciler(fact._es_client_sync, fact._index_name, str)
    return reconciler.reconcile(
        {key: {"names": names} for key, names in names_by_id.items()},
        merge_belonging_backfill,
    )


def _scan(fact, query: dict):
    return helpers.scan(
        fact._es_client_sync,
        index=fact._index_name,
        size=_BATCH,
        query=query,
        scroll="5m",
    )


def backfill_participation_names(fact: DailyParticipationFact) -> dict:
    checked = written = cleared = unchanged = 0
    hits = _scan(fact, {"query": {"term": {"metric_source": "participation"}}})
    batch = []
    try:
        for hit in hits:
            batch.append(hit)
            if len(batch) >= _BATCH:
                stats = _flush_participation(fact, batch)
                checked += stats["checked"]
                written += stats["written"]
                cleared += stats["cleared"]
                unchanged += stats["unchanged"]
                batch = []
        if batch:
            stats = _flush_participation(fact, batch)
            checked += stats["checked"]
            written += stats["written"]
            cleared += stats["cleared"]
            unchanged += stats["unchanged"]
    finally:
        hits.close()
    logger.info(
        "belonging.backfill source=participation checked={} written={} cleared={} unchanged={}",
        checked,
        written,
        cleared,
        unchanged,
    )
    return {"checked": checked, "written": written, "cleared": cleared, "unchanged": unchanged}


def _flush_participation(fact, batch: list) -> dict:
    checkpoint()
    sources = [(hit["_id"], hit.get("_source") or {}) for hit in batch]
    department_ids = [
        int(source["primary_department_id"])
        for _, source in sources
        if str(source.get("primary_department_id") or "").isdigit()
    ]
    departments = _get_departments_by_ids(department_ids)
    by_id = _path_map(list(departments.values()))
    names_by_id = {}
    cleared = 0
    for key, source in sources:
        department_id = source.get("primary_department_id")
        department = departments.get(int(department_id)) if str(department_id or "").isdigit() else None
        names = belonging_names(department, by_id, int(source.get("tenant_id") or 1))
        names_by_id[key] = names
        if not names:
            cleared += 1
    result = _reconcile(fact, names_by_id)
    return {
        "checked": len(batch),
        "written": result["updated"] + result["created"],
        "cleared": cleared,
        "unchanged": result["unchanged"],
    }


def backfill_increment_names(fact: DailyParticipationFact) -> dict:
    checked = written = cleared = unchanged = 0
    hits = _scan(fact, {"query": {"term": {"metric_source": "increment"}}})
    batch = []
    try:
        for hit in hits:
            batch.append(hit)
            if len(batch) >= _BATCH:
                stats = _flush_increment(fact, batch)
                checked += stats["checked"]
                written += stats["written"]
                cleared += stats["cleared"]
                unchanged += stats["unchanged"]
                batch = []
        if batch:
            stats = _flush_increment(fact, batch)
            checked += stats["checked"]
            written += stats["written"]
            cleared += stats["cleared"]
            unchanged += stats["unchanged"]
    finally:
        hits.close()
    logger.info(
        "belonging.backfill source=increment checked={} written={} cleared={} unchanged={}",
        checked,
        written,
        cleared,
        unchanged,
    )
    return {"checked": checked, "written": written, "cleared": cleared, "unchanged": unchanged}


def _flush_increment(fact, batch: list) -> dict:
    checkpoint()
    sources = [(hit["_id"], hit.get("_source") or {}) for hit in batch]
    user_ids = [int(source["user_id"]) for _, source in sources if str(source.get("user_id") or "").isdigit()]
    unique, ambiguous = _load_unique_primary_departments(user_ids)
    by_id = _path_map(list(unique.values()))
    names_by_id = {}
    cleared = 0
    for key, source in sources:
        user_id = int(source["user_id"]) if str(source.get("user_id") or "").isdigit() else None
        department = None if user_id is None or user_id in ambiguous else unique.get(user_id)
        row_tenant = int(getattr(department, "tenant_id", None) or 1)
        names = belonging_names(department, by_id, row_tenant)
        names_by_id[key] = names
        if not names:
            cleared += 1
    result = _reconcile(fact, names_by_id)
    return {
        "checked": len(batch),
        "written": result["updated"] + result["created"],
        "cleared": cleared,
        "unchanged": result["unchanged"],
    }


def backfill_question_names(fact: RealtimeQaQuestionFact) -> dict:
    checked = written = cleared = unchanged = 0
    hits = _scan(fact, {"query": {"match_all": {}}})
    batch = []
    try:
        for hit in hits:
            batch.append(hit)
            if len(batch) >= _BATCH:
                stats = _flush_questions(fact, batch)
                checked += stats["checked"]
                written += stats["written"]
                cleared += stats["cleared"]
                unchanged += stats["unchanged"]
                batch = []
        if batch:
            stats = _flush_questions(fact, batch)
            checked += stats["checked"]
            written += stats["written"]
            cleared += stats["cleared"]
            unchanged += stats["unchanged"]
    finally:
        hits.close()
    logger.info(
        "belonging.backfill source=question checked={} written={} cleared={} unchanged={}",
        checked,
        written,
        cleared,
        unchanged,
    )
    return {"checked": checked, "written": written, "cleared": cleared, "unchanged": unchanged}


def _flush_questions(fact, batch: list) -> dict:
    checkpoint()
    sources = [(hit["_id"], hit.get("_source") or {}) for hit in batch]
    department_ids = [
        int(source["primary_department_id"])
        for _, source in sources
        if str(source.get("primary_department_id") or "").isdigit()
    ]
    departments = _get_departments_by_ids(department_ids)
    by_id = _path_map(list(departments.values()))
    names_by_id = {}
    cleared = 0
    for key, source in sources:
        department_id = source.get("primary_department_id")
        department = departments.get(int(department_id)) if str(department_id or "").isdigit() else None
        names = qa_belonging_names(source, department, by_id)
        names_by_id[key] = names
        if not names:
            cleared += 1
    result = _reconcile(fact, names_by_id)
    return {
        "checked": len(batch),
        "written": result["updated"] + result["created"],
        "cleared": cleared,
        "unchanged": result["unchanged"],
    }


@bisheng_celery.task()
@bounded_telemetry_task
def backfill_belonging_organization_names() -> dict:
    """Fill belonging company, department and office on existing user and QA rows."""
    trace_id_var.set(f"backfill_belonging_organization_names_{generate_uuid()}")
    user_fact = DailyParticipationFact()
    question_fact = RealtimeQaQuestionFact()
    participation = backfill_participation_names(user_fact)
    increment = backfill_increment_names(user_fact)
    questions = backfill_question_names(question_fact)
    return {"participation": participation, "increment": increment, "questions": questions}
