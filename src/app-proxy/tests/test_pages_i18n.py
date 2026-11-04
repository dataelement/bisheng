"""The fallback pages in three languages, and the role they name.

Two properties are pinned here that nothing else in the repo can check:

* **Parity.** These strings sit outside ``packages/locales``, so
  ``pnpm check-i18n`` never sees them. This file is the substitute: every
  locale must declare every page, or a visitor with an English browser gets a
  Chinese page (or a ``KeyError``) at exactly the moment the platform is
  already refusing them.
* **No tenant vocabulary.** ``multi_tenant.enabled`` defaults to *false*, so a
  standard install is single-tenant: ``tenant_admin`` resolves to the platform
  super admin and Root may not be granted one at all (19204). app-proxy is a
  separate process that cannot read the switch — ``grep multi_tenant`` over this
  package finds nothing — so the copy has to be true in both shapes rather than
  branch on a flag it will never see.
"""

from __future__ import annotations

import re

import pytest

from app_proxy.pages import (
    _COPY,
    _LAYOUT,
    DEFAULT_LOCALE,
    LOCALE_EN,
    LOCALE_JA,
    LOCALE_ZH,
    negotiate_locale,
    render_page,
)
from tests.conftest import NAVIGATE_HEADERS, XHR_HEADERS
from tests.fakes import deny_response

ALL_KINDS = sorted(_LAYOUT)


def _paragraphs(page: str) -> list[str]:
    """The visible copy of a rendered page, tags and indentation removed."""
    body = page.split("<body>", 1)[1]
    return [re.sub(r"<[^>]+>", "", line).strip() for line in body.splitlines() if "<p>" in line]


class TestLocaleParity:
    def test_every_locale_declares_every_page(self):
        assert sorted(_COPY) == sorted([LOCALE_ZH, LOCALE_EN, LOCALE_JA])
        for locale, bundle in _COPY.items():
            assert sorted(bundle) == ALL_KINDS, f"{locale} is missing a page"

    @pytest.mark.parametrize("locale", [LOCALE_ZH, LOCALE_EN, LOCALE_JA])
    @pytest.mark.parametrize("kind", ALL_KINDS)
    def test_every_page_renders_in_every_locale(self, locale, kind):
        """Placeholders included: a stray ``{app}`` in one bundle only shows up
        in the language nobody on the team reads."""
        header = {LOCALE_ZH: "zh-CN", LOCALE_EN: "en-US", LOCALE_JA: "ja-JP"}[locale]
        body = render_page(kind, app_name="问卷小助手", owner_name="李四", accept_language=header)

        assert _COPY[locale][kind].title in body
        assert "{app}" not in body and "{owner}" not in body

    @pytest.mark.parametrize("locale", [LOCALE_ZH, LOCALE_EN, LOCALE_JA])
    @pytest.mark.parametrize("kind", ALL_KINDS)
    def test_unknown_names_degrade_without_a_gap(self, locale, kind):
        """No app name and no owner is the ordinary not-found / deleted-account
        case, not an error path.

        The stand-in goes into the same slot as a real name, so the sentence has
        to survive both. A double space is the tell that the line was written
        assuming a name would always be there.
        """
        header = {LOCALE_ZH: "zh", LOCALE_EN: "en", LOCALE_JA: "ja"}[locale]
        page = render_page(kind, accept_language=header)

        assert "{app}" not in page and "{owner}" not in page
        for line in _paragraphs(page):
            assert "  " not in line, f"{locale}/{kind}: a missing name left a gap in {line!r}"
            assert not line.startswith(" ") and not line.endswith(" ")


class TestNoTenantVocabulary:
    @pytest.mark.parametrize("locale", [LOCALE_ZH, LOCALE_EN, LOCALE_JA])
    @pytest.mark.parametrize("kind", ALL_KINDS)
    def test_no_page_names_a_tenant_administrator(self, locale, kind):
        for line in (_COPY[locale][kind].title, *_COPY[locale][kind].lines):
            assert "租户" not in line
            assert "tenant" not in line.lower()
            assert "テナント" not in line


class TestNegotiation:
    @pytest.mark.parametrize(
        ("header", "expected"),
        [
            ("zh-CN,zh;q=0.9", LOCALE_ZH),
            ("zh-Hant-TW", LOCALE_ZH),
            ("en-US,en;q=0.9", LOCALE_EN),
            ("ja", LOCALE_JA),
            ("EN-GB", LOCALE_EN),
            # Highest q wins regardless of the order it was written in.
            ("en;q=0.4,ja;q=0.9", LOCALE_JA),
            # q=0 is an explicit refusal, so the next acceptable one is used.
            ("en;q=0,ja", LOCALE_JA),
            # Nothing we ship, and nothing at all, fall back rather than crash.
            ("de-DE,de;q=0.8", DEFAULT_LOCALE),
            ("*", DEFAULT_LOCALE),
            ("", DEFAULT_LOCALE),
            (None, DEFAULT_LOCALE),
            (";;;q=", DEFAULT_LOCALE),
            ("en;q=not-a-number", DEFAULT_LOCALE),
        ],
    )
    def test_header_picks_the_bundle(self, header, expected):
        assert negotiate_locale(header) == expected

    def test_html_lang_follows_the_bundle(self):
        assert 'lang="en"' in render_page("forbidden", accept_language="en")
        assert 'lang="ja"' in render_page("forbidden", accept_language="ja")
        assert 'lang="zh-CN"' in render_page("forbidden", accept_language="zh-CN")


class TestEndToEnd:
    def test_english_browser_gets_the_english_page(self, logged_in, fake_backend):
        fake_backend.response = deny_response("forbidden", app_name="Survey Helper", owner_name="Li Si")
        response = logged_in.get("/apps/foo", headers={**NAVIGATE_HEADERS, "Accept-Language": "en-US,en;q=0.9"})

        assert response.status_code == 200
        assert "No access" in response.text
        assert "platform administrator" in response.text
        assert "无访问权限" not in response.text

    def test_japanese_browser_gets_the_japanese_page(self, logged_in, fake_backend):
        fake_backend.response = deny_response("stopped", app_state="stopped")
        body = logged_in.get("/apps/foo", headers={**NAVIGATE_HEADERS, "Accept-Language": "ja,en;q=0.5"}).text

        assert "停止中" in body
        assert "プラットフォーム管理者" in body

    def test_no_accept_language_stays_chinese(self, logged_in, fake_backend):
        fake_backend.response = deny_response("forbidden")
        assert "无访问权限" in logged_in.get("/apps/foo", headers=NAVIGATE_HEADERS).text

    def test_json_status_message_is_localised_too(self, logged_in, fake_backend):
        """An in-app ``fetch()`` surfaces this string to the same person."""
        fake_backend.response = deny_response("forbidden")
        response = logged_in.get("/apps/foo/api/data", headers={**XHR_HEADERS, "Accept-Language": "en"})

        assert response.json()["status_message"] == "No access"
        assert response.json()["status_code"] == 16142

    def test_recovering_page_is_localised(self, logged_in, upstream_transport):
        from tests.fakes import DEFAULT_UPSTREAM

        upstream_transport.refuse.add(DEFAULT_UPSTREAM)
        body = logged_in.get("/apps/foo", headers={**NAVIGATE_HEADERS, "Accept-Language": "en"}).text
        assert "restarting" in body
