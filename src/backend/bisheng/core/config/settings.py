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
    handlers: List[Dict] = Field(default_factory=list, description='日志处理器')

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
    password_valid_period: Optional[int] = Field(default=0, description='密码超过X天必须进行修改, 登录提示重新修改密码')
    login_error_time_window: Optional[int] = Field(default=0, description='登录错误时间窗口,单位分钟')
    max_error_times: Optional[int] = Field(default=0, description='最大错误次数，超过后会封禁用户')


class SystemLoginMethod(BaseModel):
    """ System Login Method Config """
    bisheng_pro: bool = Field(default=False, description='是否是商业版, 从环境变量获取')
    admin_username: Optional[str] = Field(default=None, description='通过网关注册的系统管理员用户名')
    allow_multi_login: bool = Field(default=True, description='是否允许多点登录')


class MilvusConf(BaseModel):
    """ milvus 配置 """
    connection_args: Optional[dict] = Field(default=None, description='milvus 配置')
    is_partition: Optional[bool] = Field(default=True, description='是否是partition模式',
                                         deprecated="不在支持partition模式")
    partition_suffix: Optional[str] = Field(default='1', description='partition后缀',
                                            deprecated="不在支持partition模式")

    @field_validator('connection_args', mode='before')
    @classmethod
    def convert_connection_args(cls, value):
        if isinstance(value, str):
            return json.loads(value)
        return value


class ElasticsearchConf(BaseModel):
    """ elasticsearch 配置 """
    elasticsearch_url: Optional[str] = Field(default=None, alias='url',
                                             description='elasticsearch访问地址')

    ssl_verify: Optional[str | dict] = Field(default='{}', description='额外的参数')

    @model_validator(mode='after')
    def validate(self):
        if isinstance(self.ssl_verify, str):
            self.ssl_verify = ast.literal_eval(self.ssl_verify)

        return self


class VectorStores(BaseModel):
    """ 向量存储配置 """
    milvus: MilvusConf = Field(default_factory=MilvusConf, description='milvus 配置')
    elasticsearch: ElasticsearchConf = Field(default_factory=ElasticsearchConf, description='elasticsearch 配置')


class MinioConf(BaseModel):
    """ minio 配置 """
    secure: Optional[bool] = Field(default=False, description="是否使用https", alias="schema")
    cert_check: Optional[bool] = Field(default=False, description="是否校验证书")
    endpoint: Optional[str] = Field(default="127.0.0.1:9000", description="minio 地址")
    sharepoint: Optional[str] = Field(default="127.0.0.1:9000", description="minio 公开访问地址")
    share_schema: Optional[bool] = Field(default=False, description="minio 公开访问地址是否使用https")
    share_cert_check: Optional[bool] = Field(default=False, description="minio 公开访问地址是否校验证书")
    access_key: Optional[str] = Field(default="minioadmin", description="minio 用户名")
    secret_key: Optional[str] = Field(default="minioadmin", description="minio 密码")
    public_bucket: Optional[str] = Field(default="bisheng",
                                         description="默认存储永久文件的bucket。文件可被匿名用户永久访问")
    tmp_bucket: Optional[str] = Field(default="tmp-dir", description="临时bucket，存储的文件会设置有效期")


class ObjectStore(BaseModel):
    """ 对象存储配置 """
    type: str = Field(default='minio', description="对象存储类型")
    minio: Optional[MinioConf] = Field(default_factory=MinioConf, description="minio 配置")


class WorkflowConf(BaseModel):
    """ 工作流配置 """
    max_steps: int = Field(default=50, description="节点运行最大步数")
    timeout: int = Field(default=720, description="节点超时时间（min）")


class CeleryConf(BaseModel):
    """ Celery 配置 """
    task_routers: Optional[Dict] = Field(default_factory=dict, description='任务路由配置')
    beat_schedule: Optional[Dict] = Field(default_factory=dict, description='定时任务配置')

    @model_validator(mode='after')
    def validate(self):
        if not self.task_routers:
            self.task_routers = {
                "bisheng.worker.knowledge.*": {"queue": "knowledge_celery"},  # 知识库相关任务
                "bisheng.worker.workflow.*": {"queue": "workflow_celery"},  # 工作流执行相关任务
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
    """ 灵思配置 """
    debug: bool = Field(default=False, description='是否开启debug模式')
    tool_buffer: int = Field(default=100000, description='工具执行历史记录的最大token，超过后需要总结下历史记录')
    max_steps: int = Field(default=200, description='单个任务最大执行步骤数，防止死循环')
    retry_num: int = Field(default=3, description='灵思任务执行过程中模型调用重试次数')
    retry_sleep: int = Field(default=5, description='灵思任务执行过程中模型调用重试间隔时间（秒）')
    max_file_num: int = Field(default=5, description='生成SOP时，prompt里放的用户上传文件信息的数量')
    max_knowledge_num: int = Field(default=20, description='生成SOP时，prompt里放的知识库信息的数量')
    waiting_list_url: str = Field(default=None, description='waiting list 跳转链接')
    default_temperature: float = Field(default=0, description='模型请求时的默认温度')
    retry_temperature: float = Field(default=1, description='react模式json解析失败后重试时模型温度')
    file_content_length: int = Field(default=5000, description='拆分子任务时读取文件内容的字符数，超过后会截断')
    max_file_content_num: int = Field(default=3, description='拆分子任务时读取文件数量，按修改时间倒序')


class CookieConf(BaseModel):
    """ Cookie 配置 """
    max_age: Optional[int] = Field(default=None, description="Cookie 的最大存活时间，单位为秒")
    path: str = Field(default='/', description="Cookie 的路径属性")
    domain: Optional[str] = Field(default=None, description="Cookie 的域属性")
    secure: bool = Field(default=False, description="是否启用 secure 属性")
    httponly: bool = Field(default=True, description="是否启用 HttpOnly 属性")
    samesite: str = Field(default=None, description="SameSite 属性，可选值为 'lax', 'strict', 'none'")

    jwt_token_expire_time: int = Field(default=86400, description="JwtToken的的过期时间，单位为秒")
    jwt_iss: str = Field(default='bisheng', description="JwtToken的签发者")


class Etl4lmConf(BaseModel):
    """ Etl4lm 配置 """
    url: str = Field(default='', description='etl4lm服务地址')
    timeout: int = Field(default=600, description='etl4lm服务请求超时时间（秒）')
    ocr_sdk_url: str = Field(default='', description='etl4lm ocr sdk服务地址')


class KnowledgeConf(BaseModel):
    """ Knowledge 配置 """
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
            # 对密码进行加密
            import re
            pattern = r'(?<=:)[^:]+(?=@)'  # 匹配冒号后面到@符号前面的任意字符
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
                pattern = r'(?<=:)[^:]+(?=@)'  # 匹配冒号后面到@符号前面的任意字符
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
                pattern = r'(?<=:)[^:]+(?=@)'  # 匹配冒号后面到@符号前面的任意字符
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
