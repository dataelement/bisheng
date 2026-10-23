"""ASGI integration harness: real routes/SQL transactions, injected identity and object storage."""

import base64
import json
import sys
from contextlib import contextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from bisheng.common.errcode.base import BaseErrorCode
from bisheng.dsh_market.api.auth import MarketActor, market_actor, market_admin
from bisheng.dsh_market.api.endpoints import router
from bisheng.dsh_market.domain.repository import MarketRepository
from bisheng.dsh_market.domain.service import MarketService
from bisheng.dsh_market.infrastructure import get_market_service


class ObjectStore:
    def __init__(self):
        self.objects = {}

    def put(self, tenant, digest, data):
        self.objects[tenant, digest] = data

    def get(self, tenant, digest):
        return self.objects[tenant, digest]


engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
SQLModel.metadata.create_all(engine)


@contextmanager
def sessions():
    with Session(engine) as session:
        yield session


service = MarketService(MarketRepository(sessions), ObjectStore())
app = FastAPI()
app.include_router(router, prefix="/api/v1")
app.dependency_overrides[get_market_service] = lambda: service
app.dependency_overrides[market_actor] = lambda: MarketActor(2, 20)
app.dependency_overrides[market_admin] = lambda: MarketActor(2, 20)


@app.exception_handler(BaseErrorCode)
async def error_handler(request, error):
    return JSONResponse(error.to_dict())


with TestClient(app) as client:
    for line in sys.stdin:
        command = json.loads(line)
        try:
            kwargs = {"json": command["body"]} if "body" in command else {}
            if "artifact" in command:
                kwargs = {"files": {"file": ("plugin.zip", base64.b64decode(command["artifact"]), "application/zip")}}
            response = client.request(command["method"], command["path"], **kwargs)
            if response.headers.get("content-type", "").startswith("application/zip"):
                result = {"artifact": base64.b64encode(response.content).decode()}
            else:
                result = response.json()
            print(json.dumps({"id": command["id"], "status": response.status_code, "data": result}), flush=True)
        except Exception as exc:
            print(json.dumps({"id": command["id"], "error": str(exc)}), flush=True)
