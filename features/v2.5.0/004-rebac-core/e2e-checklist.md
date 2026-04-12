# E2E 验证清单: F004 ReBAC Permission Engine Core

**测试环境**: http://192.168.106.114:3001 (Platform) / http://192.168.106.114:7860/docs (API Docs)
**前置条件**: 后端 + OpenFGA 运行中，默认管理员 admin/Bisheng@top1

## API 手动验证

### AC-08: Docker Compose OpenFGA 服务
- [ ] `docker compose up openfga` 启动成功
- [ ] `curl http://localhost:8080/healthz` 返回 200
- [ ] OpenFGA Playground 可访问: http://localhost:3000

### AC-09: FGAManager 启动时自动初始化
- [ ] 启动后端: `python -m bisheng --dev`
- [ ] 查看日志: "FGAClient initialized: store=xxx model=xxx"
- [ ] 查看 OpenFGA stores: `curl http://localhost:8080/stores` — bisheng store 存在
- [ ] 重启后端，store 不重复创建（日志显示 "Found existing OpenFGA store"）

### AC-04: FailedTuple 补偿机制
- [ ] 停止 OpenFGA 服务: `docker stop bisheng-openfga`
- [ ] 通过 API 执行授权操作（管理员给某用户授权）
- [ ] 查看 MySQL: `SELECT * FROM failed_tuple WHERE status='pending'` — 有记录
- [ ] 重新启动 OpenFGA: `docker start bisheng-openfga`
- [ ] 启动 Celery beat: `.venv/bin/celery -A bisheng.worker.main beat -l info`
- [ ] 等待 30 秒，再查 MySQL: `SELECT * FROM failed_tuple WHERE status='succeeded'` — 补偿成功
- [ ] 验证 OpenFGA 中元组已写入

### AC-07: ChangeHandler → OpenFGA 集成
- [ ] 通过 API 创建部门: `POST /api/v1/departments`
- [ ] 查看 OpenFGA: `curl -X POST http://localhost:8080/stores/{store_id}/read -d '{"tuple_key":{"object":"department:{id}"}}'` — parent 元组存在
- [ ] 通过 API 添加部门成员: `POST /api/v1/departments/{id}/members`
- [ ] 查看 OpenFGA member 元组已写入
- [ ] 通过 API 创建用户组: `POST /api/v1/user_groups`
- [ ] 查看 OpenFGA admin 元组已写入

## 回归检查
- [ ] 工作流创建、编辑、删除正常
- [ ] 知识库创建、上传文件正常
- [ ] 助手创建和对话正常
- [ ] 系统管理页面正常加载
- [ ] 不同角色（管理员/普通用户）登录后界面正确
- [ ] 无 console 错误
