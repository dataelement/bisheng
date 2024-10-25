import json
import os
import re
from typing import Dict, List, Optional, Union

import yaml
from cryptography.fernet import Fernet
from langchain.pydantic_v1 import BaseSettings, root_validator, validator
from loguru import logger
from pydantic import BaseModel, Field
from sqlmodel import select


class LoggerConf(BaseModel):
    level: str = 'DEBUG'
    format: str = '<level>[{level.name} process-{process.id}-{thread.id} {name}:{line}]</level> - <level>trace={extra[trace_id]} {message}</level>'  # noqa
    handlers: List[Dict] = []

    @classmethod
    def parse_logger_sink(cls, sink: str) -> str:
        match = re.search(r'\{(.+?)\}', sink)
        if not match:
            return sink
        env_keys = {}
        for one in match.groups():
            env_keys[one] = os.getenv(one, '')
        return sink.format(**env_keys)

    @validator('handlers', pre=True)
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
    password_valid_period: Optional[int] = Field(default=0, description='密码超过X天必须进行修改, 登录提示重新修改密码')
    login_error_time_window: Optional[int] = Field(default=0, description='登录错误时间窗口,单位分钟')
    max_error_times: Optional[int] = Field(default=0, description='最大错误次数，超过后会封禁用户')


class SystemLoginMethod(BaseModel):
    bisheng_pro: bool = Field(default=False, description='是否是商业版, 从环境变量获取')
    admin_username: Optional[str] = Field(default=None, description='通过网关注册的系统管理员用户名')
    allow_multi_login: bool = Field(default=True, description='是否允许多点登录')


class MilvusConf(BaseModel):
    connection_args: Optional[str] = Field(
        default='{"host":"127.0.0.1","port":19530,"user":"","password":"","secure":false}',
        description='milvus 配置')
    is_partition: Optional[bool] = Field(default=False, description='是否是partition模式')
    partition_suffix: Optional[str] = Field(default='1', description='partition后缀')


class ElasticsearchConf(BaseModel):
    url: Optional[str] = Field(default='http://127.0.0.1:9200', description='elasticsearch访问地址')
    ssl_verify: Optional[str] = Field(default='{"basic_auth": ("elastic", "elastic")}', description='额外的参数')


class VectorStores(BaseModel):
    milvus: MilvusConf = Field(default_factory=MilvusConf, description='milvus 配置')
    elasticsearch: ElasticsearchConf = Field(default_factory=ElasticsearchConf, description='elasticsearch 配置')


class MinioConf(BaseModel):
    minio_schema: Optional[bool] = Field(default=False, description="是否使用https", alias="schema")
    cert_check: Optional[bool] = Field(default=False, description="是否校验证书")
    endpoint: Optional[str] = Field(default="127.0.0.1:9000", description="minio 地址")
    sharepoint: Optional[str] = Field(default="127.0.0.1:9000", description="minio 公开访问地址")
    access_key: Optional[str] = Field(default="minioadmin", description="minio 用户名")
    secret_key: Optional[str] = Field(default="minioadmin", description="minio 密码")


class ObjectStore(BaseModel):
    type: str = Field(default='minio', description="对象存储类型")
    minio: MinioConf = Field(default_factory=MinioConf, description="minio 配置")


