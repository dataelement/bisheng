"""Pure helpers: suggest ids, drop catalog history, relocate (F061 T025).

Orchestration coverage moved to test_image_view_react_loop.py.
Covers AC: AC-04, AC-08
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from bisheng.common.image_view.loop import IMAGE_VIEW_PROMPT_RULES, prepare_vision_messages, suggest_image_ids
from bisheng.common.image_view.relocate import relocate_images_to_human

_DATA_URI = "data:image/png;base64,aaa"

_OPENING_HANDBOOK = """
首钢集团司库系统账户管理模块用户操作手册
![cover](/bisheng/knowledge/images/1/6/image_1_3.jpeg)⟦img#1⟧
![logo](/bisheng/knowledge/images/1/6/image_1_1.jpeg)⟦img#2⟧
目录
1.1.1 开户申请..................................................................1

1.1.1.开户申请
成员单位去合作金融机构开立账户前，需提交账户申请。经办人在账户开户申请界面可查询单据。
管控要点：
![ctrl](/bisheng/knowledge/images/1/6/image_3_4.jpeg)⟦img#4⟧
操作路径：司库管理 事项申请
![path](/bisheng/knowledge/images/1/6/image_4_9.jpeg)⟦img#6⟧
操作路径：司库管理 银行账户 开户申请（查看已审批的账户开户申请单）
![list](/bisheng/knowledge/images/1/6/image_4_10.jpeg)⟦img#9⟧
点击单据号可查看开户申请详情：
![form](/bisheng/knowledge/images/1/6/image_4_8.jpeg)⟦img#10⟧

1.1.2.开户登记
选中单据点击待登记，检查登记表单信息，点击保存并提交：
![register](/bisheng/knowledge/images/1/6/image_6_14.jpeg)⟦img#14⟧

