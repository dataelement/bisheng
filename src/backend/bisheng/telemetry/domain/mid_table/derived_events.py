from __future__ import annotations

import datetime
from collections.abc import Iterable
from typing import Any

from elasticsearch import Elasticsearch, helpers
from elasticsearch import exceptions as es_exceptions
from loguru import logger

from bisheng.common.services import telemetry_service
from bisheng.core.search.elasticsearch.manager import get_statistics_es_connection_sync


def keyword_text_field() -> dict[str, Any]:
    return {
        "type": "keyword",
        "fields": {"text": {"type": "text", "analyzer": "single_char_analyzer"}},
    }


SINGLE_CHAR_SETTINGS = {
    "analysis": {
        "tokenizer": {
            "single_char_tokenizer": {
                "type": "ngram",
                "min_gram": 1,
                "max_gram": 1,
                "token_chars": ["letter", "digit", "punctuation", "symbol"],
            }
        },
        "analyzer": {
            "single_char_analyzer": {
                "type": "custom",
                "tokenizer": "single_char_tokenizer",
            }
        },
    }
}

COMMON_USER_PROPERTIES = {
    "timestamp": {"type": "date", "format": "strict_date_optional_time||epoch_second"},
    "user_id": keyword_text_field(),
    "user_name": keyword_text_field(),
    "user_group_infos": {
        "type": "nested",
        "properties": {
            "user_group_id": keyword_text_field(),
            "user_group_name": keyword_text_field(),
        },
    },
    "user_role_infos": {
        "type": "nested",
        "properties": {
            "role_id": keyword_text_field(),
            "role_name": keyword_text_field(),
            "group_id": keyword_text_field(),
        },
    },
    "user_department_infos": {
        "type": "nested",
        "properties": {
            "department_id": keyword_text_field(),
            "department_name": keyword_text_field(),
        },
    },
}


def build_mapping(extra_properties: dict[str, Any] | None = None) -> dict[str, Any]:
    properties = COMMON_USER_PROPERTIES | (extra_properties or {})
    return {
        "settings": SINGLE_CHAR_SETTINGS,
        "mappings": {"properties": properties},
    }


def previous_day_range() -> tuple[int, int]:
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    start_time = int(datetime.datetime.combine(yesterday, datetime.time.min).timestamp())
    end_time = int(datetime.datetime.combine(today, datetime.time.min).timestamp())
    return start_time, end_time


def user_doc_fields(user_context: dict[str, Any]) -> dict[str, Any]:
    return {
        "user_id": user_context.get("user_id"),
        "user_name": user_context.get("user_name"),
        "user_group_infos": user_context.get("user_group_infos", []),
        "user_role_infos": user_context.get("user_role_infos", []),
        "user_department_infos": user_context.get("user_department_infos", []),
    }


class BaseDerivedEventJob:
    index_name: str = ""
    es_mapping: dict[str, Any] = {}
    base_batch_size: int = 1000

    def __init__(self, es_client: Elasticsearch | None = None):
        self._es_client = es_client or get_statistics_es_connection_sync()
        self.base_telemetry_events_index = telemetry_service.index_name

    def ensure_index_exists(self) -> None:
        if not self.index_name:
            return
        try:
            if not self._es_client.indices.exists(index=self.index_name):
                self._es_client.indices.create(index=self.index_name, body=self.es_mapping)
        except es_exceptions.RequestError as exc:
            if "resource_already_exists_exception" not in str(exc):
                logger.exception("Failed to create telemetry index {}", self.index_name)
                raise

    def init_index(self, end_time: datetime.datetime | None = None) -> None:
        logger.info("Initializing telemetry index '{}'.", self.index_name)
        if self._es_client.indices.exists(index=self.index_name):
            return

        self._es_client.indices.create(index=self.index_name, body=self.es_mapping)
        end_time = datetime.datetime.combine(datetime.date.today(), datetime.time.min) if end_time is None else end_time
        self._run_incremental_update(end_time=int(end_time.timestamp()))

    def add_one_day_data(self) -> None:
        start_time, end_time = previous_day_range()
        self._run_incremental_update(start_time=start_time, end_time=end_time)

    def _run_bulk(self, actions: Iterable[dict[str, Any]]) -> None:
        success, errors = helpers.bulk(
            self._es_client,
            actions,
            chunk_size=self.base_batch_size,
            raise_on_error=False,
        )
        logger.info("Telemetry index '{}' updated. indexed={}", self.index_name, success)
        if errors:
            logger.error("Telemetry index '{}' bulk errors. first_error={}", self.index_name, errors[0])
            raise RuntimeError(f"Failed to bulk index {len(errors)} documents into {self.index_name}.")

    def _run_incremental_update(self, start_time: int | None = None, end_time: int | None = None) -> None:
        raise NotImplementedError


