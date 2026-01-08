import ast
import json
import os
import re
from typing import Dict, List, Optional, Union

from celery.schedules import crontab
from cryptography.fernet import Fernet
from loguru import logger
from pydantic import ConfigDict, BaseModel, Field, field_validator, model_validator

secret_key = 'TI31VYJ-ldAq-FXo5QNPKV_lqGTFfp-MIdbK2Hm5F1E='


def encrypt_token(token: str):
    return Fernet(secret_key).encrypt(token.encode())


def decrypt_token(token: str):
    return Fernet(secret_key).decrypt(token).decode()


class LoggerConf(BaseModel):
    """Looger Config"""
    level: str = 'DEBUG'
    format: str = '<level>[{level.name} process-{process.id}-{thread.id} {name}:{line}]</level> - <level>trace={extra[trace_id]} {message}</level>'  # noqa
    handlers: List[Dict] = Field(default_factory=list, description='Log Processor')

    @classmethod
    def parse_logger_sink(cls, sink: str) -> str:
        match = re.search(r'\{(.+?)\}', sink)
        if not match:
            return sink
        env_keys = {}
        for one in match.groups():
            env_keys[one] = os.getenv(one, '')
        return sink.format(**env_keys)

    @field_validator('handlers')
    @classmethod
    def set_handlers(cls, value):
        if value is None:
            value = []
        for one in value:
            one['sink'] = cls.parse_logger_sink(one['sink'])
            if one.get('filter'):
                one['filter'] = eval(one['filter'])
        return value


class PasswordConf(BaseModel):
    """ Password Config """
    password_valid_period: Optional[int] = Field(default=0, description='Password overXDays must be modified, Login prompt to change password again')
    login_error_time_window: Optional[int] = Field(default=0, description='Login error time window,minutes unit')
    max_error_times: Optional[int] = Field(default=0, description='Maximum number of errors, after which the user will be banned')


class SystemLoginMethod(BaseModel):
    """ System Login Method Config """
    bisheng_pro: bool = Field(default=False, description='Whether it is a commercial version, Verify Configuredlicense')
    admin_username: Optional[str] = Field(default=None, description='Admin username registered via web')
    allow_multi_login: bool = Field(default=True, description='Whether to allow multi-sign-on')


class MilvusConf(BaseModel):
    """ milvus Configure """
    connection_args: Optional[dict] = Field(default=None, description='milvus Configure')
    is_partition: Optional[bool] = Field(default=True, description='Is itpartitionMode',
                                         deprecated="Not in SupportpartitionMode")
    partition_suffix: Optional[str] = Field(default='1', description='partitionSuffix',
                                            deprecated="Not in SupportpartitionMode")

    @field_validator('connection_args', mode='before')
    @classmethod
    def convert_connection_args(cls, value):
        if isinstance(value, str):
            return json.loads(value)
        return value


class ElasticsearchConf(BaseModel):
    """ elasticsearch Configure """
    elasticsearch_url: Optional[str] = Field(default=None, alias='url',
                                             description='elasticsearchAccesses address')

    ssl_verify: Optional[str | dict] = Field(default='{}', description='Additional Arguments')

    @model_validator(mode='after')
    def validate(self):
        if isinstance(self.ssl_verify, str):
            self.ssl_verify = ast.literal_eval(self.ssl_verify)

        return self


class VectorStores(BaseModel):
    """ Vector Storage Configuration """
    milvus: MilvusConf = Field(default_factory=MilvusConf, description='milvus Configure')
    elasticsearch: ElasticsearchConf = Field(default_factory=ElasticsearchConf, description='elasticsearch Configure')


class MinioConf(BaseModel):
    """ minio Configure """
    secure: Optional[bool] = Field(default=False, description="Apakah ingin digunakan?https", alias="schema")
    cert_check: Optional[bool] = Field(default=False, description="Whether to calibrate the certificate")
    endpoint: Optional[str] = Field(default="127.0.0.1:9000", description="minio Service address")
    sharepoint: Optional[str] = Field(default="127.0.0.1:9000", description="minio Public access address")
    share_schema: Optional[bool] = Field(default=False, description="minio Whether the public access address is usedhttps")
    share_cert_check: Optional[bool] = Field(default=False, description="minio Whether the public access address verifies the certificate")
    access_key: Optional[str] = Field(default="minioadmin", description="minio Username")
    secret_key: Optional[str] = Field(default="minioadmin", description="minio Passwords")
    public_bucket: Optional[str] = Field(default="bisheng",
                                         description="Store permanent files by defaultbucket. Files can be permanently accessed by anonymous users")
    tmp_bucket: Optional[str] = Field(default="tmp-dir", description="Ad hocbucket, stored files will have an expiration date")