1.3.1.销户申请
经办人在账户销户申请界面可查询单据。
操作路径：司库管理 银行账户 销户申请
![close](/bisheng/knowledge/images/1/6/image_10_28.jpeg)⟦img#28⟧
"""


def test_relocate_moves_image_blocks_off_tool_message():
    messages = [
        HumanMessage(content="question"),
        ToolMessage(
            content=[
                {"type": "text", "text": "ack"},
                {"type": "image_url", "image_url": {"url": _DATA_URI}},
            ],
            tool_call_id="call_1",
        ),
    ]
    out = relocate_images_to_human(messages)
    tool = next(m for m in out if isinstance(m, ToolMessage))
    assert tool.content == "ack"
    humans = [m for m in out if isinstance(m, HumanMessage)]
    assert any(
        isinstance(m.content, list) and any(b.get("type") == "image_url" for b in m.content if isinstance(b, dict))
        for m in humans
    )
    assert not any(
        isinstance(m, ToolMessage) and isinstance(m.content, list) and any(_is_image(b) for b in m.content) for m in out
    )


def _is_image(block: object) -> bool:
    return isinstance(block, dict) and block.get("type") in {"image_url", "image"}


def test_suggest_image_ids_prefers_heading_near_question_not_cover():
    question = "开户申请那张界面截图里，表单上有哪些字段？"
    suggested = suggest_image_ids(_OPENING_HANDBOOK, question)
    assert suggested
    assert "img#1" not in suggested
    assert "img#2" not in suggested
    assert any(image_id in suggested for image_id in ("img#6", "img#9", "img#10"))


def test_suggest_image_ids_does_not_rank_unrelated_close_account_section():
    question = "开户申请表单上有哪些字段？"
    suggested = suggest_image_ids(_OPENING_HANDBOOK, question)
    assert "img#28" not in suggested
    assert any(image_id in suggested for image_id in ("img#9", "img#10"))


def test_image_catalog_history_is_dropped_when_preparing_messages():
    catalog = "\n".join(f"### img#{i} — guessed caption" for i in range(1, 8))
    messages = [
        SystemMessage(content="base system"),
        HumanMessage(content="文档中的图片写了啥？"),
        AIMessage(content=catalog),
        HumanMessage(content="这篇文档写了啥？ see ![chart](/x.png)⟦img#1⟧"),
    ]
    out = prepare_vision_messages(messages)
    assert not any(isinstance(m, AIMessage) and "img#1" in str(m.content) for m in out)
    assert any(isinstance(m, HumanMessage) and "这篇文档写了啥" in str(m.content) for m in out)
    assert IMAGE_VIEW_PROMPT_RULES in out[0].content


def test_short_img_mention_history_dropped_when_question_needs_pixels():
    messages = [
        SystemMessage(content="base system"),
        HumanMessage(content="开户申请那张界面截图里，表单上有哪些字段？"),
        AIMessage(content="根据截图（img#1），该图片仅显示标志，建议查看 img#7。"),
        HumanMessage(content="# 用户问题\n```\n开户申请表单上有哪些字段？\n```"),
    ]
    out = prepare_vision_messages(messages)
    assert not any(isinstance(m, AIMessage) and "img#" in str(m.content) for m in out)


def test_screenshot_question_hints_matching_image_ids():
    messages = [
        SystemMessage(content="base system"),
        HumanMessage(content=f"{_OPENING_HANDBOOK}\n# 用户问题\n```\n开户申请那张界面截图里，表单上有哪些字段？\n```"),
    ]
    out = prepare_vision_messages(messages)
    system = out[0].content
    assert "本题附近标题更匹配的图片：" in system
    hinted = system.split("本题附近标题更匹配的图片：", 1)[-1].split("。", 1)[0]
    hinted_ids = [part.strip() for part in hinted.split("、") if part.strip()]
    assert "img#1" not in hinted_ids
    assert any(token in hinted_ids for token in ("img#6", "img#9", "img#10"))
    assert "img#28" not in hinted_ids


def _hinted_ids(system: str) -> list[str]:
    hinted = system.split("本题附近标题更匹配的图片：", 1)[-1].split("。", 1)[0]
    return [part.strip() for part in hinted.split("、") if part.strip()]


def test_viewed_images_human_does_not_poison_pick_toward_last_url():
    """Synthetic 'Viewed images:' must not become the question; URL 'images/' must not rank picks."""
    context = (
        _OPENING_HANDBOOK
        + "\n2.3 U盾注销\n操作路径：司库管理 银行账户 网银U盾注销\n"
        + "![usb](/bisheng/knowledge/images/1/6/image_20_69.jpeg)⟦img#65⟧\n"
        + "![usb2](/bisheng/knowledge/images/1/6/image_20_70.jpeg)⟦img#66⟧\n"
    )
    messages = [
        SystemMessage(content="base system"),
        HumanMessage(content="<user_question>\n把开户登记界面说明相关的图片显示出来\n</user_question>"),
        ToolMessage(content=context, tool_call_id="s1", name="search_knowledge_bases"),
        ToolMessage(content="Image img#19 is not available (too_small).", tool_call_id="v0", name="view_image"),
        HumanMessage(
            content=[
                {"type": "text", "text": "Viewed images: img#7"},
                {"type": "image_url", "image_url": {"url": _DATA_URI}},
            ]
        ),
    ]
    out = prepare_vision_messages(messages)
    hinted_ids = _hinted_ids(out[0].content)
    assert hinted_ids
    assert "img#65" not in hinted_ids
    assert "img#66" not in hinted_ids
    assert "img#14" in hinted_ids


def test_failed_view_observation_is_not_treated_as_pixels_seen():
    from bisheng.common.image_view.loop import pixels_were_viewed

    failed = [
        HumanMessage(content="把开户登记界面说明相关的图片显示出来"),
        ToolMessage(content="Image img#19 is not available (too_small).", tool_call_id="v0", name="view_image"),
    ]
    ok = [
        *failed,
        ToolMessage(content="Viewed img#7 at standard quality.", tool_call_id="v1", name="view_image"),
    ]
    assert pixels_were_viewed(failed) is False
    assert pixels_were_viewed(ok) is True


_REGISTER_VS_USB = """
1.1.2.开户登记
待登记或已经登记的单据信息，经办人对开户登记单据进行查看、删除、退回、提交。
![a](/bisheng/knowledge/images/1/6/image_5_11.jpeg)⟦img#5⟧
![b](/bisheng/knowledge/images/1/6/image_5_12.jpeg)⟦img#6⟧
操作路径：司库管理 银行账户 开户登记
![c](/bisheng/knowledge/images/1/6/image_6_13.jpeg)⟦img#7⟧
选中单据点击待登记，检查登记表单信息，点击保存并提交：
![d](/bisheng/knowledge/images/1/6/image_6_14.jpeg)⟦img#8⟧
1.6 账户可视状态管理
账户银行开户登记完成后，由财务公司系统办理账户可视状态变更。
![vis](/bisheng/knowledge/images/1/6/image_15_46.jpeg)⟦img#27⟧
2.1 U盾登记
经办人在网银U盾登记界面，可查询当前经办人操作的登记单记录。
![usb1](/bisheng/knowledge/images/1/6/image_18_59.jpeg)⟦img#32⟧
![usb2](/bisheng/knowledge/images/1/6/image_18_60.jpeg)⟦img#33⟧
操作路径：司库管理 银行账户 网银U盾登记
"""


def test_suggest_opening_register_does_not_prefer_usb_register_heading():
    question = "把开户登记界面说明相关的图片显示出来"
    suggested = suggest_image_ids(_REGISTER_VS_USB, question)
    assert suggested
    assert "img#32" not in suggested
    assert "img#33" not in suggested
    assert "img#27" not in suggested
    assert any(image_id in suggested for image_id in ("img#5", "img#6", "img#7", "img#8"))


def test_suggest_skips_already_failed_too_small_ids():
    question = "把开户登记界面说明相关的图片显示出来"
    suggested = suggest_image_ids(_REGISTER_VS_USB, question, exclude={"img#5", "img#6", "img#7"})
    assert "img#5" not in suggested
    assert any(image_id in suggested for image_id in ("img#8",))
    assert "img#32" not in suggested
