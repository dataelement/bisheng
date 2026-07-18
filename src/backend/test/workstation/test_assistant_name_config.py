"""工作台 AI 助手自定义名称 (assistant_name) 配置。

知识空间 / 订阅两个工作台对话面板的标题可由管理员自定义。后端在
KnowledgeSpaceConfig / SubscriptionConfig 各加了 `assistant_name` 字段，默认空串；
客户端拿到空串时回退到本地化默认文案 ("AI 助手")。

这些用例钉住存储 round-trip 与升级回退语义（服务层用
`<Config>(**json.loads(value))` 解析 DB 行的 JSON `value`）：
- 自定义名能存能取（管理员设过 → 透传给前端）；
- 旧版本配置（无 assistant_name 键）解析后落到默认空串（升级不破坏）；
- 全新构造（空 payload / 部分 admin payload）也落到空串。
"""

import json

from bisheng.api.v1.schemas import KnowledgeSpaceConfig, SubscriptionConfig


def _parse_ks(payload: dict) -> KnowledgeSpaceConfig:
    """Mirror WorkStationService.get_knowledge_space_config 的解析方式。"""
    return KnowledgeSpaceConfig(**json.loads(json.dumps(payload)))


def _parse_sub(payload: dict) -> SubscriptionConfig:
    """Mirror WorkStationService.get_subscription_config 的解析方式。"""
    return SubscriptionConfig(**json.loads(json.dumps(payload)))


def test_knowledge_space_assistant_name_defaults_blank_when_constructed_blank():
    # 全新部署 / 部分 admin payload：不应凭空出现非空名称。
    assert KnowledgeSpaceConfig().assistant_name == ""


def test_subscription_assistant_name_defaults_blank_when_constructed_blank():
    assert SubscriptionConfig().assistant_name == ""


def test_knowledge_space_legacy_config_omits_assistant_name():
    # 旧库 JSON 没有 assistant_name 键 → 解析后落默认空串（升级回退）。
    cfg = _parse_ks({"system_prompt": "x", "user_prompt": "y", "max_chunk_size": 15000})
    assert cfg.assistant_name == ""


def test_subscription_legacy_config_omits_assistant_name():
    cfg = _parse_sub({"system_prompt": "x", "user_prompt": "y", "feedback_tips": "z"})
    assert cfg.assistant_name == ""


def test_knowledge_space_assistant_name_roundtrips_custom_value():
    # 管理员设了自定义名 → 存储 round-trip 后仍是该名（透传给前端做标题）。
    saved = KnowledgeSpaceConfig(assistant_name="北大助手")
    stored = json.dumps(saved.model_dump(mode="json"), ensure_ascii=True)
    reparsed = KnowledgeSpaceConfig(**json.loads(stored))
    assert reparsed.assistant_name == "北大助手"


def test_subscription_assistant_name_roundtrips_custom_value():
    saved = SubscriptionConfig(assistant_name="订阅小助手")
    stored = json.dumps(saved.model_dump(mode="json"), ensure_ascii=True)
    reparsed = SubscriptionConfig(**json.loads(stored))
    assert reparsed.assistant_name == "订阅小助手"
