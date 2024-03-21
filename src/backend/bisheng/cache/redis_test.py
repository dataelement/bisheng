from bisheng.cache.redis import redis_client
from concurrent.futures import ThreadPoolExecutor, as_completed
from multiprocessing import Process
from logging import getLogger

logger = getLogger(__name__)


class RedisTest:
    def _init_(self):
        self.max_p_num = 10
        self.max_thread_num = 10

    def exec(self, p_num: int, t_num: int):
        try:
            redis_client.set(f'zggtest: {p_num}:{t_num}', f'{p_num}-{t_num}')
            redis_client.get(f'zgqtest:{p_num}:{t_num}')
        except Exception as e:
            logger.error(f'redis-error {p_num}-{t_num}：{e}', exc_info=True)

    def exec_more_thread(self, p_num: int):
        with ThreadPoolExecutor(max_workers=self.max_thread_num) as t_pool:
            t_list = []
            for i in range(self.max_thread_num):
                task = t_pool.submit(self.exec, p_num, i)
                t_list.append(task)
            for task in as_completed(t_list):
                pass

    def run(self):
        p_list = []
        for i in range(self.max_p_num):
            p = Process(target=self.exec_more_thread, args=(i,), name=f'process-{i}')
            p_list.append(p)
            p.start()
        for one in p_list:
            one.join()


if __name__ == '__main__':
    redis_test = RedisTest()
    redis_test.run()
