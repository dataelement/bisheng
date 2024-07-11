from typing import Dict, List

import yaml
from bisheng.database.models.config import Config
from bisheng.database.base import session_getter
from bisheng.settings import parse_key, read_from_conf
from bisheng.utils.logger import logger
from sqlmodel import select


def init_config():
    # 初始化config

    # 首先通过yaml 获取配置文件所有的key
    config_content = read_from_conf('initdb_config.yaml')
    if not config_content:
        return
    with session_getter() as session:
        config = session.exec(select(Config)).all()
        db_keys = {conf.key: conf.value for conf in config}
        all_config_key = 'initdb_config'
        # 数据库内没有默认配置，将默认配置写入到数据库
        if db_keys.get(all_config_key, None) is None:
            # 将配置文件写入到数据库
            # 兼容旧配置，需要将旧配置和新的配置文件进行merge, 没有old config直接将新的config添加到数据库
            new_config_content = merge_old_config(config_content, config, db_keys)
            try:
                db_config = Config(key=all_config_key, value=new_config_content)
                session.add(db_config)
                session.commit()
            except Exception as e:
                logger.exception(e)
                session.rollback()


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
