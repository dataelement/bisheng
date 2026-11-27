# Token Exchange 规格评审

评审范围：spec.md + request.md；alpha1 基线 572d5ecf77。独立评审按仓库 sdd-review 的 spec 清单执行。

初次结果：没有确定 high；3 项 medium。

1. 原输入允许类型未在 AC 明确：已在 AC-01 指定 A 所属毕昇 OAuth Access Token，AC-05 显式排除 ID Token 和 Refresh Token。
2. 撤销与在途交换寿命上界：已在 AC-08 将处理耗时纳入300秒上界；AC-10 明确并发结果截止不晚于变更提交后300秒。
3. What 混入缓存处理：已从 AC-10 移除缓存机制表述，只保留对外可验证的状态生效行为。

待用户确认的产品决策：300秒上限、显式指定scope、管理员策略接口首版不含新增UI，以及OAuth身份断言与ApiCredential的窄契约边界。未将本地验签的既有选择当作已批准300秒，也未把ApiCredential约束声明为自动豁免。

复核结论：三项 medium 已闭合，独立评审无确定 high 问题，修订项无残留 high/medium。此结论不构成用户批准或既有契约豁免。

状态：规格已完成评审，待用户规格确认，未开始设计或实现。