class Settings(BaseModel):
    class Config:
        validate_assignment = True
        arbitrary_types_allowed = True
        extra = 'ignore'

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
    database_url: Optional[str] = None
    redis_url: Optional[Union[str, Dict]] = None
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
    logger_conf: LoggerConf = LoggerConf()
    password_conf: PasswordConf = PasswordConf()
    system_login_method: SystemLoginMethod = {}
    vector_stores: VectorStores = {}
    object_storage: ObjectStore = {}

    @validator('database_url', pre=True)
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

    @root_validator()
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

    @root_validator()
    def validate_lists(cls, values):
        for key, value in values.items():
            if key != 'dev' and not value:
                values[key] = []
        return values

    def get_knowledge(self):
        # 由于分布式的要求，可变更的配置存储于mysql，因此读取配置每次从mysql中读取
        all_config = self.get_all_config()
        ret = all_config.get('knowledges', {})
        # milvus、 es、minio配置从环境变量获取
        ret.update({
            "vectorstores": {
                "Milvus": {
                    "connection_args": json.loads(self.vector_stores.milvus.connection_args),
                    "is_partition": self.vector_stores.milvus.is_partition,
                    "partition_suffix": self.vector_stores.milvus.partition_suffix,
                },
                "ElasticKeywordsSearch": {
                    "elasticsearch_url": self.vector_stores.elasticsearch.url,
                    "ssl_verify": self.vector_stores.elasticsearch.ssl_verify,
                }
            },
            "minio": {
                "SCHEMA": self.object_storage.minio.minio_schema,
                "CERT_CHECK": self.object_storage.minio.cert_check,
                "MINIO_ENDPOINT": self.object_storage.minio.endpoint,
                "MINIO_SHAREPOIN": self.object_storage.minio.sharepoint,  # 确保和nginx的代理地址一致。同一个docker-compose启动可以直接使用默认值
                "MINIO_ACCESS_KEY": self.object_storage.minio.access_key,
                "MINIO_SECRET_KEY": self.object_storage.minio.secret_key,
            }
        })

        return ret

    def get_default_llm(self):
        # 由于分布式的要求，可变更的配置存储于mysql，因此读取配置每次从mysql中读取
        all_config = self.get_all_config()
        return all_config.get('default_llm', {})

    def get_password_conf(self) -> PasswordConf:
        # 获取密码相关的配置项
        all_config = self.get_all_config()
        return PasswordConf(**all_config.get('password_conf', {}))

    def get_system_login_method(self) -> SystemLoginMethod:
        # 获取密码相关的配置项
        all_config = self.get_all_config()
        tmp = SystemLoginMethod(**all_config.get('system_login_method', {}))
        tmp.bisheng_pro = os.getenv('BISHENG_PRO') == 'true'
        return tmp

    def get_from_db(self, key: str):
        # 先获取所有的key
        all_config = self.get_all_config()
        return all_config.get(key, {})

    def get_all_config(self):
        from bisheng.database.base import session_getter
        from bisheng.cache.redis import redis_client
        from bisheng.database.models.config import Config

        redis_key = 'config:initdb_config'
        cache = redis_client.get(redis_key)
        if cache:
            return yaml.safe_load(cache)
        else:
            with session_getter() as session:
                initdb_config = session.exec(
                    select(Config).where(Config.key == 'initdb_config')).first()
                if initdb_config:
                    redis_client.set(redis_key, initdb_config.value, 100)
                    return yaml.safe_load(initdb_config.value)
                else:
                    raise Exception('initdb_config not found, please check your system config')

    def update_from_yaml(self, file_path: str, dev: bool = False):
        new_settings = load_settings_from_yaml(file_path)
        self.chains = new_settings.chains or {}
        self.agents = new_settings.agents or {}
        self.prompts = new_settings.prompts or {}
        self.llms = new_settings.llms or {}
        self.tools = new_settings.tools or {}
        self.memories = new_settings.memories or {}
        self.wrappers = new_settings.wrappers or {}
        self.toolkits = new_settings.toolkits or {}
        self.textsplitters = new_settings.textsplitters or {}
        self.utilities = new_settings.utilities or {}
        self.embeddings = new_settings.embeddings or {}
        self.knowledges = new_settings.knowledges or {}
        self.vectorstores = new_settings.vectorstores or {}
        self.documentloaders = new_settings.documentloaders or {}
        self.retrievers = new_settings.retrievers or {}
        self.output_parsers = new_settings.output_parsers or {}
        self.input_output = new_settings.input_output or {}
        self.autogen_roles = new_settings.autogen_roles or {}

        self.admin = new_settings.admin or {}
        self.bisheng_rt = new_settings.bisheng_rt or {}
        self.default_llm = new_settings.default_llm or {}
        self.gpts = new_settings.gpts or {}
        self.openai_conf = new_settings.openai_conf
        self.minio_conf = new_settings.openai_conf
        self.vector_stores = new_settings.vector_stores or {}
        self.object_storage = new_settings.object_storage or {}
        self.dev = dev

    def update_settings(self, **kwargs):
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)


