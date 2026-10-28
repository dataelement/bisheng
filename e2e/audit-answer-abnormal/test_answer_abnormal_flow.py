"""审计列表「是否异常」的接口和落库流转。

只在明确跑 e2e 时执行。缺少环境变量就跳过，避免被普通 pytest 打到 171。
"""

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("BISHENG_E2E") != "1", reason="只在明确跑 e2e 时连接毕昇和 171"
)


def test_abnormal_filter_matches_message_session():
    import httpx
    from sqlalchemy import create_engine, text

    base = os.environ["BISHENG_BASE_URL"].rstrip("/")
    token = os.environ["BISHENG_TOKEN"]
    engine = create_engine(os.environ["BISHENG_MYSQL_URL"])
    headers = {"Authorization": f"Bearer {token}"}

    yes = httpx.get(
        f"{base}/api/v1/audit/session",
        headers=headers,
        params={"answer_abnormal": 1, "page": 1, "page_size": 20},
        timeout=30,
    )
    assert yes.status_code == 200
    body = yes.json()
    rows = body["data"]["data"]
    assert rows, "需要先有一条回答失败的会话, 见 README 的数据前提"
    assert all(row["answer_abnormal"] == 1 for row in rows)

    if rows:
        chat_id = rows[0]["chat_id"]
        with engine.connect() as conn:
            stored = conn.execute(
                text(
                    "SELECT answer_abnormal FROM message_session WHERE chat_id = :chat_id"
                ),
                {"chat_id": chat_id},
            ).scalar()
        assert stored == 1
        again = httpx.get(
            f"{base}/api/v1/audit/session",
            headers=headers,
            params={"answer_abnormal": 0, "page": 1, "page_size": 20},
            timeout=30,
        )
        assert again.status_code == 200
        assert all(row["chat_id"] != chat_id for row in again.json()["data"]["data"])
        with engine.connect() as conn:
            unchanged = conn.execute(
                text(
                    "SELECT answer_abnormal FROM message_session WHERE chat_id = :chat_id"
                ),
                {"chat_id": chat_id},
            ).scalar()
        assert unchanged == 1
