"""F054 T009 — channel article QA registers its source and cites it.

Channel QA does not retrieve: the endpoint fetches one article, truncates it and
drops the whole thing into the prompt. So one article is one source, addressed
by its real doc id — no knowledge-chunk id is ever invented for it (AC-02), and
there is nothing finer to point at.

Two things here are easy to get wrong and are pinned deliberately:

- The prompt must carry the citation rules. The channel's default system prompt
  is a single English sentence with no rule text at all, so without the append
  the model never emits a marker and the whole feature is inert. The append is
  idempotent so an admin prompt that already teaches the markers is not given
  them twice.
- Persistence must be strict. The shared helper the retrieval entries use falls
  back to storing *every* registered item when the answer contains no marker —
  sensible when a search ran, wrong here, because an article source is
  registered on every single turn. With that fallback a turn the model never
  cited would still write a row, and the reader would see a stored source with
  no badge to click (design §3 decision 4).

**Interface note (found while wiring T010).** The scrub and the save are two
calls, not one. Binding citations needs the stored answer's row id, but the
answer must be *cleaned before* it is stored — a single "persist" taking a
message id would force the endpoint to store the raw answer first and leave
hallucinated markers in the database. So: `scrub_article_answer` returns the
cleaned answer plus what to keep, the row is inserted, then
`save_article_citations` binds to its id.

RED until T010 lands.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bisheng.channel.domain.services.channel_chat_service import ChannelChatService
from bisheng.citation.domain.schemas.citation_schema import CitationType
from bisheng.citation.domain.services.citation_prompt_helper import (
    CITATION_END_MARKER,
    CITATION_PROMPT_RULES,
    CITATION_START_MARKER,
    ensure_citation_rules,
)

DEFAULT_SYSTEM_PROMPT = "You are a professional AI assistant helping users analyze and discuss articles."


def _article():
    return SimpleNamespace(
        doc_id="doc-9",
        title="一篇文章",
        content="文章正文" * 10,
        source_url="https://example.com/post",
        source_type=0,
    )


def _marker(citation_key: str) -> str:
    return CITATION_START_MARKER + citation_key + CITATION_END_MARKER


# --------------------------------------------------------------------------- #
# Registration — AC-01, AC-02
# --------------------------------------------------------------------------- #


async def test_registers_one_source_carrying_the_real_article_locator():
    article = _article()

    with patch(
        "bisheng.channel.domain.services.channel_chat_service.cache_citation_registry_items",
        new=AsyncMock(),
    ):
        citation_key, items = await ChannelChatService.register_article_citation(article)

    assert len(items) == 1
    item = items[0]
    assert item.type == CitationType.ARTICLE
    assert item.citationId.startswith("articlesearch_")
    assert item.sourcePayload.articleDocId == "doc-9"
    assert item.sourcePayload.title == "一篇文章"
    assert item.sourcePayload.sourceUrl == "https://example.com/post"
    assert citation_key == f"{item.citationId}:{item.itemId}"


async def test_registration_never_synthesises_a_knowledge_chunk_id():
    """AC-02: the locator is the article's own doc id, not a fabricated chunk."""
    with patch(
        "bisheng.channel.domain.services.channel_chat_service.cache_citation_registry_items",
        new=AsyncMock(),
    ):
        citation_key, items = await ChannelChatService.register_article_citation(_article())

    assert "knowledgesearch_" not in citation_key
    assert items[0].sourcePayload.articleDocId == "doc-9"


async def test_registration_caches_the_item_for_later_resolve():
    cache = AsyncMock()
    with patch("bisheng.channel.domain.services.channel_chat_service.cache_citation_registry_items", new=cache):
        _, items = await ChannelChatService.register_article_citation(_article())

    cache.assert_awaited_once()
    assert cache.await_args.args[0] == items


# --------------------------------------------------------------------------- #
# Prompt — AC-03
# --------------------------------------------------------------------------- #


def test_citation_rules_are_appended_to_the_default_system_prompt():
    """The channel default prompt teaches no markers, so without this the model
    never emits one and no badge can ever appear."""
    prompt = ensure_citation_rules(DEFAULT_SYSTEM_PROMPT)

    assert prompt.startswith(DEFAULT_SYSTEM_PROMPT)
    assert CITATION_PROMPT_RULES in prompt


def test_citation_rules_are_not_appended_twice():
    """An admin prompt that already teaches the markers is left alone."""
    already = DEFAULT_SYSTEM_PROMPT + "\n" + CITATION_PROMPT_RULES

    assert ensure_citation_rules(already) == already


def test_citation_rules_are_appended_to_a_custom_admin_prompt_too():
    custom = "你是某频道的专属助手。"

    prompt = ensure_citation_rules(custom)

    assert prompt.startswith(custom)
    assert CITATION_PROMPT_RULES in prompt


def test_article_context_prompt_carries_the_citation_key():
    prompt = ChannelChatService.build_article_context_prompt(
        title="一篇文章", content="正文", question="问题", citation_key="articlesearch_ab12cd34:0"
    )

    assert "articlesearch_ab12cd34:0" in prompt
    assert "正文" in prompt
    assert "问题" in prompt


# --------------------------------------------------------------------------- #
# Persistence — AC-06, AC-19
# --------------------------------------------------------------------------- #


