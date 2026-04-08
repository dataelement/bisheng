__all__ = ['router', 'router_rpc']


def __getattr__(name):
    if name in __all__:
        from bisheng.api.router import router, router_rpc

        exports = {
            'router': router,
            'router_rpc': router_rpc,
        }
        return exports[name]
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
