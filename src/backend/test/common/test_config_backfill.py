"""Newly shipped config keys must reach environments that are already installed.

``init_config`` writes ``initdb_config.yaml`` into the database only when the row
is absent. On any install that has booted once the row exists, so every setting
added in a later release stopped at the file and never reached the DB — the code
then silently ran on the ``settings.py`` Field default instead. That is how a
task-mode turn budget stayed at 115 on every existing deployment after the
default had already moved on, and it is invisible: the config page shows the
stored (old) config, which simply has no such key.

``merge_missing_config`` closes that gap on every boot. Its contract is narrow on
purpose, and these tests pin the parts that make it safe to run unattended:

  * a value already in the DB is NEVER touched (operator tuning outranks ours);
  * keys only the DB has are preserved (hand-added settings survive);
  * comments come across with the key, because that text is the documentation
    operators read in the system-config page;
  * nothing to add → byte-identical output, so repeated boots do not churn the
    row or evict its cache.
"""

from __future__ import annotations

import yaml

from bisheng.common.services.config_service import ConfigService

FILE_CONFIG = """\
# 灵思模块相关配置
linsight:
  # 历史记录中工具消息的最大token
  tool_buffer: 100000
  # 单个任务最大执行步骤数
  max_steps: 2500
  # 主图轮次预算-一次任务最多允许多少次模型调用
  max_model_turns: 600
  # 子代理轮次预算
  max_model_turns_subagent: 120

# 新增的顶层段
brand_new:
  # 带注释的新配置
  enabled: true
"""

DB_CONFIG = """\
# 灵思模块相关配置
linsight:
  # 历史记录中工具消息的最大token
  tool_buffer: 100000
  # 单个任务最大执行步骤数
  max_steps: 200
"""


def _merge(file_cfg=FILE_CONFIG, db_cfg=DB_CONFIG):
    merged, added = ConfigService.merge_missing_config(file_cfg, db_cfg)
    return yaml.safe_load(merged), added, merged


def test_missing_nested_keys_are_added():
    """The production case: the section exists, the new keys inside it do not."""
    cfg, added, _ = _merge()

    assert cfg["linsight"]["max_model_turns"] == 600
    assert cfg["linsight"]["max_model_turns_subagent"] == 120
    assert "linsight.max_model_turns" in added
    assert "linsight.max_model_turns_subagent" in added


def test_existing_values_are_never_overwritten():
    """max_steps is 200 in the DB and 2500 in the file — the DB wins."""
    cfg, added, _ = _merge()

    assert cfg["linsight"]["max_steps"] == 200
    assert not any(a.endswith("max_steps") for a in added)


def test_missing_top_level_section_is_added_whole():
    cfg, added, _ = _merge()

    assert cfg["brand_new"]["enabled"] is True
    assert "brand_new" in added


def test_comments_travel_with_the_key():
    """Operators read these comments in the config page; a yaml round-trip would
    have dropped every one of them."""
    _, _, merged = _merge()

    assert "# 主图轮次预算-一次任务最多允许多少次模型调用" in merged
    assert "# 子代理轮次预算" in merged
    assert "# 带注释的新配置" in merged
    # The DB's own comments survive too.
    assert "# 历史记录中工具消息的最大token" in merged


def test_db_only_keys_are_preserved():
    """A setting the operator added by hand must not be dropped."""
    db = DB_CONFIG + "\n# 运维手工加的\ncustom_section:\n  keep_me: yes\n"
    cfg, _, merged = _merge(db_cfg=db)

    assert cfg["custom_section"]["keep_me"] is True
    assert "# 运维手工加的" in merged


def test_nothing_missing_is_a_byte_identical_no_op():
    """Repeated boots must not rewrite the row or evict its cache."""
    merged, added = ConfigService.merge_missing_config(FILE_CONFIG, FILE_CONFIG)

    assert added == []
    assert merged == FILE_CONFIG


def test_merge_is_idempotent():
    once, added_once = ConfigService.merge_missing_config(FILE_CONFIG, DB_CONFIG)
    twice, added_twice = ConfigService.merge_missing_config(FILE_CONFIG, once)

    assert added_once
    assert added_twice == []
    assert twice == once


def test_result_stays_valid_yaml_with_correct_indentation():
    _, _, merged = _merge()
    cfg = yaml.safe_load(merged)

    # Inserted children landed INSIDE the section, not at the top level.
    assert "max_model_turns" not in cfg
    assert set(cfg["linsight"]) == {
        "tool_buffer",
        "max_steps",
        "max_model_turns",
        "max_model_turns_subagent",
    }


def test_empty_or_malformed_inputs_are_left_alone():
    assert ConfigService.merge_missing_config("", DB_CONFIG) == (DB_CONFIG, [])
    # A scalar document is not a config tree — refuse rather than mangle it.
    merged, added = ConfigService.merge_missing_config("just a string", DB_CONFIG)
    assert (merged, added) == (DB_CONFIG, [])


def test_scalar_vs_section_mismatch_is_skipped():
    """File says section, DB says scalar (or vice versa) — leave the DB alone
    rather than guess which shape is right."""
    file_cfg = "linsight:\n  max_model_turns: 600\n"
    db_cfg = "linsight: disabled\n"

    merged, added = ConfigService.merge_missing_config(file_cfg, db_cfg)

    assert added == []
    assert yaml.safe_load(merged)["linsight"] == "disabled"
