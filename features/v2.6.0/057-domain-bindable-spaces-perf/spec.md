# Feature: 业务域候选空间专用查询优化

**Feature ID**: `057-domain-bindable-spaces-perf`  
**Status**: Implemented  
**Mode**: Performance / API optimization  
**Created**: 2026-07-16  
**优先级**: P1  
**所属版本**: v2.6.0

## 概述

门户业务域管理当前通过通用空间聚合接口加载候选空间。该接口会按调用用户计算成员关系、OpenFGA 可见范围、文件数和部门元数据，远超业务域绑定所需的数据范围。

本功能新增仅供管理员调用的轻量查询接口，只返回当前已发布的公共、部门知识空间；门户 BFF 保留自身管理员校验后改调该接口。

详细内容见：

- [requirements.md](./requirements.md)
- [design.md](./design.md)
- [tasks.md](./tasks.md)

## 范围

- 包含：BiSheng 专用查询、门户 BFF 上游切换、两端回归测试与验证记录。
- 不包含：前端候选列表缓存/请求去重、数据库迁移、普通用户空间列表与通用 `/grouped` 接口改造。

## 风险

- 未发布空间将不再作为业务域候选空间返回，这是已确认的有效空间规则。
- 新接口暴露公共、部门空间名称，因此必须在 BiSheng 服务端强制管理员校验，不能依赖门户传参。

## 当前状态

- BiSheng 专用接口与门户 BFF 上游切换已完成。
- 定向测试、编译和差异检查通过；详情见 [verification.md](./verification.md)。
- BiSheng `knowledge_space_service.py` 的全文件 Ruff 检查存在本功能范围外的既有问题，未以该结果阻断本次交付。
