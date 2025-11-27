# register tasks
from bisheng.worker.main import bisheng_celery
from bisheng.worker.test.test import *
from bisheng.worker.knowledge.file_worker import file_copy_celery, parse_knowledge_file_celery, \
    retry_knowledge_file_celery
from bisheng.worker.knowledge.rebuild_knowledge_worker import rebuild_knowledge_celery
from bisheng.worker.workflow.tasks import *