async def test_only_a_cited_source_is_kept():
    with patch(
        "bisheng.channel.domain.services.channel_chat_service.cache_citation_registry_items",
        new=AsyncMock(),
    ):
        citation_key, items = await ChannelChatService.register_article_citation(_article())
    answer = "文章说了这个。" + _marker(citation_key)

    scrubbed, cited = ChannelChatService.scrub_article_answer(answer, items)

    assert [i.citationId for i in cited] == [items[0].citationId]
    assert scrubbed == answer


async def test_an_uncited_turn_keeps_nothing():
    """The shared helper would fall back to keeping everything here; the article
    path must not, or every turn leaves a source with no badge behind it."""
    with patch(
        "bisheng.channel.domain.services.channel_chat_service.cache_citation_registry_items",
        new=AsyncMock(),
    ):
        _, items = await ChannelChatService.register_article_citation(_article())

    scrubbed, cited = ChannelChatService.scrub_article_answer("模型自己答的，没引用文章。", items)

    assert cited == []
    assert scrubbed == "模型自己答的，没引用文章。"


async def test_nothing_is_written_when_no_source_was_cited():
    save = AsyncMock()

    with patch("bisheng.channel.domain.services.channel_chat_service.save_message_citations", new=save):
        await ChannelChatService.save_article_citations([], message_id=77, chat_id="chat-1", flow_id="doc-9")

    save.assert_not_awaited()


async def test_cited_sources_bind_to_the_stored_answer_row():
    with patch(
        "bisheng.channel.domain.services.channel_chat_service.cache_citation_registry_items",
        new=AsyncMock(),
    ):
        _, items = await ChannelChatService.register_article_citation(_article())
    save = AsyncMock()

    with patch("bisheng.channel.domain.services.channel_chat_service.save_message_citations", new=save):
        await ChannelChatService.save_article_citations(items, message_id=77, chat_id="chat-1", flow_id="doc-9")

    save.assert_awaited_once()
    assert save.await_args.kwargs["message_id"] == 77
    assert [i.citationId for i in save.await_args.kwargs["items"]] == [items[0].citationId]


async def test_a_marker_the_registry_cannot_back_is_scrubbed_before_storage():
    """A hallucinated id would otherwise be stored and then render as a badge
    whose lookup 404s, reading as a system fault rather than the model inventing
    an id. Scrubbing happens before the insert, so it never reaches the row."""
    with patch(
        "bisheng.channel.domain.services.channel_chat_service.cache_citation_registry_items",
        new=AsyncMock(),
    ):
        citation_key, items = await ChannelChatService.register_article_citation(_article())
    answer = "真的。" + _marker(citation_key) + "编的。" + _marker("articlesearch_deadbeef:0")

    scrubbed, cited = ChannelChatService.scrub_article_answer(answer, items)

    assert "articlesearch_deadbeef" not in scrubbed
    assert citation_key in scrubbed
    assert [i.citationId for i in cited] == [items[0].citationId]


async def test_repeating_the_same_turn_is_idempotent():
    with patch(
        "bisheng.channel.domain.services.channel_chat_service.cache_citation_registry_items",
        new=AsyncMock(),
    ):
        _, items = await ChannelChatService.register_article_citation(_article())
    save = AsyncMock()

    with patch("bisheng.channel.domain.services.channel_chat_service.save_message_citations", new=save):
        for _ in range(2):
            await ChannelChatService.save_article_citations(items, message_id=77, chat_id="chat-1", flow_id="doc-9")

    # Same message id and same citation id both times; the unique constraint on
    # message_citation makes the second write a no-op rather than a duplicate.
    assert {call.kwargs["message_id"] for call in save.await_args_list} == {77}
    assert {call.kwargs["items"][0].citationId for call in save.await_args_list} == {items[0].citationId}


# --------------------------------------------------------------------------- #
# Never break the answer — AC-19
# --------------------------------------------------------------------------- #


async def test_registration_failure_degrades_to_no_citation():
    """Tracing is an add-on. If registering the source throws, the turn still
    answers — just without a badge."""
    with patch(
        "bisheng.channel.domain.services.channel_chat_service.cache_citation_registry_items",
        new=AsyncMock(side_effect=RuntimeError("redis down")),
    ):
        citation_key, items = await ChannelChatService.register_article_citation(_article())

    assert citation_key == ""
    assert items == []


async def test_persist_failure_does_not_raise():
    """The answer is already stored by this point; losing its citations must not
    turn a delivered answer into an error."""
    with patch(
        "bisheng.channel.domain.services.channel_chat_service.cache_citation_registry_items",
        new=AsyncMock(),
    ):
        _, items = await ChannelChatService.register_article_citation(_article())

    with patch(
        "bisheng.channel.domain.services.channel_chat_service.save_message_citations",
        new=AsyncMock(side_effect=RuntimeError("db down")),
    ):
        await ChannelChatService.save_article_citations(items, message_id=77, chat_id="chat-1", flow_id="doc-9")


def test_prompt_building_without_a_citation_key_is_unchanged():
    """Degraded path: registration failed, so the prompt carries no key and the
    model simply has nothing to cite."""
    prompt = ChannelChatService.build_article_context_prompt(
        title="一篇文章", content="正文", question="问题", citation_key=""
    )

    assert "articlesearch_" not in prompt
    assert "正文" in prompt
