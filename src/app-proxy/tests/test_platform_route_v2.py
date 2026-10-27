"""Platform routing has no manager availability or write-key dependency."""

import httpx

from app_proxy.clients import ManagerRouteClient


async def test_route_is_read_from_backend_with_separate_key():
    calls = []

    def transport(request):
        calls.append(request)
        assert request.headers["X-Runtime-Key-Id"] == "entry-reader"
        assert request.url.path == "/api/v1/internal/app-runtime/v2/routes/apps/app-a"
        return httpx.Response(
            200, json={"decision": "allow", "target": {"host": "172.20.0.2", "port": 8080}, "route_epoch": 3}
        )

    client = ManagerRouteClient(
        "http://backend.test",
        "entry-secret",
        key_id="entry-reader",
        protocol_version=2,
        transport=httpx.MockTransport(transport),
    )
    answer = await client.route("app-a")
    await client.route("app-a")
    await client.aclose()
    assert answer["upstream"] == "http://172.20.0.2:8080" and len(calls) == 1
