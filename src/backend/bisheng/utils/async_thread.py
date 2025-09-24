import asyncio
import threading
from asyncio import Future


class AsyncTaskRunner(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.loop = None
        self._ready_event = threading.Event()
        self._task_queue = []
        self._results = {}
        self._next_task_id = 0
        self._lock = threading.Lock()

    def run(self):
        """线程主函数，运行事件循环"""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self._ready_event.set()  # 通知主线程事件循环已就绪
        self.loop.run_forever()

    def submit(self, coro) -> Future:
        """
        提交一个异步任务

        :param coro: 要执行的协程
        :return: 任务ID，用于获取结果
        """
        if not self.loop:
            self.start()
            self._ready_event.wait()  # 等待事件循环就绪

        with self._lock:
            return asyncio.run_coroutine_threadsafe(
                coro,
                self.loop
            )

    def shutdown(self):
        """关闭线程和事件循环"""
        if self.loop:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.join()

    def __del__(self):
        self.shutdown()
