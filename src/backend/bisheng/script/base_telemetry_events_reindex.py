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

import time


def wait_for_task(
        es,
        task_id: str,
        poll_interval: int = 10,
        timeout: int = 3600,
):
    """
    轮询 ES task 状态，直到完成或超时
    """
    start_time = time.time()

    while True:

        task_info = es.tasks.get(task_id=task_id)
        completed = task_info.get("completed", False)

        if completed:
            response = task_info.get("response", {})
            failures = response.get("failures", [])
            total = response.get("total", 0)
            created = response.get("created", 0)
            updated = response.get("updated", 0)

            print(
                f"[REINDEX DONE] total={total}, created={created}, updated={updated}"
            )

            if failures:
                raise RuntimeError(f"Reindex failures: {failures}")

            return response

        if time.time() - start_time > timeout:
            raise TimeoutError(f"Reindex task timeout: {task_id}")

        status = task_info.get("task", {}).get("status", {})
        print(
            f"[REINDEX RUNNING] "
            f"total={status.get('total', 0)} "
            f"created={status.get('created', 0)} "
            f"updated={status.get('updated', 0)}"
        )

        time.sleep(poll_interval)


def count_docs(es, index):
    return es.count(index=index)["count"]


if __name__ == '__main__':
    es_conn = get_statistics_es_connection_sync()
    temp_index_name = "base_telemetry_events_v1"
    original_index_name = "base_telemetry_events"

    # 1. 记录原始数据量
    try:
        source_count = count_docs(es_conn, original_index_name)
        print(f"Original doc count: {source_count}")
    except:
        source_count = 0
        print("Original index might not exist.")

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

    resp = es_conn.options(request_timeout=3600).reindex(
        body=reindex_body,
        wait_for_completion=False
    )

    task_id = resp["task"]
    print(f"Reindex started, task_id={task_id}")

    wait_for_task(
        es_conn,
        task_id=task_id,
        poll_interval=5,
        timeout=3600
    )

    # 删除原始索引
    es_conn.indices.delete(index=original_index_name)

    # 将临时索引重命名为原始索引名
    es_conn.indices.put_alias(index=temp_index_name, name=original_index_name)


    print(f"Reindexed data to {original_index_name} successfully.")

