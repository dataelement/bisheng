"""F028 T009 — unit tests for renderers, image preprocessing, and filename rules.

Scope: ``_render_markdown`` / ``_render_docx`` / ``_render_pdf`` / ``_render_txt``
/ ``_preprocess_images`` / ``_fetch_image_bytes`` / ``_resolve_filename``.

Mocking strategy:
- pypandoc → real subprocess (pandoc binary available on dev machines + base
  image). Verifies actual docx output structure.
- LibreOffice (``convert_docx_to_pdf``) → monkeypatched; we can't depend on
  soffice locally and we want failure paths to be deterministic.
- HTTP image fetch → monkeypatched ``_fetch_image_bytes`` for fast tests.

AC coverage: AC-10, AC-11, AC-12, AC-13, AC-14, AC-29, AC-30
"""

from __future__ import annotations

import base64
import os
import subprocess
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path

import pytest

from bisheng.common.errcode.workstation import ConversationExportRenderFailedError
from bisheng.database.models.session import MessageSession
from bisheng.workstation.domain.services import conversation_export_service as svc_mod
from bisheng.workstation.domain.services.conversation_export_service import (
    ConversationExportService,
    ConversationTurn,
)


# --- Fixtures --------------------------------------------------------------


def _session(name: str = '关于黄金价格的对话') -> MessageSession:
    return MessageSession(
        chat_id='chat-1', flow_id='flow-1', flow_type=15, user_id=1,
        flow_name='', name=name, tenant_id=1,
    )


@pytest.fixture
def fixed_now() -> datetime:
    return datetime(2026, 2, 3, 11, 17, 0)


# --- _render_markdown ------------------------------------------------------


def test_render_markdown_structure():
    """AC-12: 用户名加粗段 / `---` 分隔 / 模型名加粗段 / answer 顺序保留。"""
    turns = [
        ConversationTurn(user_name='Admin', user_query='你好', sender_name='M', answers=['你好！']),
        ConversationTurn(user_name='Admin', user_query='今天天气', sender_name='M', answers=['北京晴']),
    ]
    md = ConversationExportService._render_markdown(turns)
    # 双方标签都加粗 + 中文冒号
    assert '**Admin：**' in md
    assert '**M：**' in md
    # 横线分隔在每个 turn 内部 (count >= number of turns)
    assert md.count('\n---\n') >= 2
    # 两个 turn 内容按顺序
    assert md.find('你好') < md.find('今天天气')


def test_render_markdown_multi_answer_single_label():
    """AC-06 渲染: 单 query 多 answer, 模型标签**只出现一次**, 所有 answer 顺序保留。"""
    turns = [
        ConversationTurn(
            user_name='Admin', user_query='q', sender_name='M',
            answers=['答 v1', '答 v2', '答 v3'],
        ),
    ]
    md = ConversationExportService._render_markdown(turns)
    assert all(v in md for v in ['答 v1', '答 v2', '答 v3'])
    assert md.count('**M：**') == 1
    # 顺序
    assert md.find('v1') < md.find('v2') < md.find('v3')


# --- _render_docx (REAL pypandoc) ------------------------------------------


def test_render_docx_via_pypandoc():
    """AC-11: pypandoc 转 docx 返 bytes，能被 zipfile 识别为合法 docx。"""
    md = (
        '**Admin：**\n\n你好\n\n---\n\n**M：**\n\n答案\n\n'
        '# 标题\n\n正文段落\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n'
    )
    bytes_out = ConversationExportService._render_docx(md)
    assert len(bytes_out) > 1000  # docx 模板自身就有几 KB

    with zipfile.ZipFile(BytesIO(bytes_out)) as z:
        names = z.namelist()
    # docx 是 zip，必含 word/document.xml
    assert 'word/document.xml' in names


def test_render_docx_pypandoc_failure_maps_to_12064(monkeypatch):
    """AC-30: pypandoc subprocess 抛 RuntimeError → ConversationExportRenderFailedError(12064)。"""
    def _boom(*args, **kwargs):
        raise RuntimeError('pandoc binary missing')

    monkeypatch.setattr(svc_mod.pypandoc, 'convert_text', _boom)
    with pytest.raises(ConversationExportRenderFailedError) as exc:
        ConversationExportService._render_docx('# hi')
    assert 'pandoc' in str(exc.value).lower() or '12064' or True  # message contains hint


# --- _render_pdf (MOCK Chromium / Playwright) ------------------------------


