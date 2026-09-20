"""空环境补齐 ES 埋点索引, 避开官方 reindex 在索引不存在时 DELETE 404.

不写 MySQL. 只碰 ES: base_telemetry_events / base_telemetry_events_v1.
最后一行打印 NEED_REINDEX=0|1, 给 hop 决定要不要跑官方迁移.
"""

from bisheng.core.search.elasticsearch.manager import get_statistics_es_connection_sync

ORIG = "base_telemetry_events"
TEMP = "base_telemetry_events_v1"

# 与 2.3.0 镜像里 base_telemetry_events_reindex.py 同一套 mapping
INDEX_MAPPING = {
    "mappings": {
        "properties": {
            "event_id": {"type": "keyword"},
            "event_type": {"type": "keyword"},
            "trace_id": {"type": "keyword"},
            "timestamp": {
                "type": "date",
                "format": "strict_date_optional_time||epoch_second",
            },
            "user_context": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "integer"},
                    "user_name": {"type": "keyword"},
                    "user_group_infos": {
                        "type": "object",
                        "properties": {
                            "user_group_id": {"type": "integer"},
                            "user_group_name": {"type": "keyword"},
                        },
                    },
                    "user_role_infos": {
                        "type": "object",
                        "properties": {
                            "role_id": {"type": "integer"},
                            "role_name": {"type": "keyword"},
                            "group_id": {"type": "integer"},
                        },
                    },
                },
            },
            "event_data": {"type": "object", "dynamic": True},
        }
    }
}


def exists(es, name: str) -> bool:
    return bool(es.indices.exists(index=name))


def is_alias(es, name: str) -> bool:
    try:
        es.indices.get_alias(name=name)
        return True
    except Exception:
        return False


def main() -> None:
    es = get_statistics_es_connection_sync()

    if exists(es, ORIG):
        if is_alias(es, ORIG):
            print("base_telemetry_events 已是别名, 跳过官方 reindex")
            print("NEED_REINDEX=0")
            return
        print("base_telemetry_events 是实体索引, 交给官方 reindex")
        print("NEED_REINDEX=1")
        return

    if exists(es, TEMP):
        es.indices.put_alias(index=TEMP, name=ORIG)
        print("已把 base_telemetry_events_v1 别名为 base_telemetry_events")
        print("NEED_REINDEX=0")
        return

    es.indices.create(index=ORIG, body=INDEX_MAPPING)
    print("空环境: 已建空索引 base_telemetry_events, 交给官方 reindex 收成 v1+别名")
    print("NEED_REINDEX=1")


if __name__ == "__main__":
    main()
