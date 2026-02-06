import os
from typing import List, Dict

import yaml
from loguru import logger

from bisheng.common.models.config import ConfigKeyEnum, Config
from bisheng.common.repositories.implementations.config_repository_impl import ConfigRepositoryImpl
from bisheng.core.cache.redis_manager import get_redis_client_sync
from bisheng.core.config.settings import Settings, PasswordConf, SystemLoginMethod, \
    WorkflowConf, LinsightConf, KnowledgeConf
from bisheng.core.database import get_sync_db_session, get_async_db_session

config_file = os.getenv('config', 'config.yaml')


def read_from_conf(file_path: str) -> str:
    if '/' not in file_path:
        # Get project main path
        current_path = os.path.dirname(os.path.abspath(__file__))
        # Look up the previous two levels of the catalog
        current_path = os.path.dirname(os.path.dirname(current_path))

        file_path = os.path.join(current_path, file_path)

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    return content


def parse_key(keys: list[str], setting_str: str = None, include_key: bool = False) -> str:
    # Setujukey  Back  yamlConfigure invalueAll strings, including comments
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
    """Configure service classes, inherited fromSettingsto provide configuration access"""

    def __init__(self, **data):

        super().__init__(**data)

    @staticmethod
    def env_var_constructor(loader, node):
        value = loader.construct_scalar(node)  # PyYAML loaderFixed method for constructing a variable value from the current node
        var_name = value.strip('${} ')  # Subtract variable values (e.g.${PATH}) Special characters and spaces before and after
        env_val = os.getenv(var_name)  # Try to get the variable name in the environment variable (e.g.USER) corresponding to the value, if it is not obtained, it is empty
        if env_val is None:
            raise ValueError(f'Environment variable {var_name} not found')
        return env_val

    @classmethod
    def load_settings_from_yaml(cls, file_path: str) -> 'ConfigService':
        # Sign up for customYAMLConstructor to handle environment variables
        yaml.SafeLoader.add_constructor('!env', cls.env_var_constructor)
        # Get current path
        current_path = os.path.dirname(os.path.abspath(__file__))
        # Look up the previous two levels of the catalog
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
            logger.debug(f'Loading {key} from {file_path}')

        return ConfigService(**settings_dict)

    async def init_config(self):
        # Inisialisasiconfig

        # First Passedyaml Get all of the profileskey
        config_content = read_from_conf('initdb_config.yaml')
        if not config_content:
            return
        async with get_async_db_session() as session:

            config_repository = ConfigRepositoryImpl(session)
            config = list(await config_repository.find_all())

            db_keys = {conf.key: conf.value for conf in config}
            all_config_key = 'initdb_config'
            # There is no default configuration in the database, write the default configuration to the database
            if db_keys.get(all_config_key, None) is None:
                # Write profile to database
                # Compatible with old configurations, old configurations and new profiles need to bemerge, Noold configDirectly combine the newconfigAdd to Database
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
        # No old configuration, write the new configuration directly to the database
        if old_db_config.__len__() == 0:
            return new_config
        new_content = ''
        # Start with the new configuration
        config_yaml = yaml.safe_load(new_config)
        for one in config_yaml.keys():
            if old_db_keys.get(one, None) is None:  # is a new configuration, directly using the contents of the file
                new_content += f'{parse_key([one], new_config, include_key=True)[0]}\n\n'
            else:
                new_content += f'{one}:\n{old_db_keys[one]}\n\n'
        return new_content

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

    def get_knowledge(self) -> KnowledgeConf:
        # Due to distributed requirements, configurations that can be changed are stored inmysqlso each time the configuration is read from themysqlRead in
        all_config = self.get_all_config()
        ret = all_config.get('knowledges', {})
        return KnowledgeConf(**ret)

    async def async_get_knowledge(self) -> KnowledgeConf:
        # Due to distributed requirements, configurations that can be changed are stored inmysqlso each time the configuration is read from themysqlRead in
        all_config = await self.aget_all_config()
        ret = all_config.get('knowledges', {})
        return KnowledgeConf(**ret)

    def get_default_llm(self):
        # Due to distributed requirements, configurations that can be changed are stored inmysqlso each time the configuration is read from themysqlRead in
        all_config = self.get_all_config()
        return all_config.get('default_llm', {})

    async def get_password_conf(self) -> PasswordConf:
        # Get password-related configuration items
        all_config = await self.aget_all_config()
        return PasswordConf(**all_config.get('password_conf', {}))

    def get_system_login_method(self) -> SystemLoginMethod:
        # Get password-related configuration items
        all_config = self.get_all_config()
        tmp = SystemLoginMethod(**all_config.get('system_login_method', {}))
        tmp.bisheng_pro = os.getenv('BISHENG_PRO') == 'true'
        return tmp

    async def aget_system_login_method(self) -> SystemLoginMethod:
        # Get password-related configuration items
        all_config = await self.aget_all_config()
        tmp = SystemLoginMethod(**all_config.get('system_login_method', {}))
        tmp.bisheng_pro = os.getenv('BISHENG_PRO') == 'true'
        return tmp

    def get_workflow_conf(self) -> WorkflowConf:
        # Get password-related configuration items
        all_config = self.get_all_config()
        return WorkflowConf(**all_config.get('workflow', {}))

    def get_linsight_conf(self) -> LinsightConf:
        # Get Ideas-related configuration items
        all_config = self.get_all_config()
        conf = LinsightConf(debug=self.linsight_conf.debug)
        linsight_conf = all_config.get('linsight', {})
        for k, v in linsight_conf.items():
            setattr(conf, k, v)
        return conf

    def get_from_db(self, key: str):
        # Get all of them firstkey
        all_config = self.get_all_config()
        return all_config.get(key, {})

    async def aget_from_db(self, key: str):
        # Get all of them firstkey
        all_config = await self.aget_all_config()
        return all_config.get(key, {})


settings = ConfigService.load_settings_from_yaml(config_file)
