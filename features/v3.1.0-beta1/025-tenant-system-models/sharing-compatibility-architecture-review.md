**PROCEED — 两个 blocker 已在设计中补齐。**

- 第 16 行将预览 pin 纳入命令摘要，并在 provider 锁内校验、创建 reservation，解决完成关闭后被旧修复命令重新开启的竞态。
- 第 14 行通过零增量 adoption 产生真实完成计划，再读取新增模型快照，补齐操作关联生产者，且不扩大接收范围。

无剩余设计 blocker。原 spec/design 的冲突陈述仍应按约同步。实现验证需覆盖“预览后关闭”“adoption 后关闭”“失败重试原 reservation”三种交错。本结论仅针对设计。
