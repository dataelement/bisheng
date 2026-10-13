# MinerU 4.0 E2E 验收清单

**当前结果**：离线 V1 协议到 `Document` 的 PDF/PNG 集成测试及定向回归已通过。2026-10-13 已在独立 MinerU 4.0.12 服务上完成 Basic 档位 PDF、PNG、OFD 以及 Standard 档位 PDF 的真实 V1 接口与 Loader 闭环；完整毕昇中间件、知识库入库及页面验收仍待执行。离线测试文件为 `src/backend/test/knowledge/test_mineru_v4_e2e.py`。后续验收使用专用测试租户、测试知识库及脱敏文件；只清理本次创建的数据。

## 环境准备

- [x] 在目标环境确认 `/v1/health`、`/v1/tiers`：服务版本 4.0.12，最终保留的服务提供 `flash`、`basic`、`standard`、`advanced`，支持 ZIP；仅绑定目标机 `127.0.0.1:18089`，无外网入口，因此未配置 API Key。后续如开放给其他机器，需增加鉴权并在 API 与知识 Worker 进程设置相同的 Key 环境变量。
- [ ] 在毕昇配置中设置 `knowledges.mineru_v4.api_url`、`api_key_env`、`tier` 和需要的 `request_kwargs`；显式把 `loader_provider` 切为 `mineru_v4`。保存前留存原配置以便恢复。
- [ ] 准备原生 PDF、扫描 PDF、PNG/JPEG、OFD，以及含标题、表格、公式、多张图片的脱敏样本。

## 独立接口与 Loader 实测（2026-10-13）

- 目标机 `192.168.106.20` 最终保留测试容器 `mineru-v4-bisheng-standard-test`，使用 MinerU 4.0.12 基础包、ONNX/CPU 小模型和 llama.cpp VLM，按 Standard 档位启动；端口只映射到目标机回环地址。依赖和模型位于 `/nfs-share/node11_public/mineru-v4-bisheng-test`，不改动原有 `mineru:latest`（2.6.8）镜像。模型校验结果为 `MinerU-4_models_onnx: ok` 和 `MinerU2.5-Pro-2605-1.2B-GGUF: ok`。服务设置为自动重启，并限制为 4 CPU、16 GiB 内存和只读容器根文件系统。
- [x] 在临时 Basic 实例上使用当前 `MineruV4Loader` 对一页原生 PDF 发起上传、建任务、轮询和 ZIP 下载：任务完成，得到 `schema=docvortex.middle`、`schema_version=2.0`，正文含标题、表格和公式测试文本；1 页、4 个块、4 个 bbox，并暂存 1 张表格图片。该临时实例已关闭并移除。
- [x] 在临时 Basic 实例上使用当前 `MineruV4Loader` 对 PNG 发起同一闭环：任务完成，OCR 正文为 `MinerU V4 image OCR test 2026`；1 页、1 个块和 1 个 bbox。
- [x] 在临时 Basic 实例上使用现有 `OfdLoader` 把 `sample.ofd` 转成 PDF，再委托当前 `MineruV4Loader` 调用真实服务：任务完成，正文为 `Hello OFD sample`；转换后的预览 PDF 存在，得到 1 个 bbox。
- [x] 在最终保留的 Standard 实例上，以当前 `MineruV4Loader` 和默认 `tier=standard` 重跑一页 PDF：任务完成，得到同一 Middle JSON 协议，1 页、4 个块、4 个 bbox 和 1 张表格图片；服务日志确认 VLM 使用 llama.cpp 引擎。
- 本轮只证明独立服务协议、ZIP 结构和 Loader 转换。尚未通过毕昇 API/Worker、MinIO、知识库入库或前端页面验证；也未测试扫描 PDF、JPEG、多图素材与失败终态。

## 解析、预览和入库（AC-01、AC-04、AC-05、AC-06、AC-10）

- [ ] 在平台知识库分别上传 PDF、图片和 OFD，发起预览并等待终态；确认正文可读、页序正确、上游确实提供的 bbox 可定位、图片 URL 可访问。OFD 的文件预览应展示转换后的 PDF。
- [ ] 打开段落编辑，核对标题、表格、公式和多张图片没有丢失；图片内容能从 MinIO 对象读取，分块引用范围与正文一致。
- [ ] 对含图片的样本关闭“保留图片”后重新预览并入库；确认正文和图注仍可读，正文没有图片占位或未上传的素材链接。再打开该选项，确认子目录图片均能访问。
- [ ] 提交入库后通过知识文件详情或列表确认最终成功状态和 `parse_type=mineru_v4`，再发起问答并打开引用，确认平台和 `/workspace` 客户端均能打开预览和定位。
- [ ] 使用不可达服务、错误 Key、无 ZIP 产物和上游部分完成样本验证失败终态；知识文件不得显示为成功，也不得产生部分正文引用。

## 兼容、缓存与任务时机（AC-02、AC-03、AC-07、AC-08、AC-11）

- [ ] 恢复默认或旧 `mineru` 提供方，上传测试文件；确认使用原有解析链路。历史旧 MinerU 文件与新文件在平台和客户端的聊天引用均可打开。
- [ ] 先用旧提供方生成预览并记下可见分块，再切换到 `mineru_v4` 后提交入库；确认入库正文仍与已看到的预览一致。记录此次文件的 `parse_type`、bbox 与图片来源，按设计中的缓存边界解释可能的来源差异。
- [ ] 使用专用测试队列制造排队窗口，提交任务后切换全局提供方；确认任务实际执行时采用当时生效的配置，无需与提交时保持一致。

## 队列及恢复（AC-09、AC-10）

- [ ] 启用 OCR 专用队列且配置有效新提供方，提交 PDF 与 OFD，确认二者进入专用队列；关闭专用队列或清空外部提供方地址后，OFD 进入普通知识队列。
- [ ] 解析任务运行中重启 MinerU 服务，确认毕昇最终呈现明确失败或现有重试结果；用户刷新预览页面后能够重新发起任务并获取新任务 ID。

## 结果记录

记录每个样本的文件类型、解析来源、预览终态、入库终态、图片/定位可用性、平台与客户端引用结果，以及失败样本的错误信息。除上述独立接口与 Loader 实测外，其余真实环境和页面验收仍未执行，不能把本轮结果视为完整功能验收通过。
