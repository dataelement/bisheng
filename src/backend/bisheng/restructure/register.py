from fastapi import FastAPI

from bisheng.restructure.routers import router as router_restructure


def register_restructure(app: FastAPI):
    app.include_router(router_restructure)
