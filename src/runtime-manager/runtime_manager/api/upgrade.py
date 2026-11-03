"""Bounded legacy inventory for an authenticated, maintenance-window upgrade."""

import asyncio

from fastapi import APIRouter, Depends

from runtime_manager.api.operations import authorized, executor
from runtime_manager.config import get_config
from runtime_manager.desired_state import get_store

router = APIRouter(prefix="/v2/upgrade", dependencies=[Depends(authorized)])


def inventory():
    service = executor()
    service.heartbeat()
    config = get_config()
    items = []
    for record in get_store(config).list():
        reference = record.container_id or record.container_name
        data = service.docker.inspect_container(reference)
        labels = data.get("Config", {}).get("Labels", {})
        image = service.docker.inspect_image(data["Image"])
        items.append(
            {
                "app_id": record.app_id,
                "version_id": record.version_id,
                "generation": record.generation,
                "desired": record.desired,
                "exec_ref": data["Id"],
                "image_id": image["Id"],
                "platform": image.get("Os", "linux") + "/" + image["Architecture"],
                "running": bool(data.get("State", {}).get("Running")),
                "labels": labels,
                "tier": {"memory_mb": record.tier_mem_mb, "cpu_millicores": int(record.tier_cpu * 1000)},
                "target": {
                    "host": data.get("NetworkSettings", {})
                    .get("Networks", {})
                    .get(config.network, {})
                    .get("IPAddress"),
                    "port": record.port,
                },
                "storage_namespace": "apps/" + record.app_id + "/",
                "storage_bucket": config.storage_bucket,
            }
        )
    return {
        "schema_version": 1,
        "node_id": config.node_id,
        "engine_id": service.docker.info()["ID"],
        "applications": items,
    }


@router.get("/inventory")
async def read_inventory():
    return await asyncio.to_thread(inventory)
