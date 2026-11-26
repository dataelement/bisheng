"""AC-49, AC-51, AC-52: opt-in disposable Nginx/API/FGA/object-store retention probe.

Run inside the explicitly disposable backend with its normal mounted config.
Only generated accounts/resources are created. State remains private across
container recreation. No credentials, cookies or signed URLs are printed.
"""

import base64
import json
import os
import secrets
import sys
from pathlib import Path
from urllib.parse import urljoin

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding

from bisheng.core.cache.redis_conn import RedisClient
from bisheng.core.config.credential_artifacts import read_confidential, write_confidential
from bisheng.core.config.credential_loader import load_config, validate_runtime

EXPECTED_OWNER = os.environ.get("BISHENG_ROTATION_EXPECTED_OWNER", "rotation-acceptance-166")

if (
    os.environ.get("BISHENG_ROTATION_BUSINESS_DISPOSABLE") != "true"
    or EXPECTED_OWNER not in {"rotation-acceptance-166", "rotation-acceptance-166-sealed-v2"}
    or Path("/app/data/.credential-acceptance-owner").read_text().strip() != EXPECTED_OWNER
):
    raise SystemExit("explicit disposable fixture ownership required")

ROOT = Path("/app/data/credential-acceptance")
ROOT.mkdir(mode=0o700, exist_ok=True)
STATE = ROOT / "business-state.json"
MODE = sys.argv[1]
BASE = "http://frontend:3001/api/v1"
settings = validate_runtime(load_config("/app/bisheng/config.yaml").data)
state = json.loads(read_confidential(STATE, deployment=EXPECTED_OWNER)) if STATE.exists() else {"nonce": secrets.token_hex(8), "accounts": []}


def save():
    write_confidential(STATE, json.dumps(state).encode(), deployment=EXPECTED_OWNER)


def payload(response, label):
    if response.status_code not in (200, 201) or response.json().get("status_code") != 200:
        detail = ROOT / "last-http.private.json"
        write_confidential(detail, response.content, deployment=EXPECTED_OWNER)
        raise AssertionError("HTTP business operation failed: " + label + " HTTP=" + str(response.status_code))
    return response.json()["data"]


def encrypted(value, key):
    public = serialization.load_pem_public_key(key.encode())
    return base64.b64encode(public.encrypt(value.encode(), padding.PKCS1v15())).decode()


def captcha(client):
    info = payload(client.get(BASE + "/user/get_captcha"), "captcha")
    redis = RedisClient(settings.redis_url)
    try:
        value = redis.get(info["captcha_key"])
    finally:
        redis.close()
    assert value, "own captcha nonce missing"
    return {"captcha_key": info["captcha_key"], "captcha": value.decode() if isinstance(value, bytes) else value}


