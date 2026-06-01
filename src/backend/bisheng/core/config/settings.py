import ast
import json
import os
import re
from typing import Union

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
    timeout: int = Field(default=720, description="Node timeout (min）")


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
        if "file_scheduler_dispatch" not in self.beat_schedule:
            self.beat_schedule["file_scheduler_dispatch"] = {
                "task": "bisheng.worker.knowledge.scheduler.trigger_dispatch_task",
                "schedule": 30.0,
            }
        if "file_scheduler_reconcile" not in self.beat_schedule:
            self.beat_schedule["file_scheduler_reconcile"] = {
                "task": "bisheng.worker.knowledge.scheduler.reconcile_file_scheduler_task",
                "schedule": 300.0,
            }

        # convert str to crontab
        for key, task_info in self.beat_schedule.items():
            if isinstance(task_info["schedule"], str):
                self.beat_schedule[key]["schedule"] = crontab(task_info["schedule"])
        return self


class FairSchedulerConf(BaseModel):
    """Fair scheduler runtime configuration.

    Beat schedule intervals (dispatch every 30 s, reconcile every 300 s) are
    configured via ``celery_task.beat_schedule.file_scheduler_dispatch`` and
    ``celery_task.beat_schedule.file_scheduler_reconcile`` in config.yaml.
    The defaults are set in ``CeleryConf.validate``; operators can override
    them without touching this model.
    """

    dispatch_lock_ttl_seconds: int = Field(default=24, ge=1, le=300)
    max_per_user_inflight: int = Field(default=1, ge=1)
    user_overrides: dict[str, int] = Field(default_factory=dict)
    inflight_ttl_seconds: int = Field(default=7200, ge=60)

    @model_validator(mode="after")
    def validate(self):
        for user_id, limit in self.user_overrides.items():
            if limit < 1:
                raise ValueError(f"user_overrides[{user_id}] must be >= 1, got {limit}")
        return self

    def limit_for(self, user_id: str) -> int:
        return self.user_overrides.get(str(user_id), self.max_per_user_inflight)


class KnowledgeFileWorkerConf(BaseModel):
    """Knowledge file worker (parse pipeline) configuration."""

    ocr_queue_enabled: bool = Field(default=False)
    ocr_queue: str = Field(default="ocr_celery")
    fair_scheduler_enabled: bool = Field(default=False)
    fair_scheduler: FairSchedulerConf = Field(default_factory=FairSchedulerConf)


class KnowledgeQAFilterConf(BaseModel):
    """Knowledge space AI Q&A retrieval permission filter (F029).

    Controls the two-layer view_file permission filter shared by chat_folder
    (KnowledgeSpaceChatService), queryChunksFromDB (WorkStationService) and
    citation source resolve (CitationResolveService). See
    features/v2.6.0/029-knowledge-qa-permission-filter/spec.md §4 (AD-02/03/08).
    """

    index_filter_threshold: int = Field(
        default=5000,
        ge=1,
        description=(
            "AD-02 threshold. When the user's visible-or-excluded file count for the "
            "queried space is at or below this value, the index-layer filter switches "
            "to an IN / NOT-IN clause; otherwise it falls back to post-filter only."
        ),
    )
    retrieval_initial_multiplier: int = Field(
        default=3,
        ge=1,
        description=(
            "AD-03 first attempt. Initial recall fetches top_k * this multiplier so "
            "result-layer view_file post-filter can still leave at least top_k chunks."
        ),
    )
    retrieval_expansion_multiplier: int = Field(
        default=10,
        ge=1,
        description=(
            "AD-03 capped expansion. When the first attempt fails to fill top_k, a "
            "single retry recalls top_k * this multiplier; no further expansion."
        ),
    )
    fine_grained_concurrency: int = Field(
        default=8,
        ge=1,
        le=64,
        description=(
            "AD-08 concurrency. Semaphore limit when resolving view_file per file "
            "via FineGrainedPermissionService; mirrors KnowledgeSpaceService's "
            "_CHILD_PERMISSION_CHECK_CONCURRENCY default."
        ),
    )

    @model_validator(mode="after")
    def validate(self):
        if self.retrieval_expansion_multiplier < self.retrieval_initial_multiplier:
            raise ValueError(
                "retrieval_expansion_multiplier must be >= retrieval_initial_multiplier"
            )
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

    @property
    def enabled(self) -> bool:
        return bool(self.prefix and self.prefix.strip())


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


class InAppMessageForwardingConf(BaseModel):
    """Top-level forwarding config; one sub-block per external system."""

    cofco: CofcoForwardingConf = CofcoForwardingConf()
    # Future: shougang / longhua etc. as parallel fields


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
    knowledge_file_worker: KnowledgeFileWorkerConf = KnowledgeFileWorkerConf()
    knowledge_qa_filter: KnowledgeQAFilterConf = KnowledgeQAFilterConf()
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
            if key != "dev" and not value:
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
