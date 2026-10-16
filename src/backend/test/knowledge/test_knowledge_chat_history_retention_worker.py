import inspect

import bisheng.worker.knowledge.knowledge_chat_history_retention as worker_module
from bisheng.worker.config import task_routes
from bisheng.worker.knowledge.knowledge_chat_history_retention import (
    TASK_NAME,
    rehome_knowledge_chat_sessions,
)


def test_rehome_task_registration_and_delivery_contract():
    source = inspect.getsource(worker_module)

    assert TASK_NAME in source
    assert "name=TASK_NAME, acks_late=True, max_retries=3" in source
    assert callable(rehome_knowledge_chat_sessions.run)
    assert task_routes["bisheng.worker.knowledge.*"]["queue"] == "knowledge_celery"
