"""AC-R9 live regression, opt-in on a dedicated deployment with speech models.

Set F053_VOICE_E2E=1, E2E_API_BASE and F053_E2E_WORKFLOW_ID /
F053_E2E_ASSISTANT_ID. ASR also requires F053_VOICE_E2E_AUDIO_FILE pointing
to a short, non-sensitive test recording. No accounts, apps or configuration
are created or changed; synthesized audio uses the existing temporary storage.
"""

import os
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from test.e2e.helpers.api import API_BASE, assert_resp_200, assert_resp_error

pytestmark = pytest.mark.skipif(
    os.environ.get("F053_VOICE_E2E") != "1",
    reason="set F053_VOICE_E2E=1 only on a dedicated voice test deployment",
)
VOICE_URL = f"{API_BASE.removesuffix('/api/v1')}/api/v3/llm/workbench"


@pytest.fixture
async def voice_client():
    async with httpx.AsyncClient(timeout=60) as client:
        yield client


@pytest.fixture(params=["F053_E2E_WORKFLOW_ID", "F053_E2E_ASSISTANT_ID"])
def published_app_id(request):
    resource_id = os.environ.get(request.param, "")
    if not resource_id:
        pytest.skip(f"set {request.param} to test this application type")
    return resource_id


async def test_public_voice_config(voice_client, published_app_id):
    """AC-R9: A fresh client loads only public speech references without credentials."""
    response = await voice_client.get(VOICE_URL, params={"flow_id": published_app_id})
    data = assert_resp_200(response)
    assert response.json()["status_message"] == "SUCCESS"
    assert set(data) == {"asr_model", "tts_model"}
    assert all(set(model) == {"id"} for model in data.values())


async def test_public_speech_recognition(voice_client, published_app_id):
    """AC-R9: The anonymous published application can transcribe a recording."""
    audio_path = os.environ.get("F053_VOICE_E2E_AUDIO_FILE", "")
    if not audio_path:
        pytest.skip("set F053_VOICE_E2E_AUDIO_FILE to a test recording")
    path = Path(audio_path)
    with path.open("rb") as audio:
        response = await voice_client.post(
            f"{VOICE_URL}/asr",
            params={"flow_id": published_app_id},
            files={"file": (path.name, audio, "audio/wav")},
        )
    assert isinstance(assert_resp_200(response), str)
    assert response.json()["status_message"] == "SUCCESS"


async def test_public_speech_synthesis(voice_client, published_app_id):
    """AC-R9: Anonymous synthesis returns an audio URL."""
    response = await voice_client.post(
        f"{VOICE_URL}/tts",
        params={"flow_id": published_app_id},
        json={"text": "This is a published application speech test."},
    )
    audio_url = assert_resp_200(response)
    assert response.json()["status_message"] == "SUCCESS"
    assert isinstance(audio_url, str) and audio_url


@pytest.mark.parametrize("operation", ["config", "asr", "tts"])
async def test_unknown_application_cannot_use_speech(voice_client, operation):
    """AC-R9: An unknown publication cannot expose configuration or call a model."""
    params = {"flow_id": uuid4().hex}
    if operation == "config":
        response = await voice_client.get(VOICE_URL, params=params)
    elif operation == "asr":
        response = await voice_client.post(
            f"{VOICE_URL}/asr",
            params=params,
            files={"file": ("empty.wav", b"", "audio/wav")},
        )
    else:
        response = await voice_client.post(f"{VOICE_URL}/tts", params=params, json={"text": "test"})
    assert response.status_code == 404
    assert_resp_error(response, 404)