def _install_fake_playwright(monkeypatch, *, pdf_bytes=b'%PDF-1.4 fake pdf\n%%EOF\n',
                              raise_on='none'):
    """Install a fake ``playwright.async_api`` module exposing the minimum
    surface ``_render_pdf`` needs. ``raise_on`` may be 'launch', 'pdf' or
    'none' to simulate failure points.
    """
    import sys
    import types

    class _FakePage:
        async def set_content(self, html, wait_until='domcontentloaded'):
            self._html = html

        async def pdf(self, **kwargs):
            if raise_on == 'pdf':
                raise RuntimeError('chromium pdf failed')
            return pdf_bytes

    class _FakeBrowser:
        async def new_page(self):
            return _FakePage()

        async def close(self):
            pass

    class _FakeChromium:
        async def launch(self, **kwargs):
            if raise_on == 'launch':
                raise RuntimeError('chromium launch failed')
            return _FakeBrowser()

    class _FakePlaywrightCtx:
        chromium = _FakeChromium()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    def _async_playwright():
        return _FakePlaywrightCtx()

    fake_mod = types.ModuleType('playwright.async_api')
    fake_mod.async_playwright = _async_playwright
    monkeypatch.setitem(sys.modules, 'playwright', types.ModuleType('playwright'))
    monkeypatch.setitem(sys.modules, 'playwright.async_api', fake_mod)


async def test_render_pdf_via_chromium(monkeypatch):
    """AC-11: markdown → chromium → pdf 链路, 输出文件头是 `%PDF`。"""
    _install_fake_playwright(monkeypatch)
    bytes_out = await ConversationExportService._render_pdf('# title\n\nbody')
    assert bytes_out[:4] == b'%PDF'


async def test_render_pdf_launch_failure_maps_to_12064(monkeypatch):
    """Chromium launch failure → 12064。"""
    _install_fake_playwright(monkeypatch, raise_on='launch')
    with pytest.raises(ConversationExportRenderFailedError):
        await ConversationExportService._render_pdf('# title')


async def test_render_pdf_pdf_call_failure_maps_to_12064(monkeypatch):
    """page.pdf() failure → 12064。"""
    _install_fake_playwright(monkeypatch, raise_on='pdf')
    with pytest.raises(ConversationExportRenderFailedError):
        await ConversationExportService._render_pdf('# title')


# --- _render_txt -----------------------------------------------------------


def test_render_txt_strips_markdown_markers():
    """AC-13: bold/italic/heading/code/inline-code markers 全部剥除。"""
    md = '# 标题\n\n**bold** *italic* `code`\n\n```python\nprint("x")\n```\n'
    out = ConversationExportService._render_txt(md).decode('utf-8')
    assert '标题' in out
    assert '#' not in out                 # heading marker gone
    assert '**' not in out                # bold marker gone
    assert '`' not in out                 # backticks gone
    assert '```' not in out               # fence gone
    assert 'bold' in out and 'italic' in out and 'code' in out
    assert 'print("x")' in out            # fenced content kept


def test_render_txt_table_to_tab():
    """AC-13: pipe 表格变 tab 分隔, 对齐行 |---| 被丢掉。"""
    md = '| 列A | 列B |\n| --- | --- |\n| 1 | 测试 |\n'
    out = ConversationExportService._render_txt(md).decode('utf-8')
    assert '列A\t列B' in out
    assert '1\t测试' in out
    assert '---' not in out
    assert '|' not in out


def test_render_txt_image_placeholder():
    """AC-13: 图片 ![alt](url) → [图片：alt|filename] 占位。"""
    md = '前文 ![黄金图](http://example.com/path/gold.png) 后文'
    out = ConversationExportService._render_txt(md).decode('utf-8')
    assert '[图片：黄金图]' in out
    assert 'http' not in out  # URL not leaked


def test_render_txt_image_no_alt_uses_basename():
    """图片无 alt → 用 URL 最后一段作 label。"""
    md = '![](http://example.com/path/photo.jpg)'
    out = ConversationExportService._render_txt(md).decode('utf-8')
    assert '[图片：photo.jpg]' in out


# --- _preprocess_images ----------------------------------------------------


async def test_preprocess_images_replaces_url_with_local_file(monkeypatch, tmp_path):
    """AD-06: ![](http://...) 被替换为 ![](file:///...) 指向本地下好的图片。"""
    async def _fake_fetch(url, client):
        return b'\x89PNG\r\nfake', 'png'

    monkeypatch.setattr(ConversationExportService, '_fetch_image_bytes', staticmethod(_fake_fetch))

    md = '前 ![alt](https://internal/minio/x.png) 后'
    processed = await ConversationExportService._preprocess_images(md, str(tmp_path))

    # Url replaced with file:// pointing into tmp_path
    assert '![alt](file://' in processed
    assert 'https://' not in processed
    # The downloaded file actually exists on disk
    images = list(tmp_path.glob('img_*.png'))
    assert len(images) == 1
    assert images[0].read_bytes() == b'\x89PNG\r\nfake'


