from typing import Any, Dict

from bisheng.api.errcode.server import NotFoundServerError
from bisheng.api.v1.schemas import UnifiedResponseModel
from bisheng.database.models.finetune import Finetune, FinetuneCreate, FinetuneDao
from bisheng.database.models.server import ServerDao
from bisheng.utils.logger import logger
from pydantic import BaseModel


class FinetuneService(BaseModel):

    @classmethod
    def validate_extra_params(cls, params: Dict) -> UnifiedResponseModel | None:
        """ 检查extra_params内的参数，返回None表示校验通过 """

        return None

    @classmethod
    def create_finetune(cls, finetune: FinetuneCreate, user: Any) -> UnifiedResponseModel[Finetune]:
        # 查找RT服务是否存在
        server = ServerDao.find_server(finetune.server)
        if not server:
            return NotFoundServerError.return_resp(None)

        # 校验额外参数
        validate_ret = cls.validate_extra_params(finetune.extra_params)
        if validate_ret is not None:
            return validate_ret

        # 插入到数据库内
        finetune = FinetuneDao.insert_one(Finetune(**finetune.dict()))

        # 调用SFT-backend的API
        logger.info('start process sft job')

        print(finetune)
        return UnifiedResponseModel()
