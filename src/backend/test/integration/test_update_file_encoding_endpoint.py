"""Integration tests for PUT /api/v1/knowledge/space/{sid}/files/{fid}/encoding.

NOTE: requires a running DB and FastAPI test client. Skipped automatically when
the necessary fixtures aren't available. Intended to be run by the user after
DB env is set up.
"""
import pytest


pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_update_file_encoding_success(authenticated_owner_client, sample_space_with_file):
    space_id = sample_space_with_file["space_id"]
    file_id = sample_space_with_file["file_id"]
    resp = await authenticated_owner_client.put(
        f"/api/v1/knowledge/space/{space_id}/files/{file_id}/encoding",
        json={"encoding": "MY-CUSTOM-CODE-001"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status_code"] == 200
    assert body["data"]["file_encoding"] == "MY-CUSTOM-CODE-001"


@pytest.mark.asyncio
async def test_update_file_encoding_rejects_empty(authenticated_owner_client, sample_space_with_file):
    space_id = sample_space_with_file["space_id"]
    file_id = sample_space_with_file["file_id"]
    resp = await authenticated_owner_client.put(
        f"/api/v1/knowledge/space/{space_id}/files/{file_id}/encoding",
        json={"encoding": ""},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_file_encoding_rejects_too_long(authenticated_owner_client, sample_space_with_file):
    space_id = sample_space_with_file["space_id"]
    file_id = sample_space_with_file["file_id"]
    resp = await authenticated_owner_client.put(
        f"/api/v1/knowledge/space/{space_id}/files/{file_id}/encoding",
        json={"encoding": "X" * 65},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_file_encoding_denies_non_owner(authenticated_member_client, sample_space_with_file):
    space_id = sample_space_with_file["space_id"]
    file_id = sample_space_with_file["file_id"]
    resp = await authenticated_member_client.put(
        f"/api/v1/knowledge/space/{space_id}/files/{file_id}/encoding",
        json={"encoding": "ABC-123"},
    )
    assert resp.status_code in (403, 200)
    if resp.status_code == 200:
        body = resp.json()
        assert body["status_code"] != 200, "expected permission error in response body"


@pytest.mark.asyncio
async def test_update_file_encoding_404_for_unknown_file(authenticated_owner_client, sample_space_with_file):
    space_id = sample_space_with_file["space_id"]
    resp = await authenticated_owner_client.put(
        f"/api/v1/knowledge/space/{space_id}/files/999999999/encoding",
        json={"encoding": "ABC-123"},
    )
    assert resp.status_code in (404, 200)
    if resp.status_code == 200:
        body = resp.json()
        assert body["status_code"] != 200
