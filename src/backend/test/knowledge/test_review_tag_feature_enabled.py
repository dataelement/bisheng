"""待审标签开关: 关闭时必须能解析并抛出 ReviewTagFeatureDisabledError."""

from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.knowledge_space import ReviewTagFeatureDisabledError
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService


@pytest.mark.asyncio
async def test_require_review_tag_feature_raises_imported_error() -> None:
    with patch.object(
        KnowledgeSpaceService,
        "_is_review_tag_feature_enabled",
        new_callable=AsyncMock,
        return_value=False,
    ):
        with pytest.raises(ReviewTagFeatureDisabledError):
            await KnowledgeSpaceService._require_review_tag_feature_enabled()
