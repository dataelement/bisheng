# F035 POC Spike（Wave 0 · §7 必验门槛）

deepagents 适配层关键技术假设的可运行验证。**不在 CI 跑**（依赖外部中间件/模型），由 Lead/Track owner 手动执行，结论入 `RESULTS.md`，阻塞设计成立的项必须有红/绿结论。

| 脚本 | 门槛 | 关联 Track | 依赖 |
|------|------|-----------|------|
| `poc_p1_backend_injection.py` | P1 自定义 FilesystemBackend 注入 | C/A | 无（纯 deepagents） |
| `poc_p2_subgraph_streaming.py` | P2 subgraphs=True 子图冒泡 + namespace 不串流 | A | 无（纯 langgraph） |
| `poc_p3_redis_checkpointer_resume.py` | P3 park-and-release + 跨重启续跑保真 | B | Redis（config.yaml redis_url） |
| `poc_p4_skill_call_reason.py` | P4 call_reason 遵从率 + Skill 命中率 ≥95% | A/D | 可用中文模型 |
| `poc_p5_required_files.py` | P5 required_files 声明遵从率 + 修复率 | C/A | 可用中文模型 + E2B |

## 运行

```bash
# 从 src/backend 运行（脚本自带 sys.path 引导，模型类脚本需 bisheng 包）
cd src/backend
uv run python scripts/035-linsight-deepagents/poc_p1_backend_injection.py
uv run python scripts/035-linsight-deepagents/poc_p2_subgraph_streaming.py
uv run python scripts/035-linsight-deepagents/poc_p3_redis_checkpointer_resume.py
uv run python scripts/035-linsight-deepagents/poc_p4_skill_call_reason.py [model_id]
uv run python scripts/035-linsight-deepagents/poc_p5_required_files.py [model_id]
```

P4/P5 接受可选 `model_id`（DB 中 online 的 llm 模型）；不给则探测一组候选。无可用模型时输出 `BLOCKED`（非失败）。
