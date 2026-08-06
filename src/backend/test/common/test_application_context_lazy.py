from bisheng.core.context import FunctionContextManager
from bisheng.core.context.manager import ApplicationContextManager


async def test_lazy_context_initializes_only_on_first_access_and_closes() -> None:
    events: list[str] = []
    manager = ApplicationContextManager()

    async def initialize_eager() -> str:
        events.append("eager:init")
        return "eager"

    async def initialize_lazy() -> str:
        events.append("lazy:init")
        return "lazy"

    async def close_lazy(value: str) -> None:
        events.append(f"lazy:close:{value}")

    def register_contexts(config, *, instance_role: str) -> None:
        del config, instance_role
        manager.register_context(
            FunctionContextManager("eager", initialize_eager),
        )
        manager.register_context(
            FunctionContextManager(
                "lazy",
                initialize_lazy,
                close_lazy,
            ),
            dependencies=["eager"],
            lazy=True,
        )

    manager._register_default_contexts = register_contexts

    await manager.initialize(object())

    assert events == ["eager:init"]
    assert await manager.async_get_instance("lazy") == "lazy"
    assert await manager.async_get_instance("lazy") == "lazy"
    assert events == ["eager:init", "lazy:init"]

    await manager.async_close()

    assert events == ["eager:init", "lazy:init", "lazy:close:lazy"]
