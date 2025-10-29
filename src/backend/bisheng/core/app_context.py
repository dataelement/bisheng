import asyncio
from typing import Dict, Any

from bisheng.prompts.prompt_loader import PromptLoader


class AppContext:

    def __init__(self):
        # 缓存字典 用于存储以初始化的对象
        self.cache: Dict[str, Any] = {}


    def get_event_loop(self) -> asyncio.AbstractEventLoop:
        """
        获取当前的事件循环，如果没有则创建一个新的。
        :return: asyncio.AbstractEventLoop 实例
        """
        key = "EVENT_LOOP"
        if key not in self.cache:
            self.cache[key] = asyncio.new_event_loop()
        return self.cache[key]

    # 获取 promptLoader
    def get_prompt_loader(self) -> PromptLoader:
        """
        获取 promptLoader，如果未初始化则进行初始化。
        :return: promptLoader 实例
        """
        key = "PROMPT_LOADER"
        if key not in self.cache:
            self.cache[key] = PromptLoader()
        return self.cache[key]


app_ctx = AppContext()


# 需要优先加载的模块
async def init_app_context():
    """
    初始化应用上下文。
    :param loop: 可选的事件循环
    """
    app_ctx.get_prompt_loader()


# 关闭应用上下文
async def close_app_context():
    """
    关闭应用上下文，释放资源。
    """
    # 清空缓存
    app_ctx.cache.clear()
