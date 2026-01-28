from bisheng.core.search.elasticsearch.manager import get_statistics_es_connection_sync

INDEX_MAPPING = {
    "mappings": {  # Defining the indexed Mapping
        "properties": {
            "event_id": {"type": "keyword"},
            "event_type": {"type": "keyword"},
            "trace_id": {"type": "keyword"},
            "timestamp": {"type": "date", "format": "strict_date_optional_time||epoch_second"},
            "user_context": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "integer"},
                    "user_name": {"type": "keyword"},
                    "user_group_infos": {
                        "type": "object",
                        "properties": {
                            "user_group_id": {"type": "integer"},
                            "user_group_name": {"type": "keyword"}
                        }
                    },
                    "user_role_infos": {
                        "type": "object",
                        "properties": {
                            "role_id": {"type": "integer"},
                            "role_name": {"type": "keyword"},
                            "group_id": {"type": "integer"},
                        }
                    }
                }
            },
            "event_data": {
                "type": "object",
                "dynamic": True
            }
        }
    }
}

if __name__ == '__main__':
    es_conn = get_statistics_es_connection_sync()

    # 临时索引名称
    temp_index_name = "base_telemetry_events_temp_reindex"
    original_index_name = "base_telemetry_events"

    # 创建临时索引
    if not es_conn.indices.exists(index=temp_index_name):
        es_conn.indices.create(index=temp_index_name, body=INDEX_MAPPING)
        print(f"Created temporary index: {temp_index_name}")

    # 使用Elasticsearch的_reindex API进行数据迁移
    reindex_body = {
        "source": {
            "index": original_index_name
        },
        "dest": {
            "index": temp_index_name
        }
    }

    es_conn.reindex(body=reindex_body, wait_for_completion=True, request_timeout=3600)
    print(f"Reindexed data from {original_index_name} to {temp_index_name}")

    # 删除原始索引
    es_conn.indices.delete(index=original_index_name)

    print(f"Deleted original index: {original_index_name}")

    # 创建新的原始索引
    es_conn.indices.create(index=original_index_name, body=INDEX_MAPPING)
    print(f"Created new index: {original_index_name}")

    # 使用_reindex API将数据从临时索引迁移回原始索引
    reindex_back_body = {
        "source": {
            "index": temp_index_name
        },
        "dest": {
            "index": original_index_name
        }
    }

    es_conn.reindex(body=reindex_back_body, wait_for_completion=True, request_timeout=3600)

    # 删除临时索引
    es_conn.indices.delete(index=temp_index_name)

    print(f"Reindexed data back to {original_index_name} and deleted temporary index: {temp_index_name}")
    print("Reindexing process completed successfully.")
