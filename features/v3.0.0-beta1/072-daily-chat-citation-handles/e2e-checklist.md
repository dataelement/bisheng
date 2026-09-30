# E2E 验收记录: F072 工作台日常模式引用改用短句柄

**测试环境**: http://192.168.106.120:3002/workspace（test，release `8bc7ae7`，后端 116 同版本）
**账号**: 用户 3（管理员）
**会话**: `d008924f253c40ebbf959b3b1b3f2fa0`，模型 deepseek-v4-flash（774），知识空间「鲁力的部门的知识空间」(3812) + 「有视频【测试溯源】」(4195)，联网检索开
**执行时间**: 2026-09-30 17:09–17:25

## 第 1 轮：「OKR 绩效管理运营规则 2026 版相比 2025 版有哪些主要变化？……并简要联网补充」

| AC | 结果 | 实测 |
|---|---|---|
| AC-01 | ✅ | 落库的工具结果：知识库为 `<ref>S11</ref>`…，联网为 `"ref": "S1"`…；工具结果中 `<chunk_id>`、`citation_key`、`knowledgesearch_`、`websearch_` 出现次数均为 0 |
| AC-02 / AC-03 | ✅ | 后端请求日志里的系统提示词：租户保存的旧「# 引用规则」段已替换为「# 来源编号」，其后「## 其他信息 当前时间：2026-09-30 17:09:35」保留；不含 `<chunk_id>` 与私有区字符 |
| AC-05 | ✅ | 流式期间每 150ms 采样页面文本共 194 次，字面 `[Sn]` 命中 0 次；角标边写边出现（知识库蓝色、联网紫色） |
| AC-06 | ✅ | 落库 `msg` 含 3 组标记、0 个字面编号；执行记录 5 个文本段均已转换 |
| AC-13 | ✅ | `[daily-citation-audit] chat=d008924f… model=774 sources_seen=83 cited=8 unknown_handles=0 legacy_markers=0` |
| AC-14 | ✅ | `message_citation_relation` 只绑定正文实际引用的 2 个来源（1 知识库 + 1 联网） |
| 决策 1 | ✅ | Redis `linsight:cite_handles:d008924f…` 共 44 个编号，**无** `meta:enabled`（日常模式建表不钉任务模式契约） |

## 第 2 轮：「你上面说试行期 6 个月，这个说法出自哪里？请不要重新检索……」

| AC | 结果 | 实测 |
|---|---|---|
| AC-11 | ✅ | 模型思考内容写出「上一轮回答中……标注了来源[S28]」——历史回放给模型的是编号而非长 key |
| AC-12 | ✅ | 本轮无任何工具调用（`sources_seen=0`），正文引用转成上一轮来源 `knowledgesearch_89cb2dea:0`，并绑定到本轮消息 441496；点击角标在停靠面板打开 `OKR绩效管理运营规则 2025.docx` |
| AC-15 | ✅ | 点复制：剪贴板文本无私有区字符、无内部 key、无字面 `[Sn]` |
| AC-16 | ✅ | 刷新后两轮角标照常渲染与解析 |

## 未在界面覆盖

- AC-04（三语默认模板）、AC-07～AC-10、AC-17、AC-19：由单测覆盖（`test/citation/test_handle_stream_converter.py`、`test_daily_handle_rules.py`、`test/workstation/test_daily_citation_tools.py`、`test/common/test_image_view_react_loop.py`）
- AC-20（知识空间 / 频道不变）：由 `test/citation/test_citation_prompt_rules.py`、`test/channel`、知识空间对话引用用例覆盖，未在界面回归

## 观察

1. **思考内容里有字面 `[S28]`**：模型的 reasoning（折叠的「已深度思考」）会提到编号。转换只作用于回答正文，思考内容原样展示。展开思考时用户能看到 `[S28]`，与 spec AC-05「任何时刻都看不到已识别编号」的字面有出入，待定是否处理（见交付说明）。
2. **首次知识库检索失败**：第 1 轮第一次检索返回 Milvus `service unavailable`（后端刚重启、向量库连接冷启动），与本 Feature 无关；模型随后重试成功。
