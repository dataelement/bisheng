import yaml
from bisheng.database.models.config import Config
from bisheng.settings import parse_key, read_from_conf
from bisheng.utils.logger import logger
from sqlmodel import select


def init_config():
    # 初始化config
    from bisheng.database.base import session_getter

    # 首先通过yaml 获取配置文件所有的key
    dbconfig = read_from_conf('initdb_config.yaml')
    if not dbconfig:
        return
    with session_getter() as session:
        config = session.exec(select(Config)).all()
        db_keys = {conf.key for conf in config}
        config_yaml = yaml.safe_load(dbconfig)
        keys = config_yaml.keys()
        try:
            for key in keys:
                if key not in db_keys:
                    values = parse_key([key], dbconfig)
                    db_config = Config(key=key, value=values[0])
                    session.add(db_config)
            session.commit()
        except Exception as e:
            logger.exception(e)
            session.rollback()
