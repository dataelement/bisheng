**Proudly made by Chinese，May we, like the creators of Deepseek and Black Myth: Wukong, bring more wonder and greatness to the world.**

> 源自中国匠心，希望我们能像 [Deepseek]、[黑神话：悟空] 团队一样，给世界带来更多美好。

<img src="https://dataelem.com/bs/face.png" alt="Bisheng banner">

<p align="center">
    <a href="https://dataelem.feishu.cn/wiki/ZxW6wZyAJicX4WkG0NqcWsbynde"><img src="https://img.shields.io/badge/docs-Wiki-brightgreen"></a>
    <img src="https://img.shields.io/github/license/dataelement/bisheng" alt="license"/>
    <a href=""><img src="https://img.shields.io/github/last-commit/dataelement/bisheng"></a>
    <a href="https://star-history.com/#dataelement/bisheng&Timeline"><img src="https://img.shields.io/github/stars/dataelement/bisheng?color=yellow"></a> 
</p>
<p align="center">
  <a href="./README_CN.md">简体中文</a> |
  <a href="./README.md">English</a> |
  <a href="./README_JPN.md">日本語</a>
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


BISHENG is an open LLM application devops platform, focusing on enterprise scenarios. It has been used by a large number of industry leading organizations and Fortune 500 companies.

"Bi Sheng" was the inventor of movable type printing, which played a vital role in promoting the transmission of human knowledge. We hope that BISHENG can also provide strong support for the widespread implementation of intelligent applications. Everyone is welcome to participate.


