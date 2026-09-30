"""F072 — stored markers are shown to the model as ``[Sn]`` in history.

Past answers are stored with private-use markers around registry keys. Replayed
as-is, the model would see two citation formats and start copying the old one.
Keys with no handle (answers from before the migration, an expired table) are
dropped with their marker; the prose stays.

AC-11.
"""

from bisheng.citation.domain.services.citation_prompt_helper import (
    CITATION_END_MARKER as E,
)
from bisheng.citation.domain.services.citation_prompt_helper import (
    CITATION_SEPARATOR_MARKER as SEP,
)
from bisheng.citation.domain.services.citation_prompt_helper import (
    CITATION_START_MARKER as S,
)
from bisheng.citation.domain.services.daily_citation_handles import markers_to_handles

K3 = "knowledgesearch_bbbb2222:1"
K7 = "websearch_cccc3333:0"
OLD = "knowledgesearch_0ld0ld00:4"
TABLE = {K3: "S3", K7: "S7"}


def test_known_key_becomes_its_handle():
    assert markers_to_handles(f"结论。{S}{K3}{E}", TABLE) == "结论。[S3]"


def test_multi_source_marker_becomes_adjacent_handles():
    assert markers_to_handles(f"结论{S}{K3}{SEP}{K7}{E}。", TABLE) == "结论[S3][S7]。"


def test_unmapped_keys_are_dropped_and_prose_kept():
    assert markers_to_handles(f"老回答。{S}{OLD}{E}后文", TABLE) == "老回答。后文"
    assert markers_to_handles(f"混合{S}{OLD}{SEP}{K7}{E}。", TABLE) == "混合[S7]。"


def test_escaped_marker_form_is_handled():
    text = "结论。\\ue200" + K3 + "\\ue202"
    assert markers_to_handles(text, TABLE) == "结论。[S3]"


def test_unterminated_marker_leaves_no_private_chars():
    out = markers_to_handles(f"未闭合{S}{OLD} 后文", TABLE)
    assert S not in out and E not in out
    assert OLD not in out


def test_text_without_markers_is_untouched():
    assert markers_to_handles("普通回答 [3]。", TABLE) == "普通回答 [3]。"
    assert markers_to_handles("", TABLE) == ""
