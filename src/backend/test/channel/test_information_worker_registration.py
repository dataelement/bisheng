import importlib

from bisheng.core.config.settings import CeleryConf, IntelligenceCenterConf

INFORMATION_TASKS = {
    "dispatch_information_subscription_reconcile": "bisheng.worker.information.reconcile",
    "reconcile_information_subscriptions": "bisheng.worker.information.reconcile",
    "dispatch_information_article_poll": "bisheng.worker.information.article",
    "sync_information_articles": "bisheng.worker.information.article",
    "route_new_information_articles": "bisheng.worker.information.knowledge_delivery",
    "deliver_information_articles_to_config": "bisheng.worker.information.knowledge_delivery",
}


def test_default_schedule_contains_only_two_information_dispatchers():
    conf = CeleryConf()
    information_tasks = {key: value for key, value in conf.beat_schedule.items() if "information" in value["task"]}

    assert set(information_tasks) == {
        "dispatch_information_subscription_reconcile",
        "dispatch_information_article_poll",
    }
    assert information_tasks["dispatch_information_subscription_reconcile"]["schedule"] == 3600.0
    assert information_tasks["dispatch_information_article_poll"]["schedule"] == 1800.0


def test_information_tasks_have_no_dedicated_queue_route():
    conf = CeleryConf()
    assert all("information" not in route for route in conf.task_routers)


def test_six_information_tasks_are_registered_without_old_task_names():
    worker = importlib.import_module("bisheng.worker")

    for task_name, module_name in INFORMATION_TASKS.items():
        task = getattr(worker, task_name)
        assert task.run.__module__ == module_name
        assert task.run.__name__ == task_name
    assert not hasattr(worker, "sync_information_article")
    assert not hasattr(worker, "reconcile_all_tenants")


def test_information_runtime_defaults_are_enabled_and_limit_is_validated():
    conf = IntelligenceCenterConf()
    assert conf.information_subscription_auto_unsubscribe_enabled is True
    assert conf.information_knowledge_delivery_enabled is True
    assert conf.information_initial_article_limit == 20
