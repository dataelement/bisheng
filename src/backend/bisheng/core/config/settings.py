import ast
import json
import os
import re
from typing import Any, Literal, Union

from celery.schedules import crontab
from cryptography.fernet import Fernet
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bisheng.core.config.llm import LLMConf
from bisheng.core.config.multi_tenant import MultiTenantConf
from bisheng.core.config.openfga import OpenFGAConf
from bisheng.core.config.reconcile import ReconcileConf
from bisheng.core.config.sso_sync import SSOSyncConf
from bisheng.core.config.user_tenant_sync import UserTenantSyncConf

secret_key = "TI31VYJ-ldAq-FXo5QNPKV_lqGTFfp-MIdbK2Hm5F1E="


def encrypt_token(token: str):
    return Fernet(secret_key).encrypt(token.encode())


def decrypt_token(token: str):
    return Fernet(secret_key).decrypt(token).decode()


class LoggerConf(BaseModel):
    """Looger Config"""

    level: str = "DEBUG"
    format: str = "<level>[{level.name} process-{process.id}-{thread.id} {name}:{line}]</level> - <level>trace={extra[trace_id]} {message}</level>"
    handlers: list[dict] = Field(default_factory=list, description="Log Processor")

    @classmethod
    def parse_logger_sink(cls, sink: str) -> str:
        match = re.search(r"\{(.+?)\}", sink)
        if not match:
            return sink
        env_keys = {}
        for one in match.groups():
            env_keys[one] = os.getenv(one, "")
        return sink.format(**env_keys)

    @field_validator("handlers")
    @classmethod
    def set_handlers(cls, value):
        if value is None:
            value = []
        for one in value:
            one["sink"] = cls.parse_logger_sink(one["sink"])
            if one.get("filter"):
                one["filter"] = eval(one["filter"])
        return value


class PasswordConf(BaseModel):
    """Password Config"""

    password_valid_period: int | None = Field(
        default=0, description="Password overXDays must be modified, Login prompt to change password again"
    )
    login_error_time_window: int | None = Field(default=0, description="Login error time window,minutes unit")
    max_error_times: int | None = Field(
        default=0, description="Maximum number of errors, after which the user will be banned"
    )


class SystemLoginMethod(BaseModel):
    """System Login Method Config"""

    bisheng_pro: bool = Field(default=False, description="Whether it is a commercial version")
    dashboard_pro: bool = Field(default=False, description="Whether dashboard is a commercial version")
    admin_username: str | None = Field(default=None, description="Admin username registered via web")
    allow_multi_login: bool = Field(default=True, description="Whether to allow multi-sign-on")


class MilvusConf(BaseModel):
    """milvus Configure"""

    connection_args: dict | None = Field(default=None, description="milvus Configure")
    is_partition: bool | None = Field(
        default=True, description="Is itpartitionMode", deprecated="Not in SupportpartitionMode"
    )
    partition_suffix: str | None = Field(
        default="1", description="partitionSuffix", deprecated="Not in SupportpartitionMode"
    )

    @field_validator("connection_args", mode="before")
    @classmethod
    def convert_connection_args(cls, value):
        if isinstance(value, str):
            return json.loads(value)
        return value


class ElasticsearchConf(BaseModel):
    """elasticsearch Configure"""

    elasticsearch_url: str | None = Field(default=None, alias="url", description="elasticsearchAccesses address")

    ssl_verify: str | dict | None = Field(default="{}", description="Additional Arguments")

    @model_validator(mode="after")
    def validate(self):
        if isinstance(self.ssl_verify, str):
            self.ssl_verify = ast.literal_eval(self.ssl_verify)

        return self


class VectorStores(BaseModel):
    """Vector Storage Configuration"""

    milvus: MilvusConf = Field(default_factory=MilvusConf, description="milvus Configure")
    elasticsearch: ElasticsearchConf = Field(default_factory=ElasticsearchConf, description="elasticsearch Configure")


class MinioConf(BaseModel):
    """minio Configure"""

    secure: bool | None = Field(default=False, description="Apakah ingin digunakan?https", alias="schema")
    cert_check: bool | None = Field(default=False, description="Whether to calibrate the certificate")
    endpoint: str | None = Field(default="127.0.0.1:9000", description="minio Service address")
    sharepoint: str | None = Field(default="127.0.0.1:9000", description="minio Public access address")
    share_schema: bool | None = Field(default=False, description="minio Whether the public access address is usedhttps")
    share_cert_check: bool | None = Field(
        default=False, description="minio Whether the public access address verifies the certificate"
    )
    access_key: str | None = Field(default="minioadmin", description="minio Username")
    secret_key: str | None = Field(default="minioadmin", description="minio Passwords")
    public_bucket: str | None = Field(
        default="bisheng",
        description="Store permanent files by defaultbucket. Files can be permanently accessed by anonymous users",
    )
    tmp_bucket: str | None = Field(
        default="tmp-dir", description="Ad hocbucket, stored files will have an expiration date"
    )


class ObjectStore(BaseModel):
    """Object Storage Configuration"""

    type: str = Field(default="minio", description="Object Storage Type")
    minio: MinioConf | None = Field(default_factory=MinioConf, description="minio Configure")


class WorkflowConf(BaseModel):
    """Workflow Configuration"""

    max_steps: int = Field(default=50, description="Maximum number of steps a node can run")
    timeout: int = Field(default=720, description="Node timeout (min)")