class ObjectStore(BaseModel):
    """ Object Storage Configuration """
    type: str = Field(default='minio', description="Object Storage Type")
    minio: Optional[MinioConf] = Field(default_factory=MinioConf, description="minio Configure")


class WorkflowConf(BaseModel):
    """ Workflow Configuration """
    max_steps: int = Field(default=50, description="Maximum number of steps a node can run")
    timeout: int = Field(default=720, description="Node timeout (min）")


class CeleryConf(BaseModel):
    """ Celery Configure """
    task_routers: Optional[Dict] = Field(default_factory=dict, description='Task Routing Configuration')
    beat_schedule: Optional[Dict] = Field(default_factory=dict, description='Timed Task Configuration')

    @model_validator(mode='after')
    def validate(self):
        if not self.task_routers:
            self.task_routers = {
                "bisheng.worker.knowledge.*": {"queue": "knowledge_celery"},  # Knowledge Base Related Tasks
                "bisheng.worker.workflow.*": {"queue": "workflow_celery"},  # Workflow Execution Related Tasks
            }
        if 'telemetry_mid_user_increment' not in self.beat_schedule:
            self.beat_schedule['telemetry_mid_user_increment'] = {
                'task': 'bisheng.worker.telemetry.mid_table.sync_mid_user_increment',
                'schedule': crontab('*/30 0 * * *'),  # 00:30 exec every day
            }
        if 'telemetry_mid_knowledge_increment' not in self.beat_schedule:
            self.beat_schedule['telemetry_mid_knowledge_increment'] = {
                'task': 'bisheng.worker.telemetry.mid_table.sync_mid_knowledge_increment',
                'schedule': crontab('*/30 0 * * *'),  # 00:30 exec every day
            }
        if 'telemetry_sync_mid_app_increment' not in self.beat_schedule:
            self.beat_schedule['telemetry_sync_mid_app_increment'] = {
                'task': 'bisheng.worker.telemetry.mid_table.sync_mid_app_increment',
                'schedule': crontab('*/30 0 * * *'),  # 00:30 exec every day
            }
        if 'telemetry_sync_mid_user_interact_dtl' not in self.beat_schedule:
            self.beat_schedule['telemetry_sync_mid_user_interact_dtl'] = {
                'task': 'bisheng.worker.telemetry.mid_table.sync_mid_user_interact_dtl',
                'schedule': crontab('*/30 0 * * *'),  # 00:30 exec every day
            }

        # convert str to crontab
        for key, task_info in self.beat_schedule.items():
            if isinstance(task_info['schedule'], str):
                self.beat_schedule[key]['schedule'] = crontab(task_info['schedule'])
        return self


class LinsightConf(BaseModel):
    """ Inspiration Configuration """
    debug: bool = Field(default=False, description='Whether to opendebugMode')
    tool_buffer: int = Field(default=100000, description='Maximum Tool Execution Historytoken, you need to summarize your history after')
    max_steps: int = Field(default=200, description='Maximum number of steps per task to prevent infinite loops')
    retry_num: int = Field(default=3, description='Number of times the model call was retried during the execution of the Ideas task')
    retry_sleep: int = Field(default=5, description='Interval between retries of model calls during execution of Invisible Tasks (seconds)')
    max_file_num: int = Field(default=5, description='BuatSOPJampromptThe number of user-uploaded file information placed in the')
    max_knowledge_num: int = Field(default=20, description='BuatSOPJampromptThe amount of knowledge base information placed in the')
    waiting_list_url: str = Field(default=None, description='waiting list Jump link')
    default_temperature: float = Field(default=0, description='Default Temperature at Model Request')
    retry_temperature: float = Field(default=1, description='reactModejsonModel temperature when retrying after parsing failure')
    file_content_length: int = Field(default=5000, description='The number of characters to read the contents of the file when splitting subtasks, which will be truncated when exceeded')
    max_file_content_num: int = Field(default=3, description='Number of files to read when subtasking, in reverse order by modification time')


