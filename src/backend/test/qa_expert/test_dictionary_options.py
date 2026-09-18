from types import SimpleNamespace

from bisheng.qa_expert.domain.dictionary_options import canonical_dict_options, dict_filter_aliases


def test_canonical_dict_options_dedupes_key_and_display_value() -> None:
    items = [
        SimpleNamespace(dict_key="expert_job_family_001", dict_value="制造技术族"),
        SimpleNamespace(dict_key="expert_job_family_002", dict_value="技能操作族"),
        SimpleNamespace(dict_key="expert_job_family_003", dict_value="制造技术族"),
    ]

    options = canonical_dict_options(
        ["expert_job_family_001", "制造技术族", "expert_job_family_003", "技能操作族"],
        items,
    )

    assert options == [
        {"dict_key": "expert_job_family_001", "dict_value": "制造技术族"},
        {"dict_key": "expert_job_family_002", "dict_value": "技能操作族"},
    ]


def test_dict_filter_aliases_include_key_and_value() -> None:
    items = [SimpleNamespace(dict_key="expert_job_family_001", dict_value="制造技术族")]

    assert dict_filter_aliases("expert_job_family_001", items) == [
        "expert_job_family_001",
        "制造技术族",
    ]
    assert dict_filter_aliases("制造技术族", items) == [
        "expert_job_family_001",
        "制造技术族",
    ]