class CeleryConf(BaseModel):
    """Celery Configure"""

    task_routers: dict | None = Field(default_factory=dict, description="Task Routing Configuration")
    beat_schedule: dict | None = Field(default_factory=dict, description="Timed Task Configuration")

    @model_validator(mode="after")
    def validate(self):
        if not self.task_routers:
            self.task_routers = {
                "bisheng.worker.knowledge.*": {"queue": "knowledge_celery"},  # Knowledge Base Related Tasks
                "bisheng.worker.workflow.*": {"queue": "workflow_celery"},  # Workflow Execution Related Tasks
                "bisheng.worker.org_sync.*": {"queue": "knowledge_celery"},
                # Org Sync Tasks (low frequency, reuse knowledge queue)
                "bisheng.worker.tenant_reconcile.*": {"queue": "knowledge_celery"},
                # v2.5.1 F012 — 6h catch-up, reuse knowledge_celery
                "bisheng.worker.admin_scope.*": {"queue": "knowledge_celery"},  # v2.5.1 F019 — 10min sweep, low-volume
                "bisheng.worker.message.*": {"queue": "knowledge_celery"},  # WeChat message push tasks
                "bisheng.worker.portal_course.*": {"queue": "knowledge_celery"},
            }
        if "telemetry_mid_user_increment" not in self.beat_schedule:
            self.beat_schedule["telemetry_mid_user_increment"] = {
                "task": "bisheng.worker.telemetry.mid_table.sync_mid_user_increment",
                "schedule": crontab.from_string("30 0 * * *"),  # 00:30 exec every day
            }
        if "telemetry_mid_knowledge_increment" not in self.beat_schedule:
            self.beat_schedule["telemetry_mid_knowledge_increment"] = {
                "task": "bisheng.worker.telemetry.mid_table.sync_mid_knowledge_increment",
                "schedule": crontab.from_string("30 0 * * *"),  # 00:30 exec every day
            }
        if "telemetry_sync_mid_app_increment" not in self.beat_schedule:
            self.beat_schedule["telemetry_sync_mid_app_increment"] = {
                "task": "bisheng.worker.telemetry.mid_table.sync_mid_app_increment",
                "schedule": crontab.from_string("30 0 * * *"),  # 00:30 exec every day
            }
        if "telemetry_sync_mid_user_interact_dtl" not in self.beat_schedule:
            self.beat_schedule["telemetry_sync_mid_user_interact_dtl"] = {
                "task": "bisheng.worker.telemetry.mid_table.sync_mid_user_interact_dtl",
                "schedule": crontab.from_string("30 0 * * *"),  # 00:30 exec every day
            }
        if "telemetry_sync_mid_knowledge_space_content_stat" not in self.beat_schedule:
            self.beat_schedule["telemetry_sync_mid_knowledge_space_content_stat"] = {
                "task": "bisheng.worker.telemetry.mid_table.sync_mid_knowledge_space_content_stat",
                "schedule": crontab.from_string("30 0 * * *"),  # 00:30 exec every day
            }
        if "telemetry_sync_mid_active_user" not in self.beat_schedule:
            self.beat_schedule["telemetry_sync_mid_active_user"] = {
                "task": "bisheng.worker.telemetry.derived_mid_table.sync_mid_active_user",
                "schedule": crontab.from_string("30 0 * * *"),  # 00:30 exec every day
            }
        if "telemetry_sync_mid_doc_parse_dtl" not in self.beat_schedule:
            self.beat_schedule["telemetry_sync_mid_doc_parse_dtl"] = {
                "task": "bisheng.worker.telemetry.derived_mid_table.sync_mid_doc_parse_dtl",
                "schedule": crontab.from_string("30 0 * * *"),  # 00:30 exec every day
            }
        if "telemetry_sync_mid_knowledge_file_increment" not in self.beat_schedule:
            self.beat_schedule["telemetry_sync_mid_knowledge_file_increment"] = {
                "task": "bisheng.worker.telemetry.derived_mid_table.sync_mid_knowledge_file_increment",
                "schedule": crontab.from_string("30 0 * * *"),  # 00:30 exec every day
            }
        if "telemetry_sync_mid_model_call_dtl" not in self.beat_schedule:
            self.beat_schedule["telemetry_sync_mid_model_call_dtl"] = {
                "task": "bisheng.worker.telemetry.derived_mid_table.sync_mid_model_call_dtl",
                "schedule": crontab.from_string("30 0 * * *"),  # 00:30 exec every day
            }
        if "telemetry_sync_mid_sessions_increment" not in self.beat_schedule:
            self.beat_schedule["telemetry_sync_mid_sessions_increment"] = {
                "task": "bisheng.worker.telemetry.derived_mid_table.sync_mid_sessions_increment",
                "schedule": crontab.from_string("30 0 * * *"),  # 00:30 exec every day
            }
        if "telemetry_sync_mid_tool_call_dtl" not in self.beat_schedule:
            self.beat_schedule["telemetry_sync_mid_tool_call_dtl"] = {
                "task": "bisheng.worker.telemetry.derived_mid_table.sync_mid_tool_call_dtl",
                "schedule": crontab.from_string("30 0 * * *"),  # 00:30 exec every day
            }
        if "telemetry_sync_mid_session_run_dtl" not in self.beat_schedule:
            self.beat_schedule["telemetry_sync_mid_session_run_dtl"] = {
                "task": "bisheng.worker.telemetry.derived_mid_table.sync_mid_session_run_dtl",
                "schedule": crontab.from_string("30 0 * * *"),  # 00:30 exec every day
            }
        if "sync_information_article" not in self.beat_schedule:
            self.beat_schedule["sync_information_article"] = {
                "task": "bisheng.worker.information.article.sync_information_article",
                "schedule": crontab.from_string("30 5 * * *"),  # 05:30 exec every day
            }
        if "retry_failed_tuples" not in self.beat_schedule:
            self.beat_schedule["retry_failed_tuples"] = {
                "task": "bisheng.worker.permission.retry_failed_tuples.retry_failed_tuples",
                "schedule": 30.0,  # Every 30 seconds
            }
        if "dispatch_approval_notifications" not in self.beat_schedule:
            self.beat_schedule["dispatch_approval_notifications"] = {
                "task": "bisheng.worker.approval.notification_tasks.dispatch_approval_notifications",
                "schedule": 30.0,
            }
        if "check_org_sync_schedules" not in self.beat_schedule:
            self.beat_schedule["check_org_sync_schedules"] = {
                "task": "bisheng.worker.org_sync.tasks.check_org_sync_schedules",
                "schedule": 60.0,  # Every 60 seconds
            }
        # v2.5.1 F012: 6h user-leaf-tenant catch-up reconcile.
        if "reconcile_user_tenant_assignments" not in self.beat_schedule:
            self.beat_schedule["reconcile_user_tenant_assignments"] = {
                "task": "bisheng.worker.tenant_reconcile.tasks.reconcile_user_tenant_assignments",
                "schedule": crontab.from_string("0 */6 * * *"),  # every 6 hours
            }
        # v2.5.1 F019: 10min admin_scope Redis key sweep (AC-13).
        if "admin_scope_cleanup" not in self.beat_schedule:
            self.beat_schedule["admin_scope_cleanup"] = {
                "task": "bisheng.worker.admin_scope.tasks.admin_scope_cleanup",
                "schedule": crontab.from_string("*/10 * * * *"),  # every 10 minutes
            }
        # v2.5.1 F015: 6h forced reconcile of every OrgSyncConfig +
        # weekly/daily ts_conflict reporting. Cron strings are sourced
        # from ``settings.reconcile`` so operators can override via env
        # without touching the code path.
        if "reconcile_all_organizations" not in self.beat_schedule:
            self.beat_schedule["reconcile_all_organizations"] = {
                "task": "bisheng.worker.org_sync.reconcile_tasks.reconcile_all_organizations",
                "schedule": crontab.from_string("0 */6 * * *"),  # every 6h
            }
        if "report_ts_conflicts_weekly" not in self.beat_schedule:
            self.beat_schedule["report_ts_conflicts_weekly"] = {
                "task": "bisheng.worker.org_sync.reconcile_tasks.report_ts_conflicts_weekly",
                "schedule": crontab.from_string("0 9 * * MON"),  # Mon 09:00
            }
        if "report_ts_conflicts_daily_escalation" not in self.beat_schedule:
            self.beat_schedule["report_ts_conflicts_daily_escalation"] = {
                "task": "bisheng.worker.org_sync.reconcile_tasks.report_ts_conflicts_daily_escalation",
                "schedule": crontab.from_string("0 9 * * *"),  # every 09:00
            }

        if "sync_information_article_hourly" not in self.beat_schedule:
            self.beat_schedule["sync_information_article_hourly"] = {
                "task": "bisheng.worker.information.article.sync_information_article",
                "schedule": crontab.from_string("*/30 * * * *"),  # exec Every half hour
            }

        # v2.6.0 F057: scan wechat message push outbox every 30 seconds.
        if "scan_wechat_message_push_outbox" not in self.beat_schedule:
            self.beat_schedule["scan_wechat_message_push_outbox"] = {
                "task": "bisheng.worker.message.tasks.scan_wechat_message_push_outbox",
                "schedule": 30.0,  # Every 30 seconds
            }

        if "scan_portal_course_media_cleanup" not in self.beat_schedule:
            self.beat_schedule["scan_portal_course_media_cleanup"] = {
                "task": "bisheng.worker.portal_course.tasks.scan_portal_course_media_cleanup",
                "schedule": 60.0,
            }

        # F056: root Beat entries only fan out; every tenant child task carries
        # an explicit tenant header and runs on the existing knowledge queue.
        if "portal_recommendation_pools_6h" not in self.beat_schedule:
            self.beat_schedule["portal_recommendation_pools_6h"] = {
                "task": "bisheng.worker.knowledge.portal_recommendation.fanout_portal_recommendation_maintenance",
                "schedule": crontab.from_string("15 */6 * * *"),
                "args": ("pools",),
            }
        if "portal_recommendation_incremental_daily" not in self.beat_schedule:
            self.beat_schedule["portal_recommendation_incremental_daily"] = {
                "task": "bisheng.worker.knowledge.portal_recommendation.fanout_portal_recommendation_maintenance",
                "schedule": crontab.from_string("20 2 * * *"),
                "args": ("incremental",),
            }
        if "portal_recommendation_search_purge_daily" not in self.beat_schedule:
            self.beat_schedule["portal_recommendation_search_purge_daily"] = {
                "task": "bisheng.worker.knowledge.portal_recommendation.fanout_portal_recommendation_maintenance",
                "schedule": crontab.from_string("50 2 * * *"),
                "args": ("purge",),
            }
        if "portal_recommendation_full_weekly" not in self.beat_schedule:
            self.beat_schedule["portal_recommendation_full_weekly"] = {
                "task": "bisheng.worker.knowledge.portal_recommendation.fanout_portal_recommendation_maintenance",
                "schedule": crontab.from_string("30 3 * * SUN"),
                "args": ("full",),
            }

        # F048: portal home hot-search daily rebuild. Root Beat only fans out;
        # each tenant child task carries an explicit tenant header (02:00,
        # staggered ahead of the portal recommendation jobs at 02:20/02:50).
        if "portal_hot_search_rebuild_daily" not in self.beat_schedule:
            self.beat_schedule["portal_hot_search_rebuild_daily"] = {
                "task": "bisheng.worker.knowledge.portal_hot_search.fanout_portal_hot_search_rebuild",
                "schedule": crontab.from_string("0 2 * * *"),
            }

        # convert str to crontab
        for key, task_info in self.beat_schedule.items():
            if isinstance(task_info["schedule"], str):
                self.beat_schedule[key]["schedule"] = crontab(task_info["schedule"])
        return self


