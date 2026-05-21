"""Tests for the version_management config schema in KnowledgeConf."""
from bisheng.core.config.settings import KnowledgeConf, VersionManagementConf


def test_version_management_default_values():
    conf = KnowledgeConf()
    assert conf.version_management.enabled is False
    assert conf.version_management.simhash_similarity_threshold == 0.85


def test_version_management_explicit_values():
    conf = KnowledgeConf(version_management={"enabled": True, "simhash_similarity_threshold": 0.9})
    assert conf.version_management.enabled is True
    assert conf.version_management.simhash_similarity_threshold == 0.9


def test_version_management_conf_standalone():
    vmc = VersionManagementConf()
    assert vmc.enabled is False
    assert vmc.simhash_similarity_threshold == 0.85
