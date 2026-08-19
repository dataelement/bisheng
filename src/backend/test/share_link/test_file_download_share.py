"""A share recipient must be able to open the task's deliverables.

``file_download`` is what turns a workspace object key into a presigned link, so
every preview, inline deliverable image and download on a share page goes
through it. It accepted only a ``linsight_session`` share (``meta_data.versionId``
pinned to this version); a ``workbench_chat`` share carries ``resource_id`` = the
session and no versionId, so a recipient 403'd the moment they opened any
produced file — which the client's global 403 handler turns into a whole-page
bounce to ``/c/new?error=11403``, reading as "this share link has no permission".

``session-version-list`` / ``execute-task-detail`` already accepted both shapes;
this pins the same grant on the third endpoint behind a share page.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestFileDownloadHonoursAWholeConversationShare:
    SESSION_ID = "conv-shared"
    VERSION_ID = "sv-1"

    @pytest.fixture()
    def endpoints(self, monkeypatch):
        from bisheng.linsight.api.endpoints import linsight as linsight_endpoints

        version = MagicMock()
        version.user_id = 1  # the owner
        version.session_id = self.SESSION_ID
        dao = MagicMock()
        dao.get_by_id = AsyncMock(return_value=version)
        monkeypatch.setattr(linsight_endpoints, "LinsightSessionVersionDao", dao)

        minio = MagicMock()
        minio.bucket = "bisheng"
        minio.get_share_link = AsyncMock(return_value="/bisheng/presigned?sig=x")
        monkeypatch.setattr(linsight_endpoints, "get_minio_storage", AsyncMock(return_value=minio))
        return linsight_endpoints

    @staticmethod
    def _reader():
        reader = MagicMock()
        reader.user_id = 999  # neither the owner nor an admin
        reader.is_admin.return_value = False
        return reader

    @staticmethod
    def _whole_conversation_share(resource_id: str):
        """A `workbench_chat` share: resource_id is the session, no versionId."""
        share_link = MagicMock()
        share_link.resource_id = resource_id
        share_link.meta_data = {"flowId": ""}
        return share_link

    def _single_version_share(self, version_id: str):
        """A `linsight_session` share: meta_data pins one version."""
        share_link = MagicMock()
        share_link.resource_id = "some-other-resource"
        share_link.meta_data = {"versionId": version_id}
        return share_link

    async def _download(self, endpoints, share_link):
        return await endpoints.linsight_file_download(
            file_url="linsight/final_result/sv-1/report.md",
            session_version_id=self.VERSION_ID,
            login_user=self._reader(),
            share_link=share_link,
        )

    async def test_whole_conversation_share_grants_the_download(self, endpoints):
        result = await self._download(endpoints, self._whole_conversation_share(self.SESSION_ID))

        assert result.status_code == 200
        assert result.data == {"file_path": "/bisheng/presigned?sig=x"}

    async def test_single_version_share_still_grants_the_download(self, endpoints):
        result = await self._download(endpoints, self._single_version_share(self.VERSION_ID))

        assert result.status_code == 200

    async def test_missing_token_is_still_rejected(self, endpoints):
        from bisheng.common.errcode.http_error import UnAuthorizedError

        with pytest.raises(UnAuthorizedError):
            await self._download(endpoints, None)

    async def test_token_for_another_conversation_is_still_rejected(self, endpoints):
        from bisheng.common.errcode.http_error import UnAuthorizedError

        with pytest.raises(UnAuthorizedError):
            await self._download(endpoints, self._whole_conversation_share("conv-not-shared"))