class CookieConf(BaseModel):
    """ Cookie Configure """
    max_age: Optional[int] = Field(default=None, description="Cookie Maximum survival time in seconds")
    path: str = Field(default='/', description="Cookie Path Properties for")
    domain: Optional[str] = Field(default=None, description="Cookie Domain Properties for")
    secure: bool = Field(default=False, description="enabled secure Property")
    httponly: bool = Field(default=True, description="enabled HttpOnly Property")
    samesite: str = Field(default=None, description="SameSite property, optional value is 'lax', 'strict', 'none'")

    jwt_token_expire_time: int = Field(default=86400, description="JwtTokenExpiration time in seconds")
    jwt_iss: str = Field(default='bisheng', description="JwtTokenIssuer of")


class Etl4lmConf(BaseModel):
    """ Etl4lm Configure """
    url: str = Field(default='', description='etl4lmService Address')
    timeout: int = Field(default=600, description='etl4lmService Request Timeout (sec)')
    ocr_sdk_url: str = Field(default='', description='etl4lm ocr sdkService Address')


class KnowledgeConf(BaseModel):
    """ Knowledge Configure """
    etl4lm: Etl4lmConf


class Settings(BaseModel):
    """ Application Settings """
    model_config = ConfigDict(validate_assignment=True, arbitrary_types_allowed=True, extra='ignore')

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
    environment: Union[dict, str] = 'dev'
    # ↑↑↑ before config for langchain flow, will be deprecated
    debug: bool = False
    database_url: Optional[str] = None
    redis_url: Optional[Union[str, Dict]] = None
    celery_redis_url: Optional[Union[str, Dict]] = None
    redis: Optional[dict] = None
    admin: dict = {}
    cache: str = 'InMemoryCache'
    remove_api_keys: bool = False
    bisheng_rt: dict = {}
    default_llm: dict = {}
    jwt_secret: str = 'secret'
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

    license_str: Optional[str] = None  # license Contents

    @field_validator('database_url')
    @classmethod
    def set_database_url(cls, value):
        if not value:
            logger.debug('No database_url provided, trying bisheng_DATABASE_URL env variable')
            if bisheng_database_url := os.getenv('bisheng_DATABASE_URL'):
                value = bisheng_database_url
            else:
                logger.debug('No DATABASE_URL env variable, using sqlite database')
                value = 'sqlite:///./bisheng.db'
        else:
            # Encrypt password
            import re
            pattern = r'(?<=:)[^:]+(?=@)'  # Match colon after to@Any character before the symbol
            match = re.search(pattern, value)
            if match:
                password = match.group(0)
                new_password = decrypt_token(password)
                new_mysql_url = re.sub(pattern, f'{new_password}', value)
                value = new_mysql_url

        return value

    @model_validator(mode='before')
    @classmethod
    def set_redis_url(cls, values):
        if 'redis_url' in values:
            if isinstance(values['redis_url'], dict):
                for k, v in values['redis_url'].items():
                    if isinstance(v, str) and v.startswith('encrypt(') and v.endswith(')'):
                        v = v[8:-1]
                        values['redis_url'][k] = decrypt_token(v)
            else:
                import re
                pattern = r'(?<=:)[^:]+(?=@)'  # Match colon after to@Any character before the symbol
                match = re.search(pattern, values['redis_url'])
                if match:
                    password = match.group(0)
                    new_password = decrypt_token(password)
                    new_redis_url = re.sub(pattern, f'{new_password}', values['redis_url'])
                    values['redis_url'] = new_redis_url
        return values

    @model_validator(mode='before')
    @classmethod
    def set_celery_redis_url(cls, values):
        if 'celery_redis_url' in values:
            if isinstance(values['celery_redis_url'], dict):
                for k, v in values['celery_redis_url'].items():
                    if isinstance(v, str) and v.startswith('encrypt(') and v.endswith(')'):
                        v = v[8:-1]
                        values['celery_redis_url'][k] = decrypt_token(v)
            else:
                import re
                pattern = r'(?<=:)[^:]+(?=@)'  # Match colon after to@Any character before the symbol
                match = re.search(pattern, values['celery_redis_url'])
                if match:
                    password = match.group(0)
                    new_password = decrypt_token(password)
                    new_redis_url = re.sub(pattern, f'{new_password}', values['celery_redis_url'])
                    values['celery_redis_url'] = new_redis_url
        return values

    @model_validator(mode='before')
    @classmethod
    def validate_lists(cls, values):
        for key, value in values.items():
            if key != 'dev' and not value:
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