## Features 
1. **Lingsight, a general-purpose agent with expert-level taste**: Through the [AGL](https://github.com/dataelement/AgentGuidanceLanguage)(Agent Guidance Language) framework, we embed domain experts’ preferences, experience, and business logic into the AI, enabling the agent to exhibit “expert-level understanding” when handling tasks.  
<p align="center"><img src="https://dataelem.com/bs/Linsight.png" alt="sence1"></p>   

2. **Unique [BISHENG Workflow](https://dataelem.feishu.cn/wiki/R7HZwH5ZGiJUDrkHZXicA9pInif)**
   - 🧩 **Independent and comprehensive application orchestration framework**: Enables the execution of various tasks within a single framework (while similar products rely on bot invocation or separate chatflow and workflow modules for different tasks).
   - 🔄 **Human in the loop**: Allows users to intervene and provide feedback during the execution of workflows (including multi-turn conversations), whereas similar products can only execute workflows from start to finish without intervention.
   - 💥 **Powerful**: Supports loops, parallelism, batch processing, conditional logic, and free combination of all logic components. It also handles complex scenarios such as multi-type input/output, report generation, content review, and more.
   - 🖐️ **User-friendly and intuitive**: Operations like loops, parallelism, and batch processing, which require specialized components in similar products, can be easily visualized in BISHENG as a "flowchart" (drawing a loop forms a loop, aligning elements creates parallelism, and selecting multiple items enables batch processing).
   <p align="center"><img src="https://dataelem.com/bs/bisheng_workflow.png" alt="sence0"></p>

3. <b>Designed for Enterprise Applications</b>: Document review, fixed-layout report generation, multi-agent collaboration, policy update comparison, support ticket assistance, customer service assistance, meeting minutes generation, resume screening, call record analysis, unstructured data governance, knowledge mining, data analysis, and more.   
The platform supports the construction of <b>highly complex enterprise application scenarios</b> and offers <b>deep optimization</b> 	with hundreds of components and thousands of parameters.
<p align="center"><img src="https://dataelem.com/bs/chat.png" alt="sence1"></p>

4. <b>Enterprise-grade</b> features are the fundamental guarantee for application implementation: security review, RBAC, user group management, traffic control by group, SSO/LDAP, vulnerability scanning and patching, high availability deployment solutions, monitoring, statistics, and more.
<p align="center"><img src="https://dataelem.com/bs/pro.png" alt="sence2"></p>

5. <b>High-Precision Document Parsing</b>: Our high-precision document parsing model is trained on a vast amount of high-quality data accumulated over past 5 years. It includes high-precision printed text, handwritten text, and rare character recognition models, table recognition models, layout analysis models, and seal models., table recognition models, layout analysis models, and seal models. You can deploy it privately for free.
<p align="center"><img src="https://dataelem.com/bs/ocr.png" alt="sence3"></p>

6. A community for sharing best practices across various enterprise scenarios: An open repository of application cases and best practices.
## Quick start 

Please ensure the following conditions are met before installing BISHENG:
- CPU >= 4 Virtual Cores
- RAM >= 16 GB
- Docker 19.03.9+
- Docker Compose 1.25.1+
> Recommended hardware condition: 18 virtual cores, 48G. In addition to installing BISHENG, we will also install the following third-party components by default: ES, Milvus, and Onlyoffice.

Download BISHENG
```bash
git clone https://github.com/dataelement/bisheng.git
# Enter the installation directory
cd bisheng/docker

# If the system does not have the git command, you can download the BISHENG code as a zip file.
wget https://github.com/dataelement/bisheng/archive/refs/heads/main.zip
# Unzip and enter the installation directory
unzip main.zip && cd bisheng-main/docker
```
Start BISHENG
```bash
docker compose -f docker-compose.yml -p bisheng up -d
```
After the startup is complete, access http://IP:3001 in the browser. The login page will appear, proceed with user registration. 

By default, the first registered user will become the system admin. 

For more installation and deployment issues, refer to:：[Self-hosting](https://dataelem.feishu.cn/wiki/BSCcwKd4Yiot3IkOEC8cxGW7nPc)

## Acknowledgement 
This repo benefits from [langchain](https://github.com/langchain-ai/langchain) [langflow](https://github.com/logspace-ai/langflow) [unstructured](https://github.com/Unstructured-IO/unstructured) and [LLaMA-Factory](https://github.com/hiyouga/LLaMA-Factory) . Thanks for their wonderful works.

<b>Thank you to our contributors：</b>

<a href="https://github.com/dataelement/bisheng/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=dataelement/bisheng" />
</a>



## Community & contact 
Welcome to join our discussion group

<img src="https://www.dataelem.com/nstatic/qrcode.png" alt="Wechat QR Code">


<!--
## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=dataelement/bisheng&type=Date)](https://star-history.com/#dataelement/bisheng&Date)
-->


 驗證結果

  管理員流程:
  1. Platform → 日常模式 → 看到「可用工具 (1/20)」含 web_search,switch 可改 default
  2. 保存 → POST /api/v1/workstation/config 寫入 tools[]
  3. GET /api/v1/workstation/config 讀回 tools[] 正確

  用戶流程(Client):
  1. 打開對話 → bsConfig.tools 加載 → AgentToolSelector 自動按 default_checked 勾選
  2. 發送消息 → payload 含 tools: [...] → 後端分派到 Agent 流
  3. SSE 返回 agent_thinking/agent_answer → useAiChatSSE 新 compat 代碼轉成 :::thinking...:::answer 給現有 renderer 消費
  4. UI 呈現:思考塊 + 最終回覆 (跟舊格式視覺等價)

  遺留 / 已跳過

  - PlusMenu (+ 按鈕分組 files/knowledge-space/org-kb): UX 細化,不阻塞功能
  - Agent 消息的原生渲染: 當前用兼容 mapper 把 agent_* 折回 :::thinking:::answer 格式複用舊 renderer。後續專屬的 AgentMessageBubble /
  ToolCallDisplay 屬於獨立的「渲染改造」任務
  - web_search 在 3003 環境的 API key: 環境問題,非代碼問題


  ----
  幾個小提醒:                                                                                                                                
                                                                                                                                             
  🚀 啟動命令(備忘)                                                                                                                          
  # 後端                                                                                                                                     
  cd /Users/shanghang/dataelem/bisheng/src/backend                                     
  config=$(pwd)/config_3003.yaml PYTHONPATH=./ \                                                                              
  uv run uvicorn bisheng.main:app --host 0.0.0.0 --port 7860 --reload                                                                        
                                                                                                                                             
  # Client (端口 4001,訪問 http://localhost:4001/workspace/__dev/login 登錄)                                                                 
  cd /Users/shanghang/dataelem/bisheng/src/frontend/client && pnpm start                                                                     
                                                                                                                                             
  # Platform (端口 3001)                                                                                                                     
  cd /Users/shanghang/dataelem/bisheng/src/frontend/platform && pnpm start                                                               
                                                                                                                                             
  🐛 萬一遇到問題                                                                                                                            
  - 後端日誌:/tmp/bisheng-backend.log                                                                                                      
  - 改 yaml 配置(如 daily_chat.agent_max_iterations):去 Platform 系統設置或直接調 POST /api/v1/config/save,redis 緩存會自動失效              
  - web_search 工具空配置會被優雅降級,Agent 流仍能跑(只是不調用該工具)                                                                     
  - 若 SSE 流卡住,先看 /tmp/bisheng-backend.log 看是 LLM 還是 LangGraph 問題                                                                 
                                                                                                                                           
  📝 主要新功能驗收清單                                                                                                                      
  1. Platform → 日常模式 → 「可用工具」+「組織知識庫」配置                                                                                   
  2. Client → 對話界面 → 工具下拉 + 結構化思考/工具調用渲染                                                                                  
  3. Client → 訂閱頻道 → 設置 → 「同步至知識空間」                                                                                           
  4. 後端 yaml 改 daily_chat.agent_max_iterations → 立即生效                


