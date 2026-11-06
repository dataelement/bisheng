> 源自中国匠心，希望我们能像 [Deepseek]、[黑神话：悟空] 团队一样，给世界带来更多美好。

<img src="https://dataelem.com/bs/face.png" alt="Bisheng banner">

<p align="center">
    <a href="https://dataelem.feishu.cn/wiki/ZxW6wZyAJicX4WkG0NqcWsbynde"><img src="https://img.shields.io/badge/docs-Wiki-brightgreen"></a>
    <img src="https://img.shields.io/github/license/dataelement/bisheng" alt="license"/>
    <img src="https://img.shields.io/docker/pulls/dataelement/bisheng-frontend" alt="docker-pull-count" />
    <a href=""><img src="https://img.shields.io/github/last-commit/dataelement/bisheng"></a>
    <a href="https://star-history.com/#dataelement/bisheng&Timeline"><img src="https://img.shields.io/github/stars/dataelement/bisheng?color=yellow"></a> 
</p>
<p align="center">
  <a href="./README.md">简体中文</a> |
  <a href="./README_EN.md">English</a> |
  <a href="./README_JPN.md">日本語</a> |
  <a href="./README_ES.md">Español</a> |
  <a href="./README_PT.md">Português</a> |
  <a href="./README_RU.md">Русский</a>
</p>

<p align="center">
  <a href="https://trendshift.io/repositories/717" target="_blank"><img src="https://trendshift.io/api/badge/repositories/717" alt="dataelement%2Fbisheng | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>
</p>
<div class="column" align="middle">
  <!-- <a href="https://bisheng.slack.com/join/shared_invite/"> -->
    <!-- <img src="https://img.shields.io/badge/Join-Slack-orange" alt="join-slack"/> -->
  </a>
  <!-- <img src="https://img.shields.io/github/license/bisheng-io/bisheng" alt="license"/> -->
  <!-- <img src="https://img.shields.io/docker/pulls/bisheng-io/bisheng" alt="docker-pull-count" /> -->
</div>


BISHENG是一款 <b>开源的企业级一站式 Agent 平台</b>，专注办公效率与企业 AI 应用落地，已有大量行业头部组织及世界 500 强企业在使用。

### 重要更新：BISHENG 客户端重磅发布

BISHENG 桌面端基于 DeepSeek Harness（DSH）开发，与 BISHENG 平台协同，为企业提供一整套开源、可私有化部署、自主可控的企业级 Agent 平台方案。

简单来说，你可以把它理解为 WorkBuddy／豆包工作的开源替代方案，让企业把 AI 能力真正掌握在自己手中。

![BISHENG 网页端、桌面端与手机端展示](docs/images/readme/bisheng-platform-overview.png)

