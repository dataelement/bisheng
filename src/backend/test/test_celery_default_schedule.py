"""默认定时任务去重和错峰, 显式配置保持优先。"""

import subprocess
import sys
from pathlib import Path

from celery.schedules import crontab

from bisheng.core.config.settings import CeleryConf


def _check_daily_statistics_are_staggered_and_articles_have_one_schedule():
    entries = CeleryConf().beat_schedule
    assert entries["scan_document_projections"]["schedule"] == 300.0
    daily = [entry["schedule"] for entry in entries.values()
             if entry["task"].rsplit(".", 1)[-1] in {
                 "sync_mid_user_increment", "sync_mid_knowledge_increment", "sync_mid_app_increment",
                 "sync_mid_user_interact_dtl", "sync_mid_active_user", "sync_mid_doc_parse_dtl",
                 "sync_mid_knowledge_file_increment", "sync_mid_model_call_dtl", "sync_mid_sessions_increment",
                 "sync_mid_tool_call_dtl", "sync_mid_session_run_dtl",
             }]
    assert len(daily) == 11
    assert len({(tuple(value.hour), tuple(value.minute)) for value in daily}) == 11
    articles = [entry for entry in entries.values()
                if entry["task"] == "bisheng.worker.information.article.sync_information_article"]
    assert len(articles) == 1
    assert articles[0]["schedule"].minute == {0, 30}


def _check_explicit_schedule_is_preserved_without_adding_article_duplicate():
    custom = {
        "telemetry_mid_user_increment": {"task": "custom", "schedule": crontab(hour=4, minute=12)},
        "custom_article": {"task": "bisheng.worker.information.article.sync_information_article", "schedule": 900.0},
        "fanout_document_projection_scan": {"task": "custom_projection", "schedule": 900.0},
    }
    entries = CeleryConf(beat_schedule=custom).beat_schedule
    assert entries["telemetry_mid_user_increment"] == custom["telemetry_mid_user_increment"]
    assert entries["scan_document_projections"] == custom["fanout_document_projection_scan"]
    assert "fanout_document_projection_scan" not in entries
    assert [key for key, entry in entries.items()
            if entry["task"] == "bisheng.worker.information.article.sync_information_article"] == ["custom_article"]


def _check_projection_schedule_migrates_to_one_registered_entry():
    prefix = "bisheng.worker.knowledge.document_projection."
    old = {"task": prefix + "fanout_document_projection_scan", "schedule": 900.0, "options": {"expires": 240}}
    entries = CeleryConf(beat_schedule={"fanout_document_projection_scan": old}).beat_schedule
    assert "fanout_document_projection_scan" not in entries
    assert entries["scan_document_projections"] == {**old, "task": prefix + "scan_document_projections"}
    custom = {"task": prefix + "scan_document_projections", "schedule": 1800.0}
    entries = CeleryConf(beat_schedule={"custom_scan": custom}).beat_schedule
    assert "scan_document_projections" not in entries
    entries = CeleryConf(beat_schedule={"fanout_document_projection_scan": old, "scan_document_projections": custom}).beat_schedule
    assert entries["scan_document_projections"] == custom
    assert "fanout_document_projection_scan" not in entries


def test_real_celery_schedule_defaults_and_overrides():
    # 共享 conftest 会替换 Celery; 独立进程验证实际 crontab 和配置校验器。
    result = subprocess.run(
        [sys.executable, "-c", "import runpy; m=runpy.run_path('test/test_celery_default_schedule.py'); "
         "m['_check_daily_statistics_are_staggered_and_articles_have_one_schedule'](); "
         "m['_check_explicit_schedule_is_preserved_without_adding_article_duplicate'](); "
         "m['_check_projection_schedule_migrates_to_one_registered_entry']()"],
        cwd=Path(__file__).parents[1], capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
