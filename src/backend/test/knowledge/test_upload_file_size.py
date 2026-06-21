from unittest.mock import patch

import pytest

from bisheng.common.errcode.knowledge_space import SpaceFileSizeLimitError
from bisheng.knowledge.domain import upload_file_size as module


class TestKnowledgeUploadFileSize:
    def test_media_extension_uses_media_limit(self):
        with patch.object(module.settings, 'get_from_db', return_value={
            'uploaded_files_maximum_size': 50,
            'uploaded_media_maximum_size': 1024,
        }):
            assert module.get_max_upload_bytes('clip.mp4') == 1024 * 1024 * 1024
            assert module.get_max_upload_bytes('note.pdf') == 50 * 1024 * 1024

    def test_validate_rejects_oversized_document(self):
        with patch.object(module.settings, 'get_from_db', return_value={
            'uploaded_files_maximum_size': 50,
            'uploaded_media_maximum_size': 1024,
        }):
            with pytest.raises(SpaceFileSizeLimitError):
                module.validate_knowledge_upload_file_size('note.pdf', 51 * 1024 * 1024)

    def test_validate_allows_media_up_to_media_limit(self):
        with patch.object(module.settings, 'get_from_db', return_value={
            'uploaded_files_maximum_size': 50,
            'uploaded_media_maximum_size': 1024,
        }):
            module.validate_knowledge_upload_file_size('clip.mp4', 1024 * 1024 * 1024)

    def test_validate_rejects_oversized_media(self):
        with patch.object(module.settings, 'get_from_db', return_value={
            'uploaded_files_maximum_size': 50,
            'uploaded_media_maximum_size': 1024,
        }):
            with pytest.raises(SpaceFileSizeLimitError):
                module.validate_knowledge_upload_file_size('clip.mp4', 1024 * 1024 * 1024 + 1)
