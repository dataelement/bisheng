from loguru import logger

from bisheng.api.services.user_service import UserPayload
from bisheng.api.v1.schema.promise import BusinessUserPromise
from bisheng.database.models.promise import PromiseDao, Promise, UserPromise


class PromiseService:

    @classmethod
    def create_promise(cls, login_user: UserPayload, business_id: str, promise_id: str):
        """ 给某个业务新建承诺书 """
        logger.info(
            f'act=create_promise user={login_user.user_name}, business_id={business_id}, promise_id={promise_id}')
        promise_db = PromiseDao.create(Promise(business_id=business_id,
                                               promise_id=promise_id,
                                               user_id=login_user.user_id), delete_other=True)
        return promise_db

    @classmethod
    def get_user_promise(cls, login_user: UserPayload, business_id: str):
        """ 获取业务所有的承诺书，并返回用户是否签署过 """
        res = []
        promise_list = PromiseDao.get_promise(business_id)
        if not promise_list:
            return []
        user_business_promise = PromiseDao.get_user_promise(user_id=login_user.user_id,
                                                            business_ids=[one.business_id for one in promise_list])
        user_business_map = {}
        for one in user_business_promise:
            key = f'{one.business_id}_{one.promise_id}'
            user_business_map[key] = one

        for one in promise_list:
            write = False
            create_time = None
            user_name = None
            key = f'{one.business_id}_{one.promise_id}'
            if user_business_map.get(key, None):
                write = True
                create_time = user_business_map[key].create_time
                user_name = user_business_map[key].user_name
            res.append(BusinessUserPromise(
                business_id=one.business_id,
                promise_id=one.promise_id,
                user_id=login_user.user_id,
                user_name=user_name,
                write=write,
                create_time=create_time
            ))
        return res

    @classmethod
    def user_write_promise(cls, login_user: UserPayload, business_id: str, business_name: str, promise_id: str,
                           promise_name: str) -> BusinessUserPromise | None:
        """ 用户签署某个业务的某个承诺书 """
        logger.info(
            f'act=user_write_promise user={login_user.user_name}, business_id={business_id}, promise_id={promise_id}')
        business_list = PromiseDao.get_promise(business_id=business_id, promise_id=promise_id)
        if len(business_list) == 0:
            return None

        res = PromiseDao.create_user_promise(UserPromise(business_id=business_id, business_name=business_name,
                                                         promise_id=promise_id, promise_name=promise_name,
                                                         user_id=login_user.user_id, user_name=login_user.user_name))
        return BusinessUserPromise(**res.model_dump(), write=True)