class ScanEventJob(BaseDerivedEventJob):
    event_types: tuple[str, ...] = ()

    def _build_query(self, start_time: int | None = None, end_time: int | None = None) -> dict[str, Any]:
        if len(self.event_types) == 1:
            event_filter = {"term": {"event_type": self.event_types[0]}}
        else:
            event_filter = {"terms": {"event_type": list(self.event_types)}}

        query = {"query": {"bool": {"must": [event_filter]}}}
        time_filter: dict[str, Any] = {}
        if start_time:
            time_filter["gte"] = start_time
        if end_time:
            time_filter["lte"] = end_time
        if time_filter:
            time_filter["format"] = "epoch_second"
            query["query"]["bool"]["must"].append({"range": {"timestamp": time_filter}})
        return query

    def _transform_hit_to_actions(self, hit: dict[str, Any]) -> list[dict[str, Any]]:
        raise NotImplementedError

    def _actions_generator(self, hits_iterator: Iterable[dict[str, Any]]) -> Iterable[dict[str, Any]]:
        for hit in hits_iterator:
            yield from self._transform_hit_to_actions(hit)

    def _run_incremental_update(self, start_time: int | None = None, end_time: int | None = None) -> None:
        self.ensure_index_exists()
        start_str = datetime.datetime.fromtimestamp(start_time).isoformat() if start_time else "the beginning"
        end_str = datetime.datetime.fromtimestamp(end_time).isoformat() if end_time else "now"
        logger.info("Starting telemetry index '{}' update from {} to {}.", self.index_name, start_str, end_str)

        hits_iterator = helpers.scan(
            client=self._es_client,
            query=self._build_query(start_time, end_time),
            index=self.base_telemetry_events_index,
            size=self.base_batch_size,
        )
        self._run_bulk(self._actions_generator(hits_iterator))