class LinsightConf(BaseModel):
    """Inspiration Configuration"""

    debug: bool = Field(default=False, description="Whether to opendebugMode")
    tool_buffer: int = Field(
        default=100000, description="Maximum Tool Execution Historytoken, you need to summarize your history after"
    )
    max_steps: int = Field(default=200, description="Maximum number of steps per task to prevent infinite loops")
    retry_num: int = Field(
        default=3, description="Number of times the model call was retried during the execution of the Ideas task"
    )
    retry_sleep: int = Field(
        default=5, description="Interval between retries of model calls during execution of Invisible Tasks (seconds)"
    )
    max_file_num: int = Field(
        default=5, description="BuatSOPJampromptThe number of user-uploaded file information placed in the"
    )
    max_knowledge_num: int = Field(
        default=20, description="BuatSOPJampromptThe amount of knowledge base information placed in the"
    )
    waiting_list_url: str = Field(default=None, description="waiting list Jump link")
    default_temperature: float = Field(default=0, description="Default Temperature at Model Request")
    retry_temperature: float = Field(
        default=1, description="reactModejsonModel temperature when retrying after parsing failure"
    )
    file_content_length: int = Field(
        default=5000,
        description="The number of characters to read the contents of the file when splitting subtasks, which will be truncated when exceeded",
    )
    max_file_content_num: int = Field(
        default=3, description="Number of files to read when subtasking, in reverse order by modification time"
    )


