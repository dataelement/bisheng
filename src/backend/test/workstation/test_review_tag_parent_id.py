"""Unit tests for review-tag resource_files parent_id parsing."""

from bisheng.workstation.domain.repositories.review_tags_repository import ReviewTagsRepositoryImpl


def test_parent_folder_id_from_level_path_root():
    assert ReviewTagsRepositoryImpl._parent_folder_id_from_level_path(None) is None
    assert ReviewTagsRepositoryImpl._parent_folder_id_from_level_path("") is None
    assert ReviewTagsRepositoryImpl._parent_folder_id_from_level_path("/") is None


def test_parent_folder_id_from_level_path_nested():
    assert ReviewTagsRepositoryImpl._parent_folder_id_from_level_path("101") == 101
    assert ReviewTagsRepositoryImpl._parent_folder_id_from_level_path("10/20/30") == 30
    assert ReviewTagsRepositoryImpl._parent_folder_id_from_level_path("/10/20/") == 20
