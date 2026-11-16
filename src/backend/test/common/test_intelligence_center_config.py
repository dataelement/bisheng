"""Read hot configuration without revalidating decrypted infrastructure URLs."""

import ast
import inspect
from pathlib import Path

import pytest
from pydantic import ValidationError

from bisheng.core.config.settings import IntelligenceCenterConf, Settings, encrypt_token


@pytest.fixture(params=["get_intelligence_center_conf", "aget_intelligence_center_conf"])
def reader(request):
    # Compile the actual getters with real Settings validation, avoiding the
    # global config_service import that initializes infrastructure.
    path = Path(__file__).parents[2] / "bisheng/common/services/config_service.py"
    tree = ast.parse(path.read_text())
    service = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ConfigService")
    methods = [
        node
        for node in service.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in {"get_intelligence_center_conf", "aget_intelligence_center_conf"}
    ]
    namespace = {"Settings": Settings, "IntelligenceCenterConf": IntelligenceCenterConf}
    isolated = ast.ClassDef(
        name="ConfigService",
        bases=[ast.Name(id="Settings", ctx=ast.Load())],
        keywords=[],
        body=methods,
        decorator_list=[],
    )
    exec(compile(ast.fix_missing_locations(ast.Module(body=[isolated], type_ignores=[])), str(path), "exec"), namespace)
    service_class = namespace["ConfigService"]
    db_config = {}

    async def aget_all_config():
        return db_config

    service_class.get_all_config = staticmethod(lambda: db_config)
    service_class.aget_all_config = staticmethod(aget_all_config)

    async def read(service):
        result = getattr(service, request.param)()
        return await result if inspect.isawaitable(result) else result

    return service_class, db_config, read


@pytest.mark.parametrize("url_field", ["redis_url", "celery_redis_url"])
async def test_hot_reload_does_not_redecrypt_urls_or_replace_boot_config(reader, url_field):
    service_class, db_config, read = reader
    token = encrypt_token("demo-only").decode()
    service = service_class(
        **{
            "redis_url": "redis://redis:6379/1",
            "celery_redis_url": "redis://redis:6379/2",
            url_field: f"redis://:{token}@redis:6379/2",
        },
        information_conf={"base_url": "http://boot.invalid"},
    )
    boot_conf = service.information_conf
    urls = (service.redis_url, service.celery_redis_url)
    db_config["information_conf"] = {"base_url": "http://first.invalid"}
    assert (await read(service)).base_url == "http://first.invalid"

    db_config["information_conf"] = {"base_url": "http://second.invalid"}
    assert (await read(service)).base_url == "http://second.invalid"
    assert service.information_conf is boot_conf
    assert (service.redis_url, service.celery_redis_url) == urls

    db_config.clear()
    assert await read(service) is boot_conf


@pytest.mark.parametrize("db_config_value", [None, {}])
async def test_empty_db_config_uses_boot_config(reader, db_config_value):
    service_class, db_config, read = reader
    service = service_class(information_conf={"base_url": "http://boot.invalid"})
    db_config["information_conf"] = db_config_value
    assert await read(service) is service.information_conf


async def test_invalid_db_config_still_fails_validation(reader):
    service_class, db_config, read = reader
    service = service_class()
    db_config["information_conf"] = {"information_initial_article_limit": 0}
    with pytest.raises(ValidationError):
        await read(service)