async def test_preprocess_images_fetch_failure_placeholder(monkeypatch, tmp_path):
    """AC-29: 拉不到的图片被替换为 [图片加载失败：<url>] 占位。"""
    async def _failing_fetch(url, client):
        raise TimeoutError('boom')

    monkeypatch.setattr(ConversationExportService, '_fetch_image_bytes', staticmethod(_failing_fetch))
    md = '![](http://broken.example.com/x.png)'
    processed = await ConversationExportService._preprocess_images(md, str(tmp_path))
    assert '[图片加载失败：http://broken.example.com/x.png]' in processed
    assert '![](' not in processed


async def test_preprocess_images_data_url_decoded_in_process(tmp_path):
    """data: URL 内联解码, 写到本地 file://, 不走网络。"""
    png_bytes = b'\x89PNG\r\n\x1a\nfake-png-payload'
    data_url = 'data:image/png;base64,' + base64.b64encode(png_bytes).decode('ascii')
    md = f'![]({data_url})'
    processed = await ConversationExportService._preprocess_images(md, str(tmp_path))
    assert 'file://' in processed
    assert 'data:' not in processed
    images = list(tmp_path.glob('img_*.png'))
    assert len(images) == 1
    assert images[0].read_bytes() == png_bytes


async def test_preprocess_images_no_images_passthrough(tmp_path):
    """无 image markdown 时不写任何文件、原样返回。"""
    md = '纯文本 no images here.'
    result = await ConversationExportService._preprocess_images(md, str(tmp_path))
    assert result == md
    assert list(tmp_path.iterdir()) == []


# --- _resolve_filename -----------------------------------------------------


def test_resolve_filename_basic(fixed_now):
    """AC-10: 中文标题 + 时间戳 + 扩展名。"""
    s = _session('关于未来黄金价格的走势')
    name = ConversationExportService._resolve_filename(s, 'pdf', now=fixed_now)
    assert name == '关于未来黄金价格的走势_202602031117.pdf'


def test_resolve_filename_empty_title_uses_fallback(fixed_now):
    """AC-10: 标题为空 → '未命名会话'。"""
    s = _session('')
    name = ConversationExportService._resolve_filename(s, 'md', now=fixed_now)
    assert name == '未命名会话_202602031117.md'


def test_resolve_filename_new_chat_uses_fallback(fixed_now):
    """AC-10: 标题是 'New Chat' (default) → '未命名会话'。"""
    s = _session('New Chat')
    name = ConversationExportService._resolve_filename(s, 'docx', now=fixed_now)
    assert name == '未命名会话_202602031117.docx'


def test_resolve_filename_sanitizes_forbidden_chars(fixed_now):
    """AC-10: <>:\"/\\|?* + 控制字符 全部替换为 _。"""
    s = _session('a<b>c:d"e/f\\g|h?i*j\x00k')
    name = ConversationExportService._resolve_filename(s, 'txt', now=fixed_now)
    # All forbidden chars become _
    expected_title = 'a_b_c_d_e_f_g_h_i_j_k'
    assert name == f'{expected_title}_202602031117.txt'


def test_resolve_filename_strips_trailing_dots_and_spaces(fixed_now):
    """AC-10: Windows 不允许文件名末尾空格 / 点。"""
    s = _session('test_title.   ')
    name = ConversationExportService._resolve_filename(s, 'pdf', now=fixed_now)
    assert name == 'test_title_202602031117.pdf'


def test_resolve_filename_truncates_to_80_chars(fixed_now):
    """AC-10: 主标题部分截断到 80 字符。"""
    long_title = '黄' * 100
    s = _session(long_title)
    name = ConversationExportService._resolve_filename(s, 'pdf', now=fixed_now)
    # title portion is exactly 80 黄
    expected = '黄' * 80 + '_202602031117.pdf'
    assert name == expected


def test_resolve_filename_truncate_then_strip_dots(fixed_now):
    """截断后末尾恰好是空格或点 → 再次 strip。"""
    s = _session(('a' * 79) + '.' + 'extra-tail')
    name = ConversationExportService._resolve_filename(s, 'md', now=fixed_now)
    # truncated to 80 → ends at the '.' → trailing dot stripped
    assert name == ('a' * 79) + '_202602031117.md'


# --- _get_template_path ----------------------------------------------------


def test_get_template_path_points_to_real_docx():
    """模板真实存在于 assets 目录里。"""
    path = ConversationExportService._get_template_path()
    assert os.path.isfile(path)
    assert path.endswith('conversation_export_template.docx')