[下载 BISHENG 客户端](https://dshdesktop.com/zh/enterprise/)

若需要对客户端进行改造（比如更换 LOGO），可基于[客户端开源代码](https://github.com/dataelement/bisheng-desktop)改造。

> BISHENG 团队于 DSH 发布当晚第一时间开源了 DSH 的桌面客户端（[dshdesktop.com](https://dshdesktop.com/)）。BISHENG 客户端基于 DSHDesktop 开发。截至目前，DSHDesktop 已获得 90 万+下载、17.4K GitHub ⭐️。个人用户可以使用 DSHDesktop。
>
> [DSHDesktop 官网](https://dshdesktop.com/zh/)

## 特点

1. **🖥️ BISHENG 客户端：连接本地工作与企业云端**

   - **Chat 与 Work 两种工作方式**：Chat 支持知识问答与云端多步任务；Work 在获准的本地目录中整理材料，生成可编辑的 Word、Excel、PPT，并根据反馈持续修改。
   - **企业资源按身份开放**：使用企业账号调用获准的模型、API/MCP 工具、技能与知识空间，也可从应用中心打开已发布的助手和工作流；知识检索继续检查空间与文件权限。
   - **模型与积分集中管理**：管理员统一配置模型授权、月度积分和调用记录；Chat 与 Work 的企业模型调用共用当前用户的积分账本，用户可查看余额与用量。
   - **企业扩展统一分发**：管理员集中导入插件和工作台，员工按企业配置与授权获取使用。

2. **🛠️ 应用工场：把 Vibe App 发布给团队**

   - **把业务需求做成应用**：将报名表、项目台账、部门看板等需求做成专门的页面，让同事从应用中心打开使用。
   - **从本地开发到团队使用**：提交本地或由 Coding Agent 辅助开发的应用，经预检、密钥扫描、构建和发布审批后，再设置使用范围，发布到应用中心。
   - **复用平台能力**：应用可按需复用平台登录与访问者身份，接入模型和知识资源，减少重复建设；具体能力与配置要求以对应版本说明为准。

   ![BISHENG 应用工场的 Vibe App 发布管理界面](docs/images/readme/bisheng-vibe-app.png)

3. **🚀 任务模式：面向多步骤复杂工作的通用 Agent**
   你给出目标，按需附上文件、知识库、工具和技能，它会拆解任务、逐步执行，最后交付报告、PPT、Excel 或 Word。

   - 🧠 **任务规划 + 子 Agent 并行**：主 Agent 动态生成任务清单、跟踪进度，把独立调研交给子 Agent 并行完成。
   - 🙋 **人机交互（Human in the loop）**：遇到只有你知道的关键信息，任务暂停等你回答。
   - 🧰 **技能（Skill）即插即用**：内置 PPT、Excel、Word 三个技能包，开箱即用；也可以从本地或 GitHub 导入团队自己的技能。
   - 📎 **结论可溯源**：报告带引用角标，点击后打开原文，并定位到被引用的段落。
   <p align="center"><img src="docs/images/readme/task-mode.png" alt="task-mode"></p>

4. **📚 知识空间：企业版团队知识库**

   - 🗂️ **有序组织**：支持多级文件夹、标签、卡片与列表视图，支持关键词和标签联合检索。
   - 👥 **团队共建**：可以按权限模板（所有者/管理者/编辑者/查看者）邀请成员，也可以发布到知识广场供他人加入。超级管理员可以为部门一键开通「部门知识空间」。
   - 🔐 **权限细到单个文件**：空间、文件夹、文件三级共用一套权限模板，可以一次授权给个人、部门（含子部门）或用户组。文件夹和文件默认继承上级权限，也可以单独设置。
   - 💬 **AI 问答**：可以针对单篇文档提问，也可以基于整个空间提问；回答标注引用来源，点开即可查看原文及溯源定位。
   <p align="center"><img src="docs/images/readme/knowledge-space.png" alt="knowledge-space"></p>

5. **📡 频道订阅：外部资讯每天自动送达，有价值的一键存成知识**

   - 📰 **主题频道**：把公众号和网站聚合成主题频道，每天自动更新，可以再分子频道。
   - 🎯 **精准过滤**：自定义规则过滤标题和正文，只留下相关资讯。
   <p align="center"><img src="docs/images/readme/channel.png" alt="channel"></p>

6. **🧩 独具特色的 [BISHENG workflow](https://dataelem.feishu.cn/wiki/R7HZwH5ZGiJUDrkHZXicA9pInif)**

   - **独立、完备的应用编排框架**：不区分 chatflow 和 workflow，多轮对话和自动化处理可以混在同一个流程里。
   - **Human in the loop**：流程执行到中途可以等人输入、确认或修改。
   - **成环、并行、批量运行自由组合**：画圈即成环（大多数同类产品不支持成环），并列即并行，多选即批量，适合文档审核、固定版式报告生成等复杂场景。
   <p align="center"><img src="https://dataelem.com/bs/bisheng_workflow.png" alt="workflow"></p>

7. **🏢 企业级特性：企业 AI 落地需要的管控能力**

   - **客户端统一管理**：管理员集中配置客户端可用的模型、技能、API/MCP 工具与知识空间，按企业配置和资源权限开放给员工；通过企业插件市场分发插件和工作台，并统一管理月度积分、调用用量与审计记录。
   - **部门和用户管理**：维护组织架构、用户和配额。
   - **功能与资源权限分开管理**：RBAC 通过角色控制功能菜单与操作；ReBAC 控制知识空间、文件夹和单个文件的访问，可按个人、部门（含下级部门）或用户组授权。文件夹和文件默认继承上级权限，也可独立设置。
   - **操作审批**：知识空间加入、频道订阅、菜单权限申请等操作可以走审批，审批流程和节点可自定义。
   - **审计**：记录会话内容和系统操作日志，可按人、时间、模块追溯。
   - **统计看板**（商业版）：预置用户活跃度、应用使用、token 用量、知识库使用等数据看板。
   - **API Key 权限边界**：管理员为服务账号签发密钥，配置有效期、接口权限，并授予可访问的应用、知识库等资源。接口权限决定能做什么，资源授权决定能对哪些资源操作；获得密钥不等于拥有整个平台权限。

     ![BISHENG API Key 签发与权限配置界面](docs/images/readme/bisheng-api-key.png)

   - **信创适配**：同时支持 MySQL 和达梦 DM8。
   - 以及 SSO/LDAP、高可用部署方案、安全审查、流量控制、监控统计、漏洞扫描修复。
   <p align="center"><img src="https://dataelem.com/bs/pro.png" alt="enterprise"></p>

   ![BISHENG 企业管理后台的客户端积分与用量页面](docs/images/readme/bisheng-enterprise-management.png)

8. **🔍 高精度文档解析**：5年海量数据沉淀，高精度文档解析模型支持免费私有化部署使用，包括高精度印刷体、手写体与生僻字识别模型、表格识别模型、版式分析模型、印章模型...
   <p align="center"><img src="https://dataelem.com/bs/ocr.png" alt="ocr"></p>

## 快速安装 

安装BISHENG前请先确保满足以下条件：
- CPU >= 8 Core
- RAM >= 32 GB
- Docker 19.03.9+
- Docker Compose 1.25.1+
> 除了BISHENG前后端，我们默认还会安装第三方组件ES、Milvus、Onlyoffice

下载BISHENG代码
```bash
# 如果系统中有git命令，可以直接下载BISHENG代码
git clone https://github.com/dataelement/bisheng.git
# 进入安装目录
cd bisheng/docker

# 如果系统没有没有git命令，可以下载BISHENG代码zip包
wget https://github.com/dataelement/bisheng/archive/refs/heads/main.zip
# 解压并进入安装目录
unzip main.zip && cd bisheng-main/docker
```
启动BISHENG
```bash
# 进入bisheng/docker或bisheng-main/docker目录，执行
docker compose -f docker-compose.yml -p bisheng up -d
```
启动后，在浏览器中访问 http://IP:3001 ，出现登录页，进行用户注册。默认第一个注册的用户会成为系统admin。

其他安装部署问题参考：[私有化部署](https://dataelem.feishu.cn/wiki/BSCcwKd4Yiot3IkOEC8cxGW7nPc)


## 感谢 

感谢我们的贡献者：

<a href="https://github.com/dataelement/bisheng/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=dataelement/bisheng" />
</a>


<br>
Bisheng 采用了以下依赖库:

- 感谢开源LLM应用开发库 [langchain](https://github.com/langchain-ai/langchain)。
- 感谢开源langchain可视化工具 [langflow](https://github.com/logspace-ai/langflow)。
- 感谢开源非结构化数据解析引擎 [unstructured](https://github.com/Unstructured-IO/unstructured)。
- 感谢开源LLM微调框架 [LLaMA-Factory](https://github.com/hiyouga/LLaMA-Factory) 。


## 社区与支持 
欢迎加入我们的交流群

<img src="https://www.dataelem.com/nstatic/qrcode.png" alt="Wechat QR Code">


<!--
## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=dataelement/bisheng&type=Date)](https://star-history.com/#dataelement/bisheng&Date)
-->

## 服务企业

BISHENG 已服务众多行业头部企业，以下为部分客户。

![中国气象局、汇丰银行、博世、屈臣氏、中国移动、中粮集团](docs/images/readme/bisheng-customer-logos-row-1.png)

![首钢集团、中国宝武、中金公司、中国出口信用保险公司、中国石油、中国工商银行](docs/images/readme/bisheng-customer-logos-row-2.png)

![重庆银行、中国电建、华泰证券、华夏银行、辽宁金控、中国民生银行](docs/images/readme/bisheng-customer-logos-row-3.png)

![龙华资本、苏交科、中信银行、中英人寿、北汽集团、中债资信](docs/images/readme/bisheng-customer-logos-row-4.png)

## 企业咨询

如需了解 BISHENG 企业部署、桌面客户端接入、产品演示或商务合作，欢迎联系我们。

[填写飞书表单，联系 BISHENG 团队](https://dataelem.feishu.cn/share/base/form/shrcnVow7GQwwKYEBCD41Bu5qoh)