class DailyChatConf(BaseModel):
    """Daily-chat (日常模式) Agent runtime configuration.

    Stored in DB config (written by POST /api/v1/config/save) under key `daily_chat`.
    Read at request time via ConfigService.aget_daily_chat_conf().
    """

    agent_max_iterations: int = Field(
        default=50,
        description="Max LangGraph recursion_limit for the daily-chat ReAct agent loop. "
        "Falls back to 50 on missing / non-int / <= 0 value.",
    )
    history_max_tokens: int = Field(
        default=8000,
        description="Upper bound (in tokens) on the combined length of chat history "
        "injected into the LLM prompt. When the stored history exceeds "
        "this budget, oldest turns are dropped one at a time until the "
        "remainder fits. Falls back to 8000 on missing / non-int / <= 0.",
    )

    @field_validator("agent_max_iterations", mode="before")
    @classmethod
    def _coerce_agent_max_iterations(cls, v):
        try:
            n = int(v)
        except (TypeError, ValueError):
            return 50
        return n if n > 0 else 50

    @field_validator("history_max_tokens", mode="before")
    @classmethod
    def _coerce_history_max_tokens(cls, v):
        try:
            n = int(v)
        except (TypeError, ValueError):
            return 8000
        return n if n > 0 else 8000


DEFAULT_SHOUGANG_FILE_DOCUMENT_TYPES = [
    {"code": "POL", "label": "政策制度"},
    {"code": "STD", "label": "标准规范"},
    {"code": "PRO", "label": "流程与程序"},
    {"code": "SPC", "label": "技术规程与诀窍"},
    {"code": "RPT", "label": "报告"},
    {"code": "CAS", "label": "案例"},
    {"code": "DGN", "label": "设计资产"},
    {"code": "PAT", "label": "专利与知识产权"},
    {"code": "TRN", "label": "培训资源"},
]


def _default_shougang_file_document_types():
    return [dict(item) for item in DEFAULT_SHOUGANG_FILE_DOCUMENT_TYPES]


class ShougangFileEncodingConf(BaseModel):
    classify_prompt: Any | None = Field(default=None)
    user_content_template: Any | None = Field(default=None)
    valid_pattern: Any | None = Field(default=None)
    fallback_code: Any | None = Field(default=None)
    seq_cap: Any | None = Field(default=None)
    document_types: Any | None = Field(default_factory=_default_shougang_file_document_types)


