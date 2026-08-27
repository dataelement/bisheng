"""Typography profiles — the *values* half of this skill, kept apart from the code.

``docx_helpers`` owns the mechanics (``w:eastAsia``, field codes, cell widths).
This module owns what those mechanics render *as*: which face, which size, which
leading. Splitting them is what lets an imported third-party 公文 skill override
the look without reimplementing the plumbing — it hands over a dict, not a script.

Two built-in profiles:

* ``gongwen``  — GB/T 9704-2012《党政机关公文格式》. **The default.**
* ``modern``   — the generic corporate look (微软雅黑 11pt). For CVs, marketing
  one-pagers, outward-facing proposals — anything explicitly *not* an official
  document.

A profile is a plain dict so a caller can pass only the keys that differ::

    resolve_profile("gongwen", {"body": {"font": "华文中宋"}})

Chinese size names, since every 公文 spec is written in them:
初号42 · 小初36 · 一号26 · 小一24 · **二号22** · 小二18 · **三号16** · 小三15
· **四号14** · 小四12 · 五号10.5 · 小五9
"""

from copy import deepcopy

# GB/T 9704-2012. Sizes are the Chinese names resolved to points; the margins are
# the standard's 版心 (37/35/28/26 mm). Body leading is fixed 28pt rather than a
# multiple — the standard specifies 22 lines per page, which a multiple cannot
# hold once the font size moves.
GONGWEN = {
    "name": "gongwen",
    "page": {
        "margin_top_cm": 3.7,
        "margin_bottom_cm": 3.5,
        "margin_left_cm": 2.8,
        "margin_right_cm": 2.6,
    },
    "body": {
        "font": "仿宋_GB2312",  # 三号仿宋
        "pt": 16,
        "line_pt": 28,  # fixed leading, not a multiple
        "space_after_pt": 0,  # 公文 runs continuous; spacing comes from leading
        "indent_chars": 2,
        "color": "000000",
    },
    # The document title (标题), not a Heading style: 二号方正小标宋简体, centred.
    "title": {"font": "方正小标宋简体", "pt": 22, "color": "000000"},
    # All four levels are 三号 — the standard separates them by *face*, not size.
    "headings": {
        1: {"font": "黑体", "pt": 16, "bold": False, "color": "000000"},  # 一、
        2: {"font": "楷体_GB2312", "pt": 16, "bold": False, "color": "000000"},  # （一）
        3: {"font": "仿宋_GB2312", "pt": 16, "bold": True, "color": "000000"},  # 1.
        4: {"font": "仿宋_GB2312", "pt": 16, "bold": True, "color": "000000"},  # （1）
        "space_before_pt": 0,
        "space_after_pt": 0,
    },
    "toc": {"font": "黑体", "pt": 16, "color": "000000"},
    "table": {
        "font": "仿宋_GB2312",
        "pt": 14,  # 四号
        "header_fill": None,  # 公文 tables carry no dark header band…
        "header_bold": True,  # …so the header row has to be bold, or it reads as data
        "header_color": "000000",
        "banded": False,
        "band_fill": None,
    },
    "footer": {"font": "宋体", "pt": 14, "color": "000000"},  # 页码 四号宋体
    "caption": {"font": "楷体_GB2312", "pt": 14, "color": "000000"},
}

# The look this skill shipped with. Values are carried over unchanged so a
# document built before profiles existed renders identically under "modern".
MODERN = {
    "name": "modern",
    "page": {
        "margin_top_cm": 2.54,
        "margin_bottom_cm": 2.54,
        "margin_left_cm": 2.54,
        "margin_right_cm": 2.54,
    },
    "body": {
        "font": "微软雅黑",
        "pt": 11,
        "line_multiple": 1.5,
        "space_after_pt": 6,
        "indent_chars": 2,
        "color": None,
    },
    "title": {"font": "微软雅黑", "pt": 20, "color": "1F1F1F"},
    "headings": {
        1: {"font": "微软雅黑", "pt": 20, "bold": True, "color": "1F1F1F"},
        2: {"font": "微软雅黑", "pt": 16, "bold": True, "color": "1F1F1F"},
        3: {"font": "微软雅黑", "pt": 14, "bold": True, "color": "1F1F1F"},
        4: {"font": "微软雅黑", "pt": 12, "bold": True, "color": "1F1F1F"},
        "space_before_pt": 12,
        "space_after_pt": 6,
    },
    "toc": {"font": "微软雅黑", "pt": 18, "color": "1F1F1F"},
    "table": {
        "font": "微软雅黑",
        "pt": 10,
        "header_fill": "1F4E79",
        "header_bold": True,
        "header_color": "FFFFFF",
        "banded": True,
        "band_fill": "F2F6FA",
    },
    "footer": {"font": "微软雅黑", "pt": 9, "color": "808080"},
    "caption": {"font": "微软雅黑", "pt": 9, "color": "808080"},
}

BUILTIN = {"gongwen": GONGWEN, "modern": MODERN}

# Generic Chinese faces. Perfectly fine in a corporate document; in a 公文 they
# mean the mandated face was silently swapped out. ``inspect_docx.py`` reads this.
GENERIC_CN_FONTS = ("微软雅黑", "等线", "宋体", "SimSun", "Microsoft YaHei", "DengXian", "Noto Sans CJK SC")

_ACTIVE = deepcopy(GONGWEN)


def _deep_merge(base: dict, extra: dict) -> dict:
    """Merge ``extra`` into a copy of ``base``, recursing into nested dicts.

    Nested rather than flat so a caller can say ``{"body": {"font": "华文中宋"}}``
    and keep the profile's size, leading and indent.
    """
    merged = deepcopy(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def resolve_profile(profile=None, overrides: dict | None = None) -> dict:
    """Resolve a profile name, a dict of overrides, or both, into a full profile.

        resolve_profile()                                   -> gongwen
        resolve_profile("modern")                           -> modern
        resolve_profile({"body": {"font": "华文中宋"}})       -> gongwen + that change
        resolve_profile("modern", {"body": {"pt": 12}})     -> modern + that change

    An unknown name falls back to gongwen rather than raising: a build script that
    dies on a typo costs the user a whole round, a slightly wrong face does not.
    """
    if profile is None:
        resolved = deepcopy(GONGWEN)
    elif isinstance(profile, str):
        resolved = deepcopy(BUILTIN.get(profile, GONGWEN))
    elif isinstance(profile, dict):
        # A bare dict is treated as overrides on top of the default profile,
        # unless it names a base itself.
        base = BUILTIN.get(profile.get("name"), GONGWEN)
        resolved = _deep_merge(base, profile)
    else:
        resolved = deepcopy(GONGWEN)

    if overrides:
        resolved = _deep_merge(resolved, overrides)
    return resolved


def set_active_profile(profile=None, overrides: dict | None = None) -> dict:
    """Make a profile the default for every helper in this package.

    ``apply_chinese_defaults()`` calls this, so a build script picks its profile
    once and every later ``add_body`` / ``add_heading_cn`` / ``add_table`` follows
    without being told again. Passing the profile to each call individually is the
    reliable way to end up with a document that is 90% right.
    """
    global _ACTIVE
    _ACTIVE = resolve_profile(profile, overrides)
    return _ACTIVE


def active_profile() -> dict:
    """The profile helpers fall back to when no explicit font/size is given."""
    return _ACTIVE


def heading_spec(level: int, profile: dict | None = None) -> dict:
    """Per-level heading values, falling back to level 4 beyond the fourth level."""
    headings = (profile or _ACTIVE)["headings"]
    return headings.get(level) or headings[4]
