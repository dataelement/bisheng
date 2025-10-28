import os
from typing import List, Dict

import yaml
from loguru import logger

from bisheng.common.models.config import ConfigKeyEnum, Config
from bisheng.common.repositories.implementations.config_repository_impl import ConfigRepositoryImpl
from bisheng.core.cache.redis_manager import get_redis_client_sync
from bisheng.core.config.settings import Settings, MinioConf, VectorStores, PasswordConf, SystemLoginMethod, \
    WorkflowConf, LinsightConf
from bisheng.core.database import get_sync_db_session, get_async_db_session

config_file = os.getenv('config', 'config.yaml')


def read_from_conf(file_path: str) -> str:
    if '/' not in file_path:
        # Get project main path
        current_path = os.path.dirname(os.path.abspath(__file__))
        # 向前两级目录查找
        current_path = os.path.dirname(os.path.dirname(current_path))

        file_path = os.path.join(current_path, file_path)

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    return content


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


class ConfigService(Settings):
    """配置服务类，继承自Settings以提供配置访问功能"""

    def __init__(self, **data):

        # 注册自定义的YAML构造器以处理环境变量
        yaml.SafeLoader.add_constructor('!env', self.env_var_constructor)

        super().__init__(**data)

    @staticmethod
    def env_var_constructor(loader, node):
        value = loader.construct_scalar(node)  # PyYAML loader的固定方法，用于根据当前节点构造一个变量值
        var_name = value.strip('${} ')  # 去除变量值（例如${PATH}）前后的特殊字符及空格
        env_val = os.getenv(var_name)  # 尝试在环境变量中获取变量名（如USER）对应的值，获取不到则为空
        if env_val is None:
            raise ValueError(f'Environment variable {var_name} not found')
        return env_val

    @staticmethod
    def load_settings_from_yaml(file_path: str) -> 'ConfigService':
        # Get current path
        current_path = os.path.dirname(os.path.abspath(__file__))
        # 向前两级目录查找
        current_path = os.path.dirname(os.path.dirname(current_path))
        # Check if a string is a valid path or a file name
        if '/' not in file_path:
            file_path = os.path.join(current_path, file_path)

        with open(file_path, 'r', encoding='utf-8') as f:
            settings_dict = yaml.safe_load(f)

        with open(os.path.join(current_path, 'default_node.yaml'), 'r', encoding='utf-8') as node:
            settings_dict.update(yaml.safe_load(node))
        for key in settings_dict:
            if key not in Settings.model_fields.keys():
                raise KeyError(f'Key {key} not found in settings')
            logger.debug(f'Loading {len(settings_dict[key])} {key} from {file_path}')

        return ConfigService(**settings_dict)

    async def init_config(self):
        # 初始化config

        # 首先通过yaml 获取配置文件所有的key
        config_content = read_from_conf('initdb_config.yaml')
        if not config_content:
            return
        async with get_async_db_session() as session:

            config_repository = ConfigRepositoryImpl(session)
            config = list(await config_repository.find_all())

            db_keys = {conf.key: conf.value for conf in config}
            all_config_key = 'initdb_config'
            # 数据库内没有默认配置，将默认配置写入到数据库
            if db_keys.get(all_config_key, None) is None:
                # 将配置文件写入到数据库
                # 兼容旧配置，需要将旧配置和新的配置文件进行merge, 没有old config直接将新的config添加到数据库
                new_config_content = self.merge_old_config(config_content, config, db_keys)
                try:
                    db_config = Config(key=all_config_key, value=new_config_content)
                    session.add(db_config)
                    await session.commit()
                except Exception as e:
                    logger.exception(e)
                    await session.rollback()

    @staticmethod
    def merge_old_config(new_config: str, old_db_config: List[Config], old_db_keys: Dict[str, str]):
        # 没有旧的配置，直接将新的配置写入到数据库
        if old_db_config.__len__() == 0:
            return new_config
        new_content = ''
        # 先将新的配置
        config_yaml = yaml.safe_load(new_config)
        for one in config_yaml.keys():
            if old_db_keys.get(one, None) is None:  # 是新的配置，直接用文件内的内容
                new_content += f'{parse_key([one], new_config, include_key=True)[0]}\n\n'
            else:
                new_content += f'{one}:\n{old_db_keys[one]}\n\n'
        return new_content

    def update_from_yaml(self, file_path: str, dev: bool = False):
        """
        更新配置项从指定的YAML文件
        :param file_path:
        :param dev:
        :return:
        """
        new_settings = self.load_settings_from_yaml(file_path)
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
        """
        动态更新配置项
        :param kwargs:
        :return:
        """
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)

    @staticmethod
    def get_all_config():

        redis_key = 'config:initdb_config'
        cache = get_redis_client_sync().get(redis_key)
        if cache:
            return yaml.safe_load(cache)
        else:
            with get_sync_db_session() as session:
                config_repository = ConfigRepositoryImpl(session)
                initdb_config = config_repository.find_one_sync(key=ConfigKeyEnum.INIT_DB.value)

                if initdb_config:
                    get_redis_client_sync().set(redis_key, initdb_config.value, 100)
                    return yaml.safe_load(initdb_config.value)
                else:
                    raise Exception('initdb_config not found, please check your system config')

    @staticmethod
    async def aget_all_config():

        redis_key = 'config:initdb_config'
        cache = await get_redis_client_sync().aget(redis_key)
        if cache:
            return yaml.safe_load(cache)
        else:
            async with get_async_db_session() as session:
                config_repository = ConfigRepositoryImpl(session)
                initdb_config = await config_repository.find_one(key=ConfigKeyEnum.INIT_DB.value)
                if initdb_config:
                    await get_redis_client_sync().aset(redis_key, initdb_config.value, 100)
                    return yaml.safe_load(initdb_config.value)
                else:
                    raise Exception('initdb_config not found, please check your system config')

    def get_knowledge(self):
        # 由于分布式的要求，可变更的配置存储于mysql，因此读取配置每次从mysql中读取
        all_config = self.get_all_config()
        ret = all_config.get('knowledges', {})
        return ret

    def get_minio_conf(self) -> MinioConf:
        return self.object_storage.minio

    def get_vectors_conf(self) -> VectorStores:
        return self.vector_stores

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

    def get_workflow_conf(self) -> WorkflowConf:
        # 获取密码相关的配置项
        all_config = self.get_all_config()
        return WorkflowConf(**all_config.get('workflow', {}))

    def get_linsight_conf(self) -> LinsightConf:
        # 获取灵思相关的配置项
        all_config = self.get_all_config()
        conf = LinsightConf(debug=self.linsight_conf.debug)
        linsight_conf = all_config.get('linsight', {})
        for k, v in linsight_conf.items():
            setattr(conf, k, v)
        return conf

    def get_from_db(self, key: str):
        # 先获取所有的key
        all_config = self.get_all_config()
        return all_config.get(key, {})


settings = ConfigService.load_settings_from_yaml(config_file)