class MidActiveUserJob(BaseDerivedEventJob):
    index_name = "mid_active_user"
    es_mapping = build_mapping()
    event_types = (
        "user_login",
        "new_message_session",
        "delete_message_session",
        "new_application",
        "edit_application",
        "delete_application",
        "new_knowledge_base",
        "delete_knowledge_base",
        "new_knowledge_file",
        "delete_knowledge_file",
    )

    def _build_bool_query(self, start_time: int | None = None, end_time: int | None = None) -> dict[str, Any]:
        query = {"bool": {"must": [{"terms": {"event_type": list(self.event_types)}}]}}
        time_filter: dict[str, Any] = {}
        if start_time:
            time_filter["gte"] = start_time
        if end_time:
            time_filter["lte"] = end_time
        if time_filter:
            time_filter["format"] = "epoch_second"
            query["bool"]["must"].append({"range": {"timestamp": time_filter}})
        return query

    def _scroll_composite_aggs(self, bool_query: dict[str, Any]) -> Iterable[tuple[dict[str, Any], str]]:
        after_key = None
        while True:
            body = {
                "size": 0,
                "query": bool_query,
                "aggs": {
                    "pagination_buckets": {
                        "composite": {
                            "size": self.base_batch_size,
                            "sources": [
                                {
                                    "activity_date": {
                                        "date_histogram": {
                                            "field": "timestamp",
                                            "calendar_interval": "1d",
                                            "format": "yyyy-MM-dd",
                                            "time_zone": "+08:00",
                                        }
                                    }
                                },
                                {"user_id": {"terms": {"field": "user_context.user_id"}}},
                            ],
                        },
                        "aggs": {
                            "latest_record": {"top_hits": {"size": 1, "sort": [{"timestamp": {"order": "desc"}}]}}
                        },
                    }
                },
            }
            if after_key:
                body["aggs"]["pagination_buckets"]["composite"]["after"] = after_key

            response = self._es_client.search(index=self.base_telemetry_events_index, body=body)
            buckets = response.get("aggregations", {}).get("pagination_buckets", {}).get("buckets", [])
            if not buckets:
                break

            for bucket in buckets:
                date_str = bucket.get("key", {}).get("activity_date")
                if not date_str or date_str.startswith("1970"):
                    continue
                hits_in_bucket = bucket.get("latest_record", {}).get("hits", {}).get("hits", [])
                if hits_in_bucket:
                    yield hits_in_bucket[0], date_str

            after_key = response.get("aggregations", {}).get("pagination_buckets", {}).get("after_key")
            if not after_key:
                break

    def _transform_hit_to_action(self, hit: dict[str, Any], date_key: str | None = None) -> dict[str, Any]:
        source = hit.get("_source", {})
        user_context = source.get("user_context", {})
        user_id = user_context.get("user_id")
        return {
            "_index": self.index_name,
            "_id": f"{user_id}_{date_key}" if date_key and user_id else hit.get("_id"),
            "_source": {
                "timestamp": source.get("timestamp"),
                **user_doc_fields(user_context),
            },
        }

    def _run_incremental_update(self, start_time: int | None = None, end_time: int | None = None) -> None:
        self.ensure_index_exists()
        start_str = datetime.datetime.fromtimestamp(start_time).isoformat() if start_time else "the beginning"
        end_str = datetime.datetime.fromtimestamp(end_time).isoformat() if end_time else "now"
        logger.info("Starting telemetry index '{}' update from {} to {}.", self.index_name, start_str, end_str)
        hits_iterator = self._scroll_composite_aggs(self._build_bool_query(start_time, end_time))
        self._run_bulk(self._transform_hit_to_action(hit, date_str) for hit, date_str in hits_iterator)


class MidDocParseDtlJob(ScanEventJob):
    index_name = "mid_doc_parse_dtl"
    event_types = ("file_parse",)
    es_mapping = build_mapping(
        {
            "event_id": {"type": "keyword"},
            "parse_type": keyword_text_field(),
            "status": keyword_text_field(),
            "app_type": keyword_text_field(),
        }
    )

    def _transform_hit_to_actions(self, hit: dict[str, Any]) -> list[dict[str, Any]]:
        source = hit.get("_source", {})
        user_context = source.get("user_context", {})
        event_data = source.get("event_data", {})
        return [
            {
                "_index": self.index_name,
                "_id": hit.get("_id"),
                "_source": {
                    "event_id": source.get("event_id"),
                    "timestamp": source.get("timestamp"),
                    **user_doc_fields(user_context),
                    "parse_type": event_data.get("file_parse_parse_type"),
                    "status": event_data.get("file_parse_status"),
                    "app_type": event_data.get("file_parse_app_type"),
                },
            }
        ]


class MidSessionsIncrementJob(ScanEventJob):
    index_name = "mid_sessions_increment"
    event_types = ("new_message_session",)
    es_mapping = build_mapping(
        {
            "event_id": {"type": "keyword"},
            "event_type": keyword_text_field(),
            "trace_id": {"type": "keyword"},
            "session_id": keyword_text_field(),
            "app_type": keyword_text_field(),
            "app_name": keyword_text_field(),
            "app_id": keyword_text_field(),
            "source": keyword_text_field(),
        }
    )

    def _transform_hit_to_actions(self, hit: dict[str, Any]) -> list[dict[str, Any]]:
        source = hit.get("_source", {})
        user_context = source.get("user_context", {})
        event_data = source.get("event_data", {})
        return [
            {
                "_index": self.index_name,
                "_id": hit.get("_id"),
                "_source": {
                    "event_id": source.get("event_id"),
                    "event_type": source.get("event_type"),
                    "trace_id": source.get("trace_id"),
                    "timestamp": source.get("timestamp"),
                    **user_doc_fields(user_context),
                    "session_id": event_data.get("new_message_session_session_id"),
                    "app_type": event_data.get("new_message_session_app_type"),
                    "app_name": event_data.get("new_message_session_app_name"),
                    "app_id": event_data.get("new_message_session_app_id"),
                    "source": event_data.get("new_message_session_source"),
                },
            }
        ]


