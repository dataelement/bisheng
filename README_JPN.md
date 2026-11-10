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
1. **🚀 タスクモード：複数ステップの複雑な作業に対応する汎用エージェント**
   目標を伝え、必要に応じてファイル、ナレッジベース、ツール、スキルを添付すると、エージェントがタスクを分解して順に実行し、最後にレポート、PPT、Excel、Word を納品します。

   - 🧠 **タスク計画 + サブエージェントの並列実行**：メインエージェントがタスクリストを動的に作成して進捗を管理し、独立した調査はサブエージェントに任せて並列に進めます。
   - 🙋 **Human in the loop**：あなたしか知らない重要な情報が必要になると、タスクを一時停止して回答を待ちます。
   - 🧰 **スキル（Skill）をそのまま追加**：PPT、Excel、Word の 3 つのスキルパックを内蔵し、すぐに使えます。チーム独自のスキルをローカルや GitHub からインポートすることもできます。
   - 📎 **結論の出典を追跡可能**：レポートには引用マークが付き、クリックすると原文を開いて引用箇所を表示します。
   <p align="center"><img src="docs/images/readme/task-mode.png" alt="task-mode"></p>

2. **📚 ナレッジスペース：企業向けチームナレッジベース**

   - 🗂️ **整理しやすい構成**：多階層フォルダ、タグ、カード表示とリスト表示に対応し、キーワードとタグを組み合わせて検索できます。
   - 👥 **チームで共同構築**：権限テンプレート（所有者／管理者／編集者／閲覧者）でメンバーを招待できます。ナレッジ広場に公開して、他のユーザーに参加してもらうこともできます。スーパー管理者は部門ごとに「部門ナレッジスペース」をワンクリックで作成できます。
   - 🔐 **ファイル単位の権限管理**：スペース、フォルダ、ファイルの 3 階層で同じ権限テンプレートを使い、個人、部門（下位部門を含む）、ユーザーグループにまとめて権限を付与できます。フォルダとファイルは既定で上位の権限を継承し、個別に設定することもできます。
   - 💬 **AI Q&A**：1 つのドキュメントにも、スペース全体にも質問できます。回答には引用元が付き、クリックすると原文の該当箇所を表示します。
   <p align="center"><img src="docs/images/readme/knowledge-space.png" alt="knowledge-space"></p>

3. **📡 チャンネル購読：外部ニュースを毎日自動で受け取り、価値ある記事はワンクリックでナレッジに保存**

   - 📰 **テーマチャンネル**：WeChat 公式アカウントや Web サイトをテーマ別のチャンネルにまとめ、毎日自動で更新します。サブチャンネルも作成できます。
   - 🎯 **精密なフィルタリング**：カスタムルールでタイトルと本文をフィルタリングし、関連する記事だけを残します。
   <p align="center"><img src="docs/images/readme/channel.png" alt="channel"></p>

4. **🧩 独自の [BISHENG workflow](https://dataelem.feishu.cn/wiki/R7HZwH5ZGiJUDrkHZXicA9pInif)**

   - **独立した完全なオーケストレーションフレームワーク**：chatflow と workflow を区別せず、多ターン対話と自動処理を同じフローに組み込めます。
   - **Human in the loop**：フローの実行途中で、人の入力、確認、修正を待つことができます。
   - **ループ、並列、バッチ実行を自由に組み合わせ**：円を描けばループ（多くの類似製品はループに非対応）、並べれば並列、複数選択すればバッチ処理になります。ドキュメント審査や固定レイアウトのレポート生成などの複雑なシナリオに適しています。
   <p align="center"><img src="https://dataelem.com/bs/bisheng_workflow.png" alt="workflow"></p>

5. **🏢 エンタープライズ機能：企業で AI を導入するために必要な管理機能**

   - **部門とユーザーの管理**：組織構造とユーザーを管理し、ロールごとに利用できる機能メニューとクォータを設定できます。
   - **RBAC + ReBAC の二重権限モデル**：ロールで使える機能を、ReBAC でアクセスできるリソースを制御します（ファイル単位まで）。
   - **承認フロー**：ナレッジスペースへの参加、チャンネル購読、メニュー権限の申請などに承認を設定でき、承認フローとノードはカスタマイズできます。
   - **監査**：会話内容とシステム操作ログを記録し、ユーザー、時間、モジュール別に追跡できます。
   - **統計ダッシュボード**（商用版）：ユーザーのアクティブ度、アプリ利用、token 使用量、ナレッジベース利用などのダッシュボードを用意しています。
   - **オープン API**：サービスアカウントと API キーでアプリやナレッジベースなどの API を呼び出せます。従業員本人の権限で、その従業員に代わって呼び出すこともできます。
   - **DSH Desktop の企業連携**（商用版）：従業員はプラットフォームのアカウントでデスクトップクライアントにログインし、BISHENG で設定したモデルをそのまま使えます。管理者はユーザーごと・月ごとにモデルの利用枠を割り当てられます。
   - **国産 IT 基盤（信創）対応**：MySQL と達夢（Dameng）DM8 の両方に対応しています。
   - そのほか、SSO/LDAP、高可用性デプロイ、コンテンツセキュリティ審査、トラフィック制御、モニタリングと統計、脆弱性スキャンと修正に対応しています。
   <p align="center"><img src="https://dataelem.com/bs/pro.png" alt="enterprise"></p>

6. **🔍 高精度ドキュメント解析**：5 年間蓄積した大量の高品質データで学習した高精度ドキュメント解析モデルを、無料でプライベート環境にデプロイできます。高精度な印刷文字・手書き文字・難読文字の認識モデル、表認識モデル、レイアウト解析モデル、印鑑モデルなどを含みます。
   <p align="center"><img src="https://dataelem.com/bs/ocr.png" alt="ocr"></p>

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
docker compose -f docker-compose.yml -p bisheng up -d
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
