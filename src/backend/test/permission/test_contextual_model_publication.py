"""Publication must not activate historical, permanently stored context facts."""

from unittest.mock import AsyncMock

import pytest

from bisheng.core.openfga.client import FGAClient
from scripts.publish_authorization_model_change import (
    AuthorizationModelPublishBlockedError,
    _assert_no_persisted_department_context,
)


@pytest.mark.parametrize("persisted_context", [False, True])
async def test_publication_scans_every_page_and_keeps_userset_grants(persisted_context):
    client = FGAClient("http://localhost", "isolated-store", "old-model")
    first = {"user": "department:1#subtree_member", "relation": "subject", "object": "permission_grant:1"}
    last = {"user": "user:1", "relation": "subtree_member" if persisted_context else "member", "object": "department:1"}
    client._post = AsyncMock(
        side_effect=[
            {"tuples": [{"key": first}], "continuation_token": "next"},
            {"tuples": [{"key": last}]},
        ]
    )
    try:
        if persisted_context:
            with pytest.raises(AuthorizationModelPublishBlockedError, match="persisted"):
                await _assert_no_persisted_department_context(client)
        else:
            await _assert_no_persisted_department_context(client)
        assert client._post.await_count == 2
        assert client._post.call_args.args[1]["continuation_token"] == "next"
        assert all(call.args[0].endswith("/read") for call in client._post.call_args_list)
    finally:
        await client.close()