class MidToolCallDtlJob(ScanEventJob):
    index_name = "mid_tool_call_dtl"
    event_types = ("tool_invoke",)
    es_mapping = build_mapping(
        {
            "event_id": {"type": "keyword"},
            "app_id": keyword_text_field(),
            "app_type": keyword_text_field(),
            "app_name": keyword_text_field(),
            "tool_id": keyword_text_field(),
            "tool_name": keyword_text_field(),
            "tool_type": keyword_text_field(),
            "status": keyword_text_field(),
        }
    )

    def _transform_hit_to_actions(self, hit: dict[str, Any]) -> list[dict[str, Any]]:
        source = hit.get("_source", {})
        user_context = source.get("user_context", {})
        event_data = source.get("event_data", {})
        return [
            {
                "_index": self.index_name,
                "_id": hit.get("_id"),
                "_source": {
                    "event_id": source.get("event_id"),
                    "timestamp": source.get("timestamp"),
                    **user_doc_fields(user_context),
                    "app_type": event_data.get("tool_invoke_app_type"),
                    "app_name": event_data.get("tool_invoke_app_name"),
                    "app_id": event_data.get("tool_invoke_app_id"),
                    "tool_id": event_data.get("tool_invoke_tool_id"),
                    "tool_name": event_data.get("tool_invoke_tool_name"),
                    "tool_type": event_data.get("tool_invoke_tool_type"),
                    "status": event_data.get("tool_invoke_status"),
                },
            }
        ]


class MidModelCallDtlJob(ScanEventJob):
    index_name = "mid_model_call_dtl"
    event_types = ("model_invoke",)
    es_mapping = build_mapping(
        {
            "event_id": {"type": "keyword"},
            "model_id": keyword_text_field(),
            "model_name": keyword_text_field(),
            "model_type": keyword_text_field(),
            "model_server_id": keyword_text_field(),
            "model_server_name": keyword_text_field(),
            "app_id": keyword_text_field(),
            "app_name": keyword_text_field(),
            "app_type": keyword_text_field(),
            "start_time": {"type": "date", "format": "strict_date_optional_time||epoch_second||epoch_millis"},
            "end_time": {"type": "date", "format": "strict_date_optional_time||epoch_second||epoch_millis"},
            "minute_ts": {"type": "date", "format": "epoch_millis"},
            "first_token_cost_time": {"type": "integer"},
            "status": keyword_text_field(),
            "is_stream": {"type": "boolean"},
            "input_token": {"type": "integer"},
            "output_token": {"type": "integer"},
            "cache_token": {"type": "integer"},
            "total_token": {"type": "integer"},
        }
    )

    @staticmethod
    def _explode_to_minutes(doc: dict[str, Any]) -> list[dict[str, Any]]:
        start_sec = doc.get("start_time")
        end_sec = doc.get("end_time")
        if not start_sec or not end_sec:
            return [doc]

        start_ms = int(start_sec * 1000)
        end_ms = int(end_sec * 1000)
        start_ms = start_ms - (start_ms % 60000)
        end_ms = end_ms - (end_ms % 60000)

        docs = []
        minute_ts = start_ms
        while minute_ts <= end_ms:
            minute_doc = doc.copy()
            minute_doc["minute_ts"] = minute_ts
            docs.append(minute_doc)
            minute_ts += 60000
        return docs

    def _transform_hit_to_actions(self, hit: dict[str, Any]) -> list[dict[str, Any]]:
        source = hit.get("_source", {})
        user_context = source.get("user_context", {})
        event_data = source.get("event_data", {})
        doc = {
            "event_id": source.get("event_id"),
            "timestamp": source.get("timestamp"),
            **user_doc_fields(user_context),
            "model_id": event_data.get("model_invoke_model_id"),
            "model_name": event_data.get("model_invoke_model_name"),
            "model_type": event_data.get("model_invoke_model_type"),
            "model_server_id": event_data.get("model_invoke_model_server_id"),
            "model_server_name": event_data.get("model_invoke_model_server_name"),
            "app_id": event_data.get("model_invoke_app_id"),
            "app_name": event_data.get("model_invoke_app_name"),
            "app_type": event_data.get("model_invoke_app_type"),
            "start_time": event_data.get("model_invoke_start_time"),
            "end_time": event_data.get("model_invoke_end_time"),
            "first_token_cost_time": event_data.get("model_invoke_first_token_cost_time"),
            "status": event_data.get("model_invoke_status"),
            "is_stream": event_data.get("model_invoke_is_stream"),
            "input_token": event_data.get("model_invoke_input_token"),
            "output_token": event_data.get("model_invoke_output_token"),
            "cache_token": event_data.get("model_invoke_cache_token"),
            "total_token": event_data.get("model_invoke_total_token"),
        }
        actions = []
        for minute_doc in self._explode_to_minutes(doc):
            minute_ts = minute_doc.get("minute_ts")
            doc_id = f"{hit.get('_id')}_{minute_ts}" if minute_ts is not None else hit.get("_id")
            actions.append({"_index": self.index_name, "_id": doc_id, "_source": minute_doc})
        return actions


