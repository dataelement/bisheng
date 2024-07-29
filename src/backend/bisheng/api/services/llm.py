from typing import List

from fastapi import Request

from bisheng.api.errcode.base import NotFoundError
from bisheng.api.services.user_service import UserPayload
from bisheng.api.v1.schemas import LLMServerInfo, LLMModelInfo
from bisheng.database.models.llm_server import LLMDao


class LLMService:

    @classmethod
    def get_all_llm(cls, request: Request, login_user: UserPayload) -> List[LLMServerInfo]:
        """ 获取所有的模型数据， 不包含key等敏感信息 """
        llm_servers = LLMDao.get_all_server()
        ret = []
        server_ids = []
        for one in llm_servers:
            server_ids.append(one.id)
            ret.append(LLMServerInfo(**one.model_dump(exclude={'config'})))

        llm_models = LLMDao.get_model_by_server_ids(server_ids)
        server_dicts = {}
        for one in llm_models:
            if one.server_id not in server_dicts:
                server_dicts[one.server_id] = []
            server_dicts[one.server_id].append(one.model_dump(exclude={'config'}))

        for one in ret:
            one.models = server_dicts.get(one.id, [])
        return ret

    @classmethod
    def get_one_llm(cls, request: Request, login_user: UserPayload, server_id: int) -> LLMServerInfo:
        """ 获取一个服务提供方的详细信息 包含了key等敏感的配置信息 """
        llm = LLMDao.get_server_by_id(server_id)
        if not llm:
            raise NotFoundError.http_exception()

        models = LLMDao.get_model_by_server_ids([server_id])
        models = [LLMModelInfo(**one.model_dump()) for one in models]
        return LLMServerInfo(**llm.model_dump(), models=models)

    @classmethod
    def add_llm_server(cls, request: Request, login_user: UserPayload, server: LLMServerInfo) -> None:
        """ 添加一个服务提供方 """
        pass