class ShougangConf(BaseModel):
    """Shougang (首钢) deployment-specific configuration.

    Stored in DB config under key `shougang`. When the block exists and
    `prefix` is set, the file-encoding feature is considered enabled.
    """

    prefix: str | None = Field(
        default=None,
        description='File-encoding prefix, e.g. "GF". Empty/None disables the feature.',
    )
    # The two below are reserved for other shougang sub-features and are not
    # consumed by the file-encoding pipeline. Kept here so the model accepts them.
    deployment_label: str | None = Field(default=None)
    portal_admin_url: str | None = Field(default=None)
    portal_base_url: str | None = Field(default=None)
    file_encoding: ShougangFileEncodingConf = Field(default_factory=ShougangFileEncodingConf)

    @property
    def enabled(self) -> bool:
        return bool(self.prefix and self.prefix.strip())

    @field_validator("file_encoding", mode="before")
    @classmethod
    def _coerce_file_encoding(cls, v):
        if v is None:
            return {}
        if isinstance(v, (dict, ShougangFileEncodingConf)):
            return v
        return {}


class CookieConf(BaseModel):
    """Cookie Configure"""

    max_age: int | None = Field(default=None, description="Cookie Maximum survival time in seconds")
    path: str = Field(default="/", description="Cookie Path Properties for")
    domain: str | None = Field(default=None, description="Cookie Domain Properties for")
    secure: bool = Field(default=False, description="enabled secure Property")
    httponly: bool = Field(default=True, description="enabled HttpOnly Property")
    samesite: str = Field(default=None, description="SameSite property, optional value is 'lax', 'strict', 'none'")

    jwt_token_expire_time: int = Field(default=86400, description="JwtTokenExpiration time in seconds")
    jwt_iss: str = Field(default="bisheng", description="JwtTokenIssuer of")


class Etl4lmConf(BaseModel):
    """Etl4lm Configure"""

    url: str = Field(default="", description="etl4lmService Address")
    timeout: int = Field(default=600, description="etl4lmService Request Timeout (sec)")
    ocr_sdk_url: str = Field(default="", description="etl4lm ocr sdkService Address")
    image_extraction_strategy: Literal["legacy", "render_only", "original_first"] = Field(
        default="original_first",
        description="PDF image extraction strategy",
    )
    image_fallback_dpi: int = Field(
        default=200,
        ge=72,
        le=300,
        description="DPI used to render a PDF image region when embedded extraction is unavailable",
    )
    image_max_pixels: int = Field(
        default=16_000_000,
        ge=1_000_000,
        le=100_000_000,
        description="Maximum pixels allowed for one extracted PDF image",
    )


class MineruConf(BaseModel):
    url: str = Field(default="", description="MineruService Address")
    timeout: int = Field(default=60, description="MineruService Request Timeout (sec)")
    headers: dict = Field(default_factory=dict, description="MineruService Request Headers")
    request_kwargs: dict = Field(default_factory=dict, description="MineruService Request Arguments")


class PaddleOcrConf(BaseModel):
    """PaddleOcr Configure"""

    url: str = Field(default="", description="PaddleOcrService Address")
    timeout: int = Field(default=60, description="PaddleOcrService Request Timeout (sec)")
    auth_token: str = Field(default="", description="PaddleOcrService Authentication Token")
    headers: dict = Field(default_factory=dict, description="PaddleOcrService Headers")
    request_kwargs: dict = Field(default_factory=dict, description="PaddleOcrService Request Arguments")


class VersionManagementConf(BaseModel):
    """Version Management Configure"""

    enabled: bool = Field(default=False, description="Enable knowledge-space file version management")
    simhash_similarity_threshold: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Similarity threshold (1 - hamming/64) to flag a file as 'similar'. Range [0, 1].",
    )
    enable_tfidf_refine: bool = Field(
        default=True,
        description="Re-score simhash-matched candidates with a TF-IDF cosine over actual chunk "
        "text, to drop false positives (simhash ~100% on template-only matches). "
        "Falls back to pure simhash when ES text is unavailable.",
    )
    tfidf_similarity_threshold: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="TF-IDF cosine threshold for the refine pass: candidates below this are "
        "dropped even if their simhash cleared simhash_similarity_threshold. Range [0, 1].",
    )


class KnowledgePdfArtifactConf(BaseModel):
    """统一 PDF 派生产物配置。"""

    enabled: bool = Field(default=True, description="Enable unified PDF artifact scheduling")
    queue_name: str = Field(default="knowledge_pdf_celery", min_length=1, description="Dedicated Celery queue")
    max_retries: int = Field(default=3, ge=0, le=10, description="Retries after the initial attempt")
    retry_base_seconds: int = Field(default=30, ge=1, description="Initial retry countdown")
    retry_max_seconds: int = Field(default=300, ge=1, description="Maximum retry countdown")
    conversion_timeout_seconds: int = Field(default=300, ge=10, description="Per conversion timeout")

    @model_validator(mode="after")
    def validate_retry_window(self):
        if self.retry_max_seconds < self.retry_base_seconds:
            raise ValueError("retry_max_seconds must be greater than or equal to retry_base_seconds")
        return self


class KnowledgePdfWatermarkConf(BaseModel):
    """门户 PDF 实时水印运行配置。"""

    timeout_seconds: int = Field(default=60, ge=1, le=300, description="Watermark generation deadline")
    max_concurrency: int = Field(default=2, ge=1, le=16, description="Per-process generation concurrency")
    user_lock_ttl_seconds: int = Field(default=90, ge=2, le=600, description="Per-user Redis lock TTL")
    process_terminate_grace_seconds: float = Field(
        default=2,
        gt=0,
        le=10,
        description="Worker terminate grace period before kill",
    )

    @model_validator(mode="after")
    def validate_user_lock_ttl(self):
        if self.user_lock_ttl_seconds <= self.timeout_seconds:
            raise ValueError("user_lock_ttl_seconds must be greater than timeout_seconds")
        return self