class MidSessionRunDtlJob(ScanEventJob):
    index_name = "mid_session_run_dtl"
    event_types = ("application_alive", "application_process")
    es_mapping = build_mapping(
        {
            "event_id": {"type": "keyword"},
            "duration_seconds": {"type": "integer"},
            "app_id": keyword_text_field(),
            "app_name": keyword_text_field(),
            "app_type": keyword_text_field(),
            "end_time": {"type": "date", "format": "strict_date_optional_time||epoch_second"},
            "minute_ts": {"type": "date", "format": "epoch_millis"},
            "session_id": keyword_text_field(),
        }
    )

    @staticmethod
    def _explode_to_minutes(doc: dict[str, Any]) -> list[dict[str, Any]]:
        start_sec = doc.get("timestamp")
        end_sec = doc.get("end_time")
        if not start_sec or not end_sec:
            return []

        start_ms = int(start_sec * 1000)
        end_ms = int(end_sec * 1000)
        start_ms = start_ms - (start_ms % 60000)
        end_ms = end_ms - (end_ms % 60000)

        docs = []
        minute_ts = start_ms
        while minute_ts <= end_ms:
            minute_doc = doc.copy()
            minute_doc["minute_ts"] = minute_ts
            docs.append(minute_doc)
            minute_ts += 60000
        return docs

    def _transform_hit_to_actions(self, hit: dict[str, Any]) -> list[dict[str, Any]]:
        source = hit.get("_source", {})
        user_context = source.get("user_context", {})
        event_data = source.get("event_data", {})
        event_type = source.get("event_type")
        doc = {
            **user_doc_fields(user_context),
            "event_id": source.get("event_id"),
            "duration_seconds": event_data.get(f"{event_type}_process_time", 0),
            "app_id": event_data.get(f"{event_type}_app_id"),
            "app_name": event_data.get(f"{event_type}_app_name"),
            "app_type": event_data.get(f"{event_type}_app_type"),
            "timestamp": event_data.get(f"{event_type}_start_time"),
            "end_time": event_data.get(f"{event_type}_end_time"),
            "session_id": event_data.get(f"{event_type}_chat_id"),
        }
        if doc["duration_seconds"] != 0:
            return [{"_index": self.index_name, "_id": hit.get("_id"), "_source": doc}]

        actions = []
        for minute_doc in self._explode_to_minutes(doc):
            actions.append(
                {
                    "_index": self.index_name,
                    "_id": f"{hit.get('_id')}_{minute_doc['minute_ts']}",
                    "_source": minute_doc,
                }
            )
        return actions
