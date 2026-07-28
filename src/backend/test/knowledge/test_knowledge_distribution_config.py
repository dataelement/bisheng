from bisheng.core.config.settings import KnowledgeConf


def test_knowledge_distribution_has_no_runtime_switches():
    assert not hasattr(KnowledgeConf(), "distribution")