class KnowledgeConf(BaseModel):
    """Knowledge Configure"""

    loader_provider: str = Field(default="etl4lm", description="Knowledge Config Provide Settings")
    etl4lm: Etl4lmConf = Field(default_factory=Etl4lmConf, description="Etl4lm Configure")
    mineru: MineruConf = Field(default_factory=MineruConf, description="Mineru Configure")
    paddle_ocr: PaddleOcrConf = Field(default_factory=PaddleOcrConf, description="PaddleOcr Config")
    version_management: VersionManagementConf = Field(
        default_factory=VersionManagementConf,
        description="Version Management Configure",
    )
    pdf_artifact: KnowledgePdfArtifactConf = Field(
        default_factory=KnowledgePdfArtifactConf,
        description="Unified PDF Artifact Configure",
    )
    pdf_watermark: KnowledgePdfWatermarkConf = Field(
        default_factory=KnowledgePdfWatermarkConf,
        description="Portal PDF Watermark Configure",
    )

    @property
    def image_parser_enabled(self) -> bool:
        """Whether the active loader_provider can parse images (and richer PDFs).

        Mirrors the loader-selection logic in `knowledge/rag/base_file_pipeline.py`:
        an external OCR/ETL service is used only when `loader_provider` matches a
        provider whose `url` is configured. Otherwise the pipeline falls back to
        the local PDF loader, which does not support images.
        """
        provider = (self.loader_provider or "").strip()
        if provider == "etl4lm":
            return bool(self.etl4lm.url)
        if provider == "mineru":
            return bool(self.mineru.url)
        if provider == "paddle_ocr":
            return bool(self.paddle_ocr.url)
        return False


class IntelligenceCenterConf(BaseModel):
    """Intelligence Center Configure"""

    base_url: str = Field(default="", description="Intelligence Center Service Address")
    api_key: str = Field(default="", description="Intelligence Center Service API Key")
    kwargs: dict = Field(default_factory=dict, description="Additional Arguments")


class McpConf(BaseModel):
    """MCP Configure"""

    enable_stdio: bool = Field(default=True, description="Whether to enable stdio")


class CofcoForwardingConf(BaseModel):
    """E+ in-app message forwarding config for 中粮 (cofco) deployment."""

    enabled: bool = Field(default=False)
    api_base: str = Field(default="", description="E.g. http://10.28.64.30:8070/qwmsg-ui")
    app_id: str = Field(default="")
    secret: str = Field(default="")
    agentid: int | None = Field(default=None)
    timeout_seconds: float = Field(default=5.0)
    bisheng_inbox_url: str = Field(default="", description="BiSheng client base URL for textcard callback")
    enable_duplicate_check: int = Field(default=0)
    duplicate_check_interval: int = Field(default=1800)
    user_sources: list[str] = Field(
        default_factory=lambda: ["cofco_eplus", "wecom"],
        description="Accepted User.source values whose external_id is the E+ employee ID",
    )


class ShougangWeChatMessagePushTemplateConf(BaseModel):
    """Message templates for Shougang enterprise WeChat push."""

    qa_expert_invited: str = Field(
        default="{applicant} 邀请你回答问题「{resource}」\n{preview}",
        description="Template for qa_expert_invited notifications",
    )
    qa_expert_answered: str = Field(
        default="{applicant} 回答了问题「{resource}」\n{preview}",
        description="Template for qa_expert_answered notifications",
    )
    qa_answer_commented: str = Field(
        default="{applicant} 评论了回答「{resource}」\n{preview}",
        description="Template for qa_answer_commented notifications",
    )
    qa_answer_accepted: str = Field(
        default="你的回答「{resource}」被 {applicant} 采纳\n{preview}",
        description="Template for qa_answer_accepted notifications",
    )


class ShougangWeChatMessagePushConf(BaseModel):
    """Shougang enterprise WeChat message push configuration."""

    enabled: bool = Field(default=False, description="Master switch for WeChat message push")
    api_url: str = Field(
        default="https://mobms.sggf.com.cn:30201/madp-app/madp/qywxPush-api/pushMessage",
        description="Shougang MADC qywxPush API endpoint",
    )
    id: str = Field(default="", description="Enterprise ID")
    agentid: str = Field(default="1000053", description="Enterprise WeChat app ID")
    key: str = Field(default="", description="Enterprise WeChat app secret")
    sys_id: str = Field(default="1", description="Business system ID")
    msg_type: str = Field(default="text", description="Message type")
    timeout_seconds: float = Field(default=10.0, description="HTTP timeout in seconds")
    max_retries: int = Field(default=3, description="Maximum retry attempts")
    batch_size: int = Field(default=100, description="Max outbox records per scan")
    scan_interval_seconds: float = Field(default=30.0, description="Beat scan interval in seconds")
    retry_base_seconds: int = Field(default=60, description="Base retry backoff in seconds")
    retry_max_seconds: int = Field(default=3600, description="Max retry backoff in seconds")
    templates: ShougangWeChatMessagePushTemplateConf = Field(
        default_factory=ShougangWeChatMessagePushTemplateConf,
        description="Message templates by action_code",
    )


class InAppMessageForwardingConf(BaseModel):
    """Top-level forwarding config; one sub-block per external system."""

    cofco: CofcoForwardingConf = CofcoForwardingConf()
    shougang_wechat: ShougangWeChatMessagePushConf = ShougangWeChatMessagePushConf()


