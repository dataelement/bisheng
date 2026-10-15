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
1. **🚀 Task Mode: a general-purpose agent for complex, multi-step work**
   You give it a goal and, if needed, attach files, knowledge bases, tools and skills. The agent breaks the goal into tasks, runs them step by step, and delivers a report, PPT, Excel or Word file.

   - 🧠 **Task planning + parallel sub-agents**: The main agent builds a task checklist, tracks progress, and gives independent research tasks to sub-agents that run in parallel.
   - 🙋 **Human in the loop**: When the agent needs information that only you have, the task pauses until you answer.
   - 🧰 **Plug-and-play skills**: Three built-in skill packs (PPT, Excel, Word) work out of the box. You can also import your team's own skills from a local file or from GitHub.
   - 📎 **Traceable conclusions**: Reports carry citation markers. Click a marker to open the source and go to the cited passage.
   <p align="center"><img src="docs/images/readme/task-mode.png" alt="task-mode"></p>

2. **📚 Knowledge Space: an enterprise knowledge base for teams**

   - 🗂️ **Organized content**: Multi-level folders, tags, card and list views, and search by keyword and tag together.
   - 👥 **Built by the team**: Invite members with a permission template (Owner / Manager / Editor / Viewer), or publish the space to the Knowledge Square so that others can join. A super admin can create a Department Space for a department in one step.
   - 🔐 **Permissions down to a single file**: Spaces, folders and files use the same set of permission templates. You can grant access to a person, a department (including its sub-departments) or a user group in one step. Folders and files inherit permissions from their parent by default, and you can also set them separately.
   - 💬 **AI Q&A**: Ask questions about one document or about the whole space. Answers show their sources; click a source to open the original text at the cited location.
   <p align="center"><img src="docs/images/readme/knowledge-space.png" alt="knowledge-space"></p>

3. **📡 Channels: external news delivered every day, and saved as knowledge in one click**

   - 📰 **Topic channels**: Combine WeChat official accounts and websites into topic channels that update every day. A channel can have sub-channels.
   - 🎯 **Precise filtering**: Custom rules filter titles and body text, so only relevant articles stay.
   <p align="center"><img src="docs/images/readme/channel.png" alt="channel"></p>

4. **🧩 Unique [BISHENG Workflow](https://dataelem.feishu.cn/wiki/R7HZwH5ZGiJUDrkHZXicA9pInif)**

   - **Independent and complete orchestration framework**: There is no split between chatflow and workflow. Multi-turn conversation and automated processing can be in the same flow.
   - **Human in the loop**: A running flow can stop and wait for a person to give input, confirm, or make changes.
   - **Loops, parallel branches and batch runs in any combination**: Draw a circle to make a loop (most similar products do not support loops), place nodes side by side to run them in parallel, and select multiple items to run a batch. This fits complex scenarios such as document review and fixed-layout report generation.
   <p align="center"><img src="https://dataelem.com/bs/bisheng_workflow.png" alt="workflow"></p>

5. **🏢 Enterprise-grade features: the controls that enterprise AI needs**

   - **Department and user management**: Manage the organization structure and users. Roles control which feature menus are available and set quotas.
   - **RBAC + ReBAC permission model**: Roles control which features a user can use. ReBAC controls which resources a user can access, down to a single file.
   - **Approvals**: Joining a knowledge space, subscribing to a channel, requesting menu permissions and other actions can require approval. You can customize approval flows and nodes.
   - **Audit**: Records conversation content and system operation logs, searchable by user, time and module.
   - **Dashboards** (commercial edition): Preset dashboards for user activity, application usage, token usage, knowledge base usage and more.
   - **Open API**: Call applications, knowledge bases and other APIs with service accounts and API keys, or call them on behalf of an employee with that employee's own permissions.
   - **DSH Desktop enterprise access** (commercial edition): Employees sign in to the desktop client with their platform account and use the models configured in BISHENG. Admins can allocate model quotas per user per month.
   - **Xinchuang (domestic IT stack) support**: Supports both MySQL and Dameng DM8.
   - Also: SSO/LDAP, high-availability deployment, content security review, traffic control, monitoring and statistics, and vulnerability scanning and fixes.
   <p align="center"><img src="https://dataelem.com/bs/pro.png" alt="enterprise"></p>

6. **🔍 High-precision document parsing**: Our document parsing models are trained on a large amount of high-quality data collected over 5 years, and you can deploy them privately for free. They include high-precision models for printed text, handwriting and rare characters, table recognition, layout analysis, and seals.
   <p align="center"><img src="https://dataelem.com/bs/ocr.png" alt="ocr"></p>

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

