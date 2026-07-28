from fastapi import FastAPI


def test_dictionary_collection_routes_register_without_trailing_slash():
    from bisheng.dictionary.api.router import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    registered_routes = {(route.path, method) for route in app.routes for method in getattr(route, "methods", set())}

    assert ("/api/v1/dictionaries", "GET") in registered_routes
    assert ("/api/v1/dictionaries", "POST") in registered_routes
