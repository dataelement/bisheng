import os
from typing import Dict, Optional, Union

import yaml
from bisheng.database.models.config import Config
from bisheng.utils.logger import logger
from cryptography.fernet import Fernet
from langchain.pydantic_v1 import BaseSettings, root_validator, validator
from sqlmodel import select


class Settings(BaseSettings):
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
    openai_conf = {}
    minio_conf = {}

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

    class Config:
        validate_assignment = True
        extra = 'ignore'

    @root_validator()
    def validate_lists(cls, values):
        for key, value in values.items():
            if key != 'dev' and not value:
                values[key] = []
        return values

    def get_knowledge(self):
        # 由于分布式的要求，可变更的配置存储于mysql，因此读取配置每次从mysql中读取
        all_config = self.get_all_config()
        return all_config.get('knowledges', {})

    def get_default_llm(self):
        # 由于分布式的要求，可变更的配置存储于mysql，因此读取配置每次从mysql中读取
        all_config = self.get_all_config()
        return all_config.get('default_llm', {})

    def get_from_db(self, key: str):
        # 先获取所有的key
        all_config = self.get_all_config()
        return all_config.get(key, {})

    def get_all_config(self):
        from bisheng.database.base import session_getter
        from bisheng.cache.redis import redis_client
        redis_key = 'config:initdb_config'
        cache = redis_client.get(redis_key)
        if cache:
            return yaml.safe_load(cache)
        else:
            with session_getter() as session:
                initdb_config = session.exec(select(Config).where(Config.key == 'initdb_config')).first()
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
        self.dev = dev

    def update_settings(self, **kwargs):
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)


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
