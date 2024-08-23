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


BISHENG毕昇 是一款 <b>开源</b> LLM应用开发平台，主攻<b>企业场景</b>， 已有大量行业头部组织及世界500强企业在使用。

“毕昇”是活字印刷术的发明人，活字印刷术为人类知识的传递起到了巨大的推动作用。我们希望“BISHENG毕昇”同样能够为智能应用的广泛落地提供有力支撑。欢迎大家一道参与。


## 特点 

1. 专为企业应用而生：文档审核、固定版式报告生成、多智能体协作、规范制度更新差异比对、工单问答、客服辅助、会议纪要生成、简历筛选、通话记录分析、非结构化数据治理、知识挖掘、数据分析...平台支持高复杂度企业应用场景构建，支持数百个组件与数千个参数的深度调优。
<p align="center"><img src="https://dataelem.com/bs/chat.png" alt="sence1"></p>

2. 企业级特性是应用落地的基本保障：安全审查、基于角色的细颗粒度权限管理、用户组管理、分组流量控制、SSO/LDAP、漏洞扫描修复、高可用部署方案、监控、统计...
<p align="center"><img src="https://dataelem.com/bs/pro.png" alt="sence2"></p>

3. 高精度文档解析：5年海量数据沉淀，高精度文档解析模型支持免费私有化部署使用，包括高精度印刷体、手写体与生僻字识别模型、表格识别模型、版式分析模型、印章模型
<p align="center"><img src="https://dataelem.com/bs/ocr.png" alt="sence3"></p>

4. 大量企业场景落地最佳实践分享社区：开放的应用案例与最佳实践库。
<p align="center"><img src="https://dataelem.com/bs/sence.png" alt="sence4"></p>


## 快速安装 

安装BISHENG前请先确保满足以下条件：
- CPU >= 8 Core
- RAM >= 32 GB
- Docker 19.03.9+
- Docker Compose 1.25.1+
> 除了BISHENG前后端，我们默认还会安装第三方组件ES、Milvus、Onlyoffice

下载BISHENG代码
```bash
# 如果系统中有git命令，可以直接下载毕昇代码
git clone https://github.com/dataelement/bisheng.git
# 进入安装目录
cd bisheng/docker

# 如果系统没有没有git命令，可以下载毕昇代码zip包
wget https://github.com/dataelement/bisheng/archive/refs/heads/main.zip
# 解压并进入安装目录
unzip main.zip && cd bisheng-main/docker
```
启动BISHENG
```bash
# 进入bisheng/docker或bisheng-main/docker目录，执行
docker-compose up -d
```
启动后，在浏览器中访问 http://IP:3001 ，出现登录页，进行用户注册。默认第一个注册的用户会成为系统admin。

其他安装部署问题参考：[私有化部署](https://dataelem.feishu.cn/wiki/BSCcwKd4Yiot3IkOEC8cxGW7nPc)


## 资源
- [📄应用案例/场景库](https://dataelem.feishu.cn/wiki/ZfkmwLPfeiAhQSkK2WvcX87unxc)
- [📄经验技巧](https://dataelem.feishu.cn/wiki/OWFRwknFaiIMajke4m5cFeLrnie)
- [📄功能使用说明](https://dataelem.feishu.cn/wiki/WxH6wubbAiBkRIkSEyecmpDMnjF)
- [📄BISHENG Blog](https://dataelem.feishu.cn/wiki/BiNowcaYWilewdksXQ5cZl3tnzy)


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