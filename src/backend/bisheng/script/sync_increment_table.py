from datetime import datetime

from bisheng.api.services.workflow import WorkFlowService
from bisheng.knowledge.domain.services.knowledge_service import KnowledgeService
from bisheng.user.domain.services.user import UserService
from bisheng.worker import sync_mid_user_interact_dtl
from bisheng.worker.telemetry.mid_table import sync_mid_user_increment, sync_mid_knowledge_increment, \
    sync_mid_app_increment


def sync_user_increment_table_all():
    """
    Sync user increment table
    """
    first_user = UserService.get_first_user()
    if not first_user:
        print("No users found, skipping user increment table sync.")
        return
    start_date = first_user.create_time.isoformat()
    end_date = datetime.now().isoformat()
    sync_mid_user_increment(start_date, end_date)


def sync_knowledge_increment_table_all():
    """
    Sync knowledge increment table
    """
    first_knowledge = KnowledgeService.get_first_knowledge()
    if not first_knowledge:
        print("No knowledge entries found, skipping knowledge increment table sync.")
        return
    start_date = first_knowledge.create_time.isoformat()
    end_date = datetime.now().isoformat()
    sync_mid_knowledge_increment(start_date, end_date)


def sync_app_increment_table_all():
    """
    Sync all increment tables
    """
    first_app = WorkFlowService.get_first_app()
    if not first_app:
        print("No apps found, skipping app increment table sync.")
        return
    start_date = first_app['create_time'].isoformat()
    end_date = datetime.now().isoformat()
    sync_mid_app_increment(start_date, end_date)


def sync_user_interact_dtl_all():
    first_date = datetime(2025, 12, 1).isoformat()
    end_date = datetime.now().isoformat()
    sync_mid_user_interact_dtl(first_date, end_date)


if __name__ == '__main__':
    sync_user_increment_table_all()
    sync_knowledge_increment_table_all()
    sync_app_increment_table_all()
    sync_user_interact_dtl_all()
