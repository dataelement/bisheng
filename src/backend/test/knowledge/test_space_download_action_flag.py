"""The space detail reports whether downloading is switched on at all.

909 only. This line offers the download button to everyone and lets the server
refuse, because deciding per file costs 43-124ms a page for a permission nearly
everyone holds. That trade breaks down when the Catalog has the action switched
off: nobody can download, so the button only promises a refusal. One Catalog
read per space answers it, which is cheap enough to pay on every detail load.
"""

from __future__ import annotations

from bisheng.knowledge.domain.schemas.knowledge_space_schema import KnowledgeSpaceInfoResp


def test_a_response_without_the_field_still_offers_download():
    """The client hides the button on an explicit false and nothing else.

    A payload from a build that predates the flag must keep the old behaviour,
    or upgrading the client ahead of the server would silently remove downloads
    for everyone.
    """

    resp = KnowledgeSpaceInfoResp(id=1, name="s", user_id=1)

    assert resp.download_action_enabled is True
