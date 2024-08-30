以下は、あなたが提供したMarkdownコンテンツの日本語翻訳です。

---

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

BISHENGは、エンタープライズシナリオに焦点を当てたオープンなLLMアプリケーションDevOpsプラットフォームです。多くの業界リーディング企業やフォーチュン500企業で使用されています。

「畢昇（Bi Sheng）」は、活版印刷の発明者であり、人類の知識の伝播に重要な役割を果たしました。我々は、BISHENGがインテリジェントアプリケーションの広範な実装に強力なサポートを提供できることを願っています。皆さんの参加を歓迎します。

## 特徴

1. **エンタープライズアプリケーション向けに設計**: ドキュメントレビュー、固定レイアウトレポート生成、マルチエージェント協働、ポリシー更新比較、サポートチケット支援、カスタマーサービス支援、会議議事録生成、履歴書スクリーニング、通話記録分析、非構造化データガバナンス、知識採掘、データ分析など。

プラットフォームは、**高度に複雑なエンタープライズアプリケーションシナリオの構築**をサポートし、**深い最適化**を行い、数百のコンポーネントと数千のパラメータを提供します。
<p align="center"><img src="https://dataelem.com/bs/chat.png" alt="sence1"></p>

2. **エンタープライズグレード**の機能は、アプリケーション実装の基本的な保証です: セキュリティレビュー、RBAC、ユーザーグループ管理、グループごとのトラフィックコントロール、SSO/LDAP、脆弱性スキャンとパッチ適用、高可用性デプロイメントソリューション、モニタリング、統計など。
<p align="center"><img src="https://dataelem.com/bs/pro.png" alt="sence2"></p>

3. **高精度ドキュメント解析**: 私たちの高精度ドキュメント解析モデルは、過去5年間にわたる大量の高品質データに基づいてトレーニングされています。高精度な印刷テキスト、手書きテキスト、稀少文字認識モデル、テーブル認識モデル、レイアウト解析モデル、印鑑モデルを含みます。プライベートに無料で展開することができます。
<p align="center"><img src="https://dataelem.com/bs/ocr.png" alt="sence3"></p>

4. 様々なエンタープライズシナリオにおけるベストプラクティスを共有するコミュニティ: オープンなアプリケーションケースとベストプラクティスのリポジトリ。

## クイックスタート

BISHENGをインストールする前に、以下の条件を満たしていることを確認してください:
- CPU >= 8 コア
- RAM >= 32 GB
- Docker 19.03.9以上
- Docker Compose 1.25.1以上

> BISHENGをインストールする際、デフォルトで以下のサードパーティコンポーネントもインストールされます: ES, Milvus, Onlyoffice。

BISHENGのダウンロード
```bash
git clone https://github.com/dataelement/bisheng.git
# インストールディレクトリに移動
cd bisheng/docker

# システムにgitコマンドがない場合は、BISHENGのコードをzipファイルとしてダウンロードできます。
wget https://github.com/dataelement/bisheng/archive/refs/heads/main.zip
# 解凍してインストールディレクトリに移動
unzip main.zip && cd bisheng-main/docker
```

BISHENGの起動
```bash
docker-compose up -d
```

起動完了後、ブラウザでhttp://IP:3001にアクセスします。ログインページが表示されるので、ユーザー登録を行います。

デフォルトでは、最初に登録されたユーザーがシステム管理者となります。

詳細なインストールおよびデプロイに関する問題は、こちらを参照してください：[私有化部署](https://dataelem.feishu.cn/wiki/BSCcwKd4Yiot3IkOEC8cxGW7nPc)

## 謝辞
このリポジトリは [langchain](https://github.com/langchain-ai/langchain) [langflow](https://github.com/logspace-ai/langflow) [unstructured](https://github.com/Unstructured-IO/unstructured) および [LLaMA-Factory](https://github.com/hiyouga/LLaMA-Factory) の恩恵を受けています。素晴らしい作品に感謝します。

**貢献者に感謝します：**

<a href="https://github.com/dataelement/bisheng/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=dataelement/bisheng" />
</a>

## コミュニティと連絡先
ディスカッショングループへの参加を歓迎します。

<img src="https://www.dataelem.com/nstatic/qrcode.png" alt="Wechat QR Code">

--- 

この翻訳を使用して、Markdownファイルを作成できます。