DATABASE_POOL_FIELDS = (
    "pool_size",
    "max_overflow",
    "pool_timeout",
    "pool_recycle",
    "pool_pre_ping",
)
SYNC_DATABASE_POOL_DEFAULTS: dict[str, Any] = {
    "pool_size": 20,
    "max_overflow": 10,
    "pool_timeout": 30,
    "pool_recycle": 3600,
    "pool_pre_ping": True,
}
ASYNC_DATABASE_POOL_DEFAULTS: dict[str, Any] = {
    "pool_size": 40,
    "max_overflow": 20,
    "pool_timeout": 30,
    "pool_recycle": 3600,
    "pool_pre_ping": True,
}


class DatabaseEnginePoolConf(BaseModel):
    """Resolved SQLAlchemy connection-pool settings for one engine type."""

    pool_size: int
    max_overflow: int
    pool_timeout: int
    pool_recycle: int
    pool_pre_ping: bool

    def as_engine_kwargs(self) -> dict[str, Any]:
        """Return keyword arguments accepted by a SQLAlchemy engine factory."""
        return self.model_dump()


class DatabasePoolConf(BaseModel):
    """Resolve legacy common overrides and engine-specific pool settings."""

    model_config = ConfigDict(populate_by_name=True)

    pool_size: int | None = Field(default=None, description="Legacy common persistent connections")
    max_overflow: int | None = Field(default=None, description="Legacy common overflow connections")
    pool_timeout: int | None = Field(default=None, description="Legacy common pool wait timeout")
    pool_recycle: int | None = Field(default=None, description="Legacy common connection recycle time")
    pool_pre_ping: bool | None = Field(default=None, description="Legacy common connection health check")
    sync: DatabaseEnginePoolConf
    async_: DatabaseEnginePoolConf = Field(alias="async")

    @model_validator(mode="before")
    @classmethod
    def resolve_engine_pool_settings(cls, values: Any) -> Any:
        """Apply defaults, legacy common fields, then engine-specific fields."""
        if values is None:
            values = {}
        if not isinstance(values, dict):
            return values

        resolved_values = dict(values)
        legacy_overrides = {field: resolved_values[field] for field in DATABASE_POOL_FIELDS if field in resolved_values}

        def resolve(
            defaults: dict[str, Any],
            engine_values: Any,
        ) -> Any:
            if engine_values is None:
                engine_values = {}
            if isinstance(engine_values, BaseModel):
                engine_values = engine_values.model_dump()
            if not isinstance(engine_values, dict):
                return engine_values
            return {**defaults, **legacy_overrides, **engine_values}

        resolved_values["sync"] = resolve(
            SYNC_DATABASE_POOL_DEFAULTS,
            resolved_values.get("sync"),
        )
        resolved_values["async"] = resolve(
            ASYNC_DATABASE_POOL_DEFAULTS,
            resolved_values.get("async", resolved_values.get("async_")),
        )
        return resolved_values

    def as_sync_engine_kwargs(self) -> dict[str, Any]:
        """Return resolved keyword arguments for the synchronous engine."""
        return self.sync.as_engine_kwargs()

    def as_async_engine_kwargs(self) -> dict[str, Any]:
        """Return resolved keyword arguments for the asynchronous engine."""
        return self.async_.as_engine_kwargs()

    def as_engine_kwargs(self) -> dict[str, Any]:
        """Return sync kwargs for callers using the legacy helper method."""
        return self.as_sync_engine_kwargs()


class PortalHotSearchConf(BaseModel):
    """F048: portal home hot-search daily batch configuration.

    All caps are hard limits that bound memory/time on large tenants; on
    reaching any cap the batch truncates and records ``degraded`` rather than
    loading all raw events into memory.
    """

    enabled: bool = Field(default=True, description="Master switch for hot-search rebuild")
    window_days: int = Field(default=30, description="Statistics window in days")
    min_unique_users: int = Field(default=5, description="Min distinct users to qualify")
    min_search_count: int = Field(default=8, description="Min deduped manual searches to qualify")
    top_k: int = Field(default=5, description="Number of hot searches published")
    candidate_top_n: int = Field(default=200, description="Pass1 candidate cap / LLM grouping input cap")
    page_size: int = Field(default=1000, description="ES aggregation/scan page size")
    max_pages: int = Field(default=500, description="ES pagination page cap before truncation")
    per_query_scan_cap: int = Field(default=50000, description="Pass2 per-candidate record scan cap")
    diagnostic_candidate_top_n: int = Field(default=50, description="Candidate rows persisted per batch")
    diagnostic_keep_batches: int = Field(default=30, description="Diagnostic batches retained per tenant")
    lock_ttl: int = Field(default=1800, description="Redis rebuild lock TTL in seconds")
    redis_ttl: int = Field(default=691200, description="Redis snapshot cache TTL in seconds (8 days)")
    llm_sample_max_chars: int = Field(default=2000, description="Max chars of LLM I/O persisted for diagnostics")


