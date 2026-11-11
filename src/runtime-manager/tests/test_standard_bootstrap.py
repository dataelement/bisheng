"""Formal commands: scoped data key publication and Service DNS, no live cluster."""

import socket

import httpx
import pytest

from runtime_manager.bootstrap_keys import public_document, publish
from runtime_manager.k8s_boot import resolve_proxy


def test_dns_resolution_keeps_application_no_dns_and_rejects_local_targets():
    def resolver(host, port, **kwargs):
        assert host == "proxy.control.svc" and port == 3128
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.96.0.9", 3128))]

    assert resolve_proxy("proxy.control.svc:3128", resolver=resolver) == "10.96.0.9:3128"
    for value in ("127.0.0.1:3128", "0.0.0.0:3128", "169.254.1.1:3128", "host:not-a-port"):
        with pytest.raises(ValueError):
            resolve_proxy(value)


def test_key_publication_is_idempotent_scoped_and_never_rotates():
    document = public_document(b"a" * 32)
    obj = {"metadata": {"resourceVersion": "1", "labels": {"runtime.bisheng.io/installation": "test"}}, "data": {}}
    patches = []

    def request(req):
        import json

        assert req.url.path == "/api/v1/namespaces/apps/configmaps/data-keys"
        if req.method == "GET":
            return httpx.Response(200, json=obj)
        body = json.loads(req.content)
        patches.append(body)
        obj["data"] = body["data"]
        return httpx.Response(200, json=obj)

    with httpx.Client(base_url="https://kubernetes.invalid", transport=httpx.MockTransport(request)) as client:
        publish(client, "apps", "data-keys", "test", document)
        publish(client, "apps", "data-keys", "test", document)
        assert len(patches) == 1 and patches[0]["metadata"]["resourceVersion"] == "1"
        with pytest.raises(ValueError, match="content_mismatch"):
            publish(client, "apps", "data-keys", "test", public_document(b"b" * 32))
        with pytest.raises(ValueError, match="ownership"):
            publish(client, "apps", "data-keys", "foreign", document)
