"""Defaults for the knowledge-space QA permission-filter recall loop.

The recall loop fetches ``100 * multiplier`` candidates per attempt. The
expansion multiplier was lowered from 10 (k=1000) to 6 (k=600) to cut the
retry-attempt search cost while still over-recalling enough for the
result-layer ``view_file`` post-filter to leave at least top_k chunks. The
``ef >= k`` guard in the Milvus wrapper keeps these k values valid regardless.
"""

from __future__ import annotations

from bisheng.core.config.settings import KnowledgeQAFilterConf


def test_expansion_multiplier_default_is_six():
    assert KnowledgeQAFilterConf().retrieval_expansion_multiplier == 6


def test_initial_multiplier_default_is_three():
    assert KnowledgeQAFilterConf().retrieval_initial_multiplier == 3


def test_expansion_not_below_initial():
    conf = KnowledgeQAFilterConf()
    assert conf.retrieval_expansion_multiplier >= conf.retrieval_initial_multiplier