class Settings(BaseModel):
    """Application Settings"""

    model_config = ConfigDict(validate_assignment=True, arbitrary_types_allowed=True, extra="ignore")

    chains: dict = {}
    agents: dict = {}
    prompts: dict = {}
    llms: dict = {}
    tools: dict = {}
    memories: dict = {}
    embeddings: dict = {}
    knowledges: dict = {}
    vectorstores: dict = {}
    documentloaders: dict = {}
    wrappers: dict = {}
    retrievers: dict = {}
    toolkits: dict = {}
    textsplitters: dict = {}
    utilities: dict = {}
    input_output: dict = {}
    output_parsers: dict = {}
    autogen_roles: dict = {}
    dev: bool = False
    environment: Union[dict, str] = "dev"
    # ↑↑↑ before config for langchain flow, will be deprecated
    debug: bool = False
    database_url: str | None = None
    redis_url: Union[str, dict] | None = None
    celery_redis_url: Union[str, dict] | None = None
    redis: dict | None = None
    admin: dict = {}
    cache: str = "InMemoryCache"
    remove_api_keys: bool = False
    bisheng_rt: dict = {}
    default_llm: dict = {}
    jwt_secret: str = "secret_cF2kD4lW9wY4zL7eX1zX9vS1fA7eW4lQ"
    gpts: dict = {}
    openai_conf: dict = {}
    minio_conf: dict = {}
    linsight_conf: LinsightConf = LinsightConf()
    logger_conf: LoggerConf = LoggerConf()
    password_conf: PasswordConf = PasswordConf()
    system_login_method: SystemLoginMethod = SystemLoginMethod()
    vector_stores: VectorStores = VectorStores()
    object_storage: ObjectStore = ObjectStore()
    workflow_conf: WorkflowConf = WorkflowConf()
    celery_task: CeleryConf = CeleryConf()
    cookie_conf: CookieConf = CookieConf()
    telemetry_elasticsearch: ElasticsearchConf = ElasticsearchConf()

    license_str: str | None = None  # license Contents

    information_conf: IntelligenceCenterConf = IntelligenceCenterConf()
    mcp: McpConf = McpConf()
    multi_tenant: MultiTenantConf = MultiTenantConf()
    openfga: OpenFGAConf = OpenFGAConf()
    user_tenant_sync: UserTenantSyncConf = UserTenantSyncConf()
    sso_sync: SSOSyncConf = SSOSyncConf()
    reconcile: ReconcileConf = ReconcileConf()
    llm: LLMConf = LLMConf()
    in_app_message_forwarding: InAppMessageForwardingConf = InAppMessageForwardingConf()
    database_pool: DatabasePoolConf = Field(default_factory=DatabasePoolConf)
    portal_hot_search: PortalHotSearchConf = Field(default_factory=PortalHotSearchConf)

    @field_validator("database_url")
    @classmethod
    def set_database_url(cls, value):
        if not value:
            logger.debug("No database_url provided, trying bisheng_DATABASE_URL env variable")
            if bisheng_database_url := os.getenv("bisheng_DATABASE_URL"):
                value = bisheng_database_url
            else:
                logger.debug("No DATABASE_URL env variable, using sqlite database")
                value = "sqlite:///./bisheng.db"
        else:
            # Encrypt password
            import re

            pattern = r"(?<=:)[^:]+(?=@)"  # Match colon after to@Any character before the symbol
            match = re.search(pattern, value)
            if match:
                password = match.group(0)
                new_password = decrypt_token(password)
                new_mysql_url = re.sub(pattern, f"{new_password}", value)
                value = new_mysql_url

        return value

    @model_validator(mode="before")
    @classmethod
    def set_redis_url(cls, values):
        if "redis_url" in values:
            if isinstance(values["redis_url"], dict):
                for k, v in values["redis_url"].items():
                    if isinstance(v, str) and v.startswith("encrypt(") and v.endswith(")"):
                        v = v[8:-1]
                        values["redis_url"][k] = decrypt_token(v)
            else:
                import re

                pattern = r"(?<=:)[^:]+(?=@)"  # Match colon after to@Any character before the symbol
                match = re.search(pattern, values["redis_url"])
                if match:
                    password = match.group(0)
                    new_password = decrypt_token(password)
                    new_redis_url = re.sub(pattern, f"{new_password}", values["redis_url"])
                    values["redis_url"] = new_redis_url
        return values

    @model_validator(mode="before")
    @classmethod
    def set_celery_redis_url(cls, values):
        if "celery_redis_url" in values:
            if isinstance(values["celery_redis_url"], dict):
                for k, v in values["celery_redis_url"].items():
                    if isinstance(v, str) and v.startswith("encrypt(") and v.endswith(")"):
                        v = v[8:-1]
                        values["celery_redis_url"][k] = decrypt_token(v)
            else:
                import re

                pattern = r"(?<=:)[^:]+(?=@)"  # Match colon after to@Any character before the symbol
                match = re.search(pattern, values["celery_redis_url"])
                if match:
                    password = match.group(0)
                    new_password = decrypt_token(password)
                    new_redis_url = re.sub(pattern, f"{new_password}", values["celery_redis_url"])
                    values["celery_redis_url"] = new_redis_url
        return values

    @model_validator(mode="before")
    @classmethod
    def validate_lists(cls, values):
        for key, value in values.items():
            if key not in {"dev", "database_pool"} and not value:
                values[key] = []
        return values

    def get_minio_conf(self) -> MinioConf:
        return self.object_storage.minio

    def get_vectors_conf(self) -> VectorStores:
        return self.vector_stores

    def get_search_conf(self) -> ElasticsearchConf:
        return self.vector_stores.elasticsearch

    def get_telemetry_conf(self) -> ElasticsearchConf:
        if not self.telemetry_elasticsearch.elasticsearch_url:
            return self.vector_stores.elasticsearch
        return self.telemetry_elasticsearch