checks = {}
with httpx.Client(timeout=45, follow_redirects=True) as client:
    assert client.get(BASE + "/user/info").status_code in (401, 403), "anonymous identity access allowed"
    checks["anonymous_denied"] = True
    key = payload(client.get(BASE + "/user/public_key"), "public key")["public_key"]
    if MODE == "verify":
        assert all(k in state for k in ("workflow", "space", "file", "embedding_model", "old_download_url")), (
            "baseline resources missing"
        )
        assert len(state["accounts"]) == 2
    if len(state["accounts"]) < 2:
        for i in range(len(state["accounts"]), 2):
            account = {
                "user_name": "cred" + state["nonce"] + str(i),
                "external_id": "credential-" + state["nonce"] + "-" + str(i),
                "password": secrets.token_urlsafe(24) + "A1@",
            }
            created = payload(
                client.post(
                    BASE + "/user/regist",
                    json={**account, "password": encrypted(account["password"], key), **captcha(client)},
                ),
                "registration",
            )
            account["id"] = created["user_id"]
            state["accounts"].append(account)
            save()
    cookies = []
    for account in state["accounts"]:
        client.cookies.clear()
        data = payload(
            client.post(
                BASE + "/user/login",
                json={
                    "user_name": account["external_id"],
                    "password": encrypted(account["password"], key),
                    **captcha(client),
                },
            ),
            "login",
        )
        cookie = {"access_token_cookie": data["access_token"]}
        profile = payload(client.get(BASE + "/user/info", cookies=cookie), "profile")
        assert profile["user_name"] == account["user_name"], "identity mismatch"
        cookies.append(cookie)
    assert state["accounts"][0]["id"] != state["accounts"][1]["id"]
    checks["admin_and_normal_user_login"] = True
    client.cookies.clear()
    client.cookies.update(cookies[0])
    if MODE == "create":
        payload(client.post(BASE + "/admin/tenant-scope", json={"tenant_id": 1}), "management tenant selection")
    else:
        selected = payload(client.get(BASE + "/admin/tenant-scope"), "retained management tenant")
        assert selected["scope_tenant_id"] == 1, "management preference not retained"
    client.headers["X-Management-Tenant"] = "1"
    if "workflow" not in state:
        workflow = payload(
            client.post(
                BASE + "/workflow/create",
                json={
                    "name": "credential-" + state["nonce"],
                    "description": "disposable credential acceptance",
                    "data": {"nodes": [], "edges": []},
                },
            ),
            "workflow creation",
        )
        state["workflow"] = workflow["id"]
        save()
    workflow = payload(client.get(BASE + "/flows/" + str(state["workflow"])), "workflow read")
    assert workflow["name"] == "credential-" + state["nonce"]
    checks["workflow_metadata_retained"] = True
    if "embedding_model" not in state:
        server = payload(
            client.post(
                BASE + "/llm",
                json={
                    "name": "credential-" + state["nonce"],
                    "type": "openai",
                    "share_to_children": False,
                    "config": {
                        "openai_api_base": f"http://{EXPECTED_OWNER}-embedding:8080/v1",
                        "openai_api_key": "disposable-fixture-only",
                    },
                    "models": [
                        {
                            "name": "credential-embedding",
                            "model_name": "credential-embedding",
                            "model_type": "embedding",
                            "online": True,
                        }
                    ],
                },
            ),
            "embedding fixture configuration",
        )
        state["embedding_model"] = server["models"][0]["id"]
        save()
    if MODE == "create":
        payload(
            client.post(BASE + "/llm/verify", json={"model_id": state["embedding_model"]}),
            "embedding fixture verification",
        )
        payload(
            client.post(
                BASE + "/llm/workbench",
                json={"embedding_model": {"id": str(state["embedding_model"]), "name": "credential-embedding"}},
            ),
            "embedding fixture selection",
        )
    else:
        stored = payload(client.get(BASE + "/llm/workbench/settings"), "retained embedding configuration")
        assert str(stored["data"]["embedding_model"]["id"]) == str(state["embedding_model"])
    if "space" not in state:
        space = payload(
            client.post(
                BASE + "/knowledge/space",
                json={
                    "name": "credential-" + state["nonce"],
                    "auth_type": "private",
                    "creation_request_id": "credential-" + state["nonce"],
                },
            ),
            "space creation",
        )
        state["space"] = space["id"]
        save()
    payload(client.get(BASE + "/knowledge/space/" + str(state["space"]) + "/info"), "space read")
    if "file" not in state:
        uploaded = payload(
            client.post(
                BASE + "/knowledge/upload/" + str(state["space"]),
                files={
                    "file": (
                        "credential-" + state["nonce"] + ".txt",
                        ("credential-content-" + state["nonce"]).encode(),
                        "text/plain",
                    )
                },
            ),
            "file upload",
        )
        files = payload(
            client.post(
                BASE + "/knowledge/space/" + str(state["space"]) + "/files",
                json={"file_path": [uploaded["file_path"]], "preview_upload_refs": [uploaded["preview_upload_ref"]]},
            ),
            "file commit",
        )
        state["file"] = files[0]["id"]
        save()
    urls = payload(
        client.get(BASE + "/knowledge/space/" + str(state["space"]) + "/files/" + str(state["file"]) + "/download"),
        "download link",
    )
    response = client.get(urljoin("http://frontend:3001", urls["original_url"]))
    assert response.status_code == 200 and response.content == ("credential-content-" + state["nonce"]).encode(), (
        "download content mismatch"
    )
    checks["knowledge_upload_download_retained"] = True
    if MODE == "verify" and state.get("old_download_url"):
        old = client.get(urljoin("http://frontend:3001", state["old_download_url"]))
        invalidated = os.environ.get("BISHENG_ACCEPTANCE_EXPECT_SIGNED_URL_INVALIDATION", "true")
        assert invalidated in {"true", "false"}, "explicit signed URL expectation required"
        if invalidated == "true":
            checks["old_signed_url_denied"] = old.status_code in (400, 401, 403)
            assert checks["old_signed_url_denied"], "old signed URL still accepted"
        else:
            checks["old_signed_url_retained"] = old.status_code == 200 and old.content == ("credential-content-" + state["nonce"]).encode()
            assert checks["old_signed_url_retained"], "unchanged credentials invalidated an existing signed URL"
    if MODE == "create":
        state["old_download_url"] = urls["original_url"]
        save()
    retrieved = payload(
        client.post(
            BASE + "/knowledge/space/retrieve",
            json={"query": "credential-content-" + state["nonce"], "space_ids": [state["space"]]},
        ),
        "knowledge retrieval",
    )
    assert any(
        "credential-content-" + state["nonce"] in item["content"] and int(item["space_id"]) == int(state["space"])
        for item in retrieved["chunks"]
    ), "uploaded document not retrieved"
    checks["knowledge_retrieval"] = True
    client.cookies.clear()
    client.cookies.update(cookies[1])
    denied = client.get(BASE + "/flows/" + str(state["workflow"]))
    assert denied.status_code in (401, 403, 404) or denied.json().get("status_code") != 200, "non-owner read allowed"
    checks["non_owner_permission_denied"] = True
result = {"mode": MODE, "checks": checks, "completed": True}
(ROOT / ("business-" + MODE + ".json")).write_text(json.dumps(result, indent=2))
print(json.dumps(result))
