# 验证 Verification：ETL4LM PDF 图片高清提取

## 结论

- Status: `verified`
- Date: `2026-07-15`
- Result: F055 的新增能力、兼容路径和资源边界已通过自动化验证。

## 自动化证据

| 验证项 | 命令/范围 | 结果 |
|---|---|---|
| 专项测试 | `pytest test/knowledge/rag/test_pdf_image_extractor.py test/knowledge/rag/test_etl4lm_image_extraction.py -q` | 28 passed |
| RAG 回归 | `pytest test/knowledge/rag --ignore=test/knowledge/rag/test_mineru.py --ignore=test/knowledge/rag/test_paddleocr.py -q` | 37 passed |
| Pipeline 回归 | `pytest test/knowledge/test_knowledge_file_pipeline_shougang.py -q` | 1 passed |
| 配置回归 | `pytest test/knowledge/test_version_management_config.py -q` | 3 passed |
| 新增文件 Ruff | extractor 与两个专项测试文件，全规则 | passed |
| 变更文件基础 Ruff | 全部变更 Python 文件，`E/F/I`，沿用项目 `E501` ignore | passed |
| 编译检查 | 四个生产 Python 文件 `compileall` | passed |
| 架构守卫 | 四个生产 Python 文件 | 三个 RAG 文件无输出；settings 命中既有 RULE-7 warning |
| Diff 检查 | `git diff --check` | passed |

## Acceptance Coverage

| Requirement | 证据摘要 | 状态 |
|---|---|---|
| REQ-001 | 原始 JPEG 字节/尺寸、唯一候选、多图、扫描背景、旋转显示矩阵、安全文件名 | PASS |
| REQ-002 | 144/200/300 DPI、clip 区域、非法/越界 bbox、旋转页、像素上限 | PASS |
| REQ-003 | bbox 数值不变、MinIO URL 契约不变 | PASS |
| REQ-004 | 三策略、默认值/非法值、Legacy、retain_images、非 PDF Legacy | PASS |
| REQ-005 | 成功日志字段、fallback reason、渲染异常传播 | PASS |
| REQ-006 | 请求 payload 不变、embedded 路径零渲染、像素限制 | PASS |

## 已知基线问题

完整执行 `test/knowledge/rag` 时有 2 个失败，均为既有测试环境问题：

- `test_mineru.py` 硬编码不存在的 `/Users/zhangguoqing/works/bisheng/src/backend/test/knowledge/rag/test1.pdf`。
- `test_paddleocr.py` 使用同一不存在路径。

这两个测试未进入本 Feature 的通过统计；排除后其余 37 项全部通过。

`settings.py` 架构守卫命中仓库原有 `secret_key` 字面量。本 Feature 仅新增 ETL4LM 图片配置，不新增或修改密钥。

## 未覆盖的外部验证

- 未连接真实 ETL4LM 服务和 MinIO；专项测试通过 HTTP/路径契约与本地字节验证覆盖。
- 未对历史文件批量重解析；该行为明确不在 F055 范围内。
- 建议提测使用包含内嵌照片、扫描 PDF、组合图和旋转图的真实样本进行视觉对比。
