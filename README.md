<img src="https://dataelem.com/bs/face.png" alt="Bisheng banner">

<p align="center">
    <a href="https://dataelem.feishu.cn/wiki/ZxW6wZyAJicX4WkG0NqcWsbynde"><img src="https://img.shields.io/badge/docs-Wiki-brightgreen"></a>
    <img src="https://img.shields.io/github/license/dataelement/bisheng" alt="license"/>
    <img src="https://img.shields.io/docker/pulls/dataelement/bisheng-frontend" alt="docker-pull-count" />
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

1. <b>Designed for Enterprise Applications</b>: Document review, fixed-layout report generation, multi-agent collaboration, policy update comparison, support ticket assistance, customer service assistance, meeting minutes generation, resume screening, call record analysis, unstructured data governance, knowledge mining, data analysis, and more. 

The platform supports the construction of <b>highly complex enterprise application scenarios</b> and offers <b>deep optimization</b> with hundreds of components and thousands of parameters.
<p align="center"><img src="https://dataelem.com/bs/chat.png" alt="sence1"></p>

2. <b>Enterprise-grade</b> features are the fundamental guarantee for application implementation: security review, RBAC, user group management, traffic control by group, SSO/LDAP, vulnerability scanning and patching, high availability deployment solutions, monitoring, statistics, and more.
<p align="center"><img src="https://dataelem.com/bs/pro.png" alt="sence2"></p>

3. <b>High-Precision Document Parsing</b>: Our high-precision document parsing model is trained on a vast amount of high-quality data accumulated over past 5 years. It includes high-precision printed text, handwritten text, and rare character recognition models, table recognition models, layout analysis models, and seal models., table recognition models, layout analysis models, and seal models. You can deploy it privately for free.
<p align="center"><img src="https://dataelem.com/bs/ocr.png" alt="sence3"></p>

4. A community for sharing best practices across various enterprise scenarios: An open repository of application cases and best practices.


## Quick start 

Please ensure the following conditions are met before installing BISHENG:
- CPU >= 8 Core
- RAM >= 32 GB
- Docker 19.03.9+
- Docker Compose 1.25.1+
> In addition to installing BISHENG, we will also install the following third-party components by default: ES, Milvus, and Onlyoffice.

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
docker-compose up -d
```
After the startup is complete, access http://IP:3001 in the browser. The login page will appear, proceed with user registration. 

By default, the first registered user will become the system admin. 

For more installation and deployment issues, refer to:：[私有化部署](https://dataelem.feishu.cn/wiki/BSCcwKd4Yiot3IkOEC8cxGW7nPc)

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