def env_var_constructor(loader, node):
    value = loader.construct_scalar(node)  # PyYAML loader的固定方法，用于根据当前节点构造一个变量值
    var_name = value.strip('${} ')  # 去除变量值（例如${PATH}）前后的特殊字符及空格
    env_val = os.getenv(var_name)  # 尝试在环境变量中获取变量名（如USER）对应的值，获取不到则为空
    if env_val is None:
        raise ValueError(f'Environment variable {var_name} not found')
    return env_val


yaml.SafeLoader.add_constructor('!env', env_var_constructor)


def save_settings_to_yaml(settings: Settings, file_path: str):
    # Check if a string is a valid path or a file name
    if '/' not in file_path:
        # Get current path
        current_path = os.path.dirname(os.path.abspath(__file__))

        file_path = os.path.join(current_path, file_path)

    with open(file_path, 'w') as f:
        settings_dict = settings.dict()
        yaml.dump(settings_dict, f)


def load_settings_from_yaml(file_path: str) -> Settings:
    # Get current path
    current_path = os.path.dirname(os.path.abspath(__file__))
    # Check if a string is a valid path or a file name
    if '/' not in file_path:
        file_path = os.path.join(current_path, file_path)

    with open(file_path, 'r', encoding='utf-8') as f:
        settings_dict = yaml.safe_load(f)

    with open(os.path.join(current_path, 'default_node.yaml'), 'r', encoding='utf-8') as node:
        settings_dict.update(yaml.safe_load(node))
    for key in settings_dict:
        if key not in Settings.__fields__.keys():
            raise KeyError(f'Key {key} not found in settings')
        logger.debug(f'Loading {len(settings_dict[key])} {key} from {file_path}')

    return Settings(**settings_dict)


def read_from_conf(file_path: str) -> str:
    if '/' not in file_path:
        # Get current path
        current_path = os.path.dirname(os.path.abspath(__file__))

        file_path = os.path.join(current_path, file_path)

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    return content


def save_conf(file_path: str, content: str):
    if '/' not in file_path:
        # Get current path
        current_path = os.path.dirname(os.path.abspath(__file__))

        file_path = os.path.join(current_path, file_path)

    with open(file_path, 'w') as f:
        f.write(content)


def parse_key(keys: list[str], setting_str: str = None, include_key: bool = False) -> str:
    # 通过key，返回yaml配置里value所有的字符串，包含注释
    if not setting_str:
        setting_str = read_from_conf(config_file)
    setting_lines = setting_str.split('\n')
    value_of_key = [[] for _ in keys]
    value_start_flag = [False for _ in keys]
    prev_line = ''
    for line in setting_lines:
        for index, key in enumerate(keys):
            if value_start_flag[index]:
                if line.startswith('  ') or not line.strip() or line.startswith('#'):
                    value_of_key[index].append(line)
                else:
                    value_start_flag[index] = False
                    continue
            if line.startswith(key + ':'):
                value_start_flag[index] = True
                if include_key:
                    if prev_line.startswith('#'):
                        value_of_key[index].append(prev_line)
                    value_of_key[index].append(line)
        prev_line = line
    return ['\n'.join(value) for value in value_of_key]


secret_key = 'TI31VYJ-ldAq-FXo5QNPKV_lqGTFfp-MIdbK2Hm5F1E='


def encrypt_token(token: str):
    return Fernet(secret_key).encrypt(token.encode())


def decrypt_token(token: str):
    return Fernet(secret_key).decrypt(token).decode()


config_file = os.getenv('config', 'config.yaml')
settings = load_settings_from_yaml(config_file)
