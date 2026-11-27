# 固定采购入口运行合同

2026-11-11；目标为独立HTTP API取数、一个采购Skill在Chat中分析和直接展示。平台配置、文件接入、脚本及Chat自然语言效果分别验收；本文件不宣称部署或模型验收完成。模型平时只需SKILL.md中的短调用，不默认读本手册或源码。

## 调用与首次导入

Chat模型看到的采购专用代码执行器输入只有`{"request": <结构化动作>}`；服务端固定调用procurement.run(request)，验证协议后直接呈现answer并终止当前图执行。模型不编写Python、不查脚本或批次路径。此包装仅针对启用本采购Skill的任务；是否真实绑定及图终止必须另有平台运行证据，不能由terminal文本推定已经实现。代码不读取服务器配置、不联网、不接收凭据。

离线维护可用以下短调用，不能作为Chat中未接通固定执行器时的自动绕行：

~~~python
import runpy
result = runpy.run_path("skills/procurement-history/scripts/procurement.py")["run"](request)
~~~

cwd为当前任务工作区。run只返回envelope、不主动print；CI包装负责协议sentinel及输出解析。

首次请求：

~~~json
{"action":"history","model":"BMS10-146 TYPE I","match_mode":"exact","page_files":["uploads/procurement-api/<receipt中的真实文件名>.json"]}
~~~

原生API接入层将每页完整MK响应保真保存至 `uploads/procurement-api/<uuid>.json`，回执给raw_json_file、query、分页及snapshot元数据。模型只传当前对话真实回执路径；可有文件工具前导斜杠，入口会转为工作区相对路径。兼容旧 `large_tool_results/<id>.json` 原始页句柄，不读取其他目录。不能从read_file文本抄录、重建JSON或猜文件名。页文件按第1页至末页排列；缺页、乱序、重复、异常包裹、非JSON或快照漂移均终止，不自动修补。

match_mode默认exact；regex须给reference_model用户原始目标，代码只用于最多3型号字符串相似度排序，不代表可替代性。首次直接问供应商用action="suppliers"，可附purchaser；初始已确认筛选放set。取齐分页和导入校验复用import_api_response，完整空结果直接no_records并结束，不重复API查询。

## 固定状态与续问

固定registry为 `uploads/procurement-runtime/session-registry.json`，保存当前查询、原始输入签名、快照版本、每型号独立batch/session绑定、last_action和view。原始文件、批次、会话及完整内部结果不作为下载交付。只在新的完整查询导入时load一次；已有状态的续问由一次run恢复并执行单动作，不重复load或filter后show。重复传入相同原始输入也不会重新load。

~~~json
{"action":"filter","set":{"date_from":"2025-01-01","date_to":"2025-12-31"}}
~~~

其他动作：history重显历史；show可改sort/page/page_size；compare用positions或line_ids；suppliers可带purchaser；reset只在明确清空条件时用。多型号默认分别作用全部；compare必须通过target_model选择唯一候选。target_model仅选择当前已返回型号，不是新的API查询条件。换型号须重新取得本次API文件；仍适用的已确认筛选显式传set，入口回显，不能借用旧型号数据。

入口复用batch_session的筛选、排序、记录映射及名录lookup。filter结果已是最终视图，不再show；比较严格映射上一有效价格展示，供应商视图后旧价格序号不可继续比较。非法动作不覆盖有效会话；多个型号本轮动作有一项失败时恢复本轮原有session，避免部分更新。批次指纹变化、缺失或损坏状态是技术错误，不默默reload或解释为无历史。

平台须把本Chat的uploads内部状态在下一轮恢复到代码工作区；工作区本身必须按当前用户/Chat隔离。本地registry和文件锁防止本目录混用，不等于已验证平台终端用户身份隔离。历史工具页并非每轮都要读取；恢复续问不读取原始API文件或整个名录。

## 终态输出

所有调用返回：

~~~json
{"protocol":"procurement-fixed-entry-v1","status":"final","outcome":"ok","terminal":true,"next_action":"none","answer":"<代码生成的中文Markdown>","models":[{"model":"<型号>","active_filters":{},"counts":{},"source":{}}]}
~~~

protocol固定为procurement-fixed-entry-v1，供服务端识别完整协议。status为final或user_clarification；outcome区分ok、no_records、信息/输入不足或具体错误。terminal始终true，next_action始终none；CI包装应验证完整envelope并在框架侧直接结束，不能只依赖模型自觉停止。信息不足本身是完整结果，不触发额外扫描名录、读取源码或换路径重试。需要用户选择/确认时answer给最少澄清问题，其余错误明确结束。最终直接呈现answer，不重算、不生成下载文件、不复述整个JSON。仅一次有依据的参数纠正可重调，不无限重试。

models只含紧凑状态、数量、分页及来源元数据；当前页全部业务行只在answer表格出现一次。完整引擎结果内部保留，不打印129列、不重复summary.latest_confirmed_records、不硬截字符串。保留命中/展示数量、后续页提示、行依据、条件差异和数据限制；分页从未冒充全量展示。

比较按用户选择顺序的第1条作基准：差额=比较明细单价－基准明细单价；比值=比较明细单价÷基准明细单价，四位小数，基准为0不计算比值。条件/数值不完整一致时均不计算。不能将引擎最大最小差额错标成某条记录的有符号差。

供应商/名录只用qualification_lookup兼容load/lookup接口；assets/qualification-index.json为资源入口，v2小manifest指向CSV，不让模型读取整表。空客查QPL、商飞查QSL、其他跳过；缺原厂、主体/产品范围/有效版本不明时正常返回信息不足，approval_verdict保持空。资料版本、证据行/页、限制和返回证据数保留，截选证据时披露，绝不自动认定合格。

## 验收边界

前置检查：首次完整JSON句柄及分页、隔离执行、固定入口资源、状态恢复、名录资源与权限。实际Chat多轮至少覆盖首次历史、追加/撤销筛选、排序后按序号比较、供应商及三类甲方、空记录、信息不足、3候选分离和错误终止。脚本通过不能替代自然语言Chat验收；来源为授权样例，不代表客户完整生产历史。

当前v0.5.4：history显式切回历史；show/filter保持当前视图，suppliers用于供应商及其价格排序。本轮明确甲方时必须传purchaser，其他甲方也不省略；省略保留旧值。QPL/QSL按指定白名单过滤后分页，未列入不在推荐表中；历史未删除。见business-contract.md末节。v0.7.0起suppliers视图附“供应商推荐”排名与首选，无历史型号按物料从QPL/QSL推荐；explain_limits topic=sourcing给出当前型号推荐。规则见business-contract.md「供应商推荐 v0.7.0」。


## 2026-11-26 历史查询与显式供应商意图边界

history及历史视图的show/filter/reset只返回历史明细、价格、比较条件与来源，不执行供应商查询、名录核验或生成候选；compare也不附推荐。精确无历史和近似无历史在history意图下只走型号核对及结束流程；仅明确suppliers或explain_limits topic=sourcing才生成供应商/名录结果。历史后明确要供应商沿用当前完整批次，无需重新取API。已有候选遇到型号查询、甲方或筛选范围变化及筛选空结果仍按原规则失效，不因暂时转历史视图或撤销筛选恢复旧编号；同范围历史展示不生成或重编号候选。近似选择、批量隔离、确认和撤销规则保持。
