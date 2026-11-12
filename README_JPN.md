> 中国のものづくりの精神から。DeepSeek や黒神話：悟空のチームのように、世界により多くの素晴らしいものを届けたいと願っています。

<img src="docs/images/readme/bisheng-banner-en.png" alt="Bisheng banner">

<p align="center">
    <a href="https://dataelem.feishu.cn/wiki/ZxW6wZyAJicX4WkG0NqcWsbynde"><img src="https://img.shields.io/badge/docs-Wiki-brightgreen"></a>
    <img src="https://img.shields.io/github/license/dataelement/bisheng" alt="license"/>
    <img src="https://img.shields.io/docker/pulls/dataelement/bisheng-frontend" alt="docker-pull-count" />
    <a href="https://github.com/dataelement/bisheng/commits"><img src="https://img.shields.io/github/last-commit/dataelement/bisheng"></a>
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

BISHENG は、**オープンソースの企業向けオールインワン Agent プラットフォーム**です。オフィス業務の効率化と企業での AI アプリケーションの活用に注力し、さまざまな業界の大手組織や Fortune 500 企業に利用されています。

### 重要アップデート：BISHENG クライアントを公開

BISHENG デスクトップクライアントは DeepSeek Harness（DSH）を基盤に開発され、BISHENG プラットフォームと連携することで、オープンソースでプライベート環境にデプロイでき、自社で管理・制御できる企業向け Agent プラットフォームの包括的なソリューションを提供します。

簡単に言えば、WorkBuddy／豆包工作のオープンソースの代替として、企業が AI の能力を自らの手で管理できるようにするものです。

![BISHENG の Web・デスクトップ・モバイル画面](docs/images/readme/bisheng-platform-overview.png)

[BISHENG クライアントをダウンロード](https://dshdesktop.com/zh/enterprise/) · [BISHENG クライアントの使い方](https://dataelem.feishu.cn/wiki/BWSMwdc2Ciwif4kfe5HcyGHgn3b#share-QZrMdHGRdokzWixRl6vc30w1n8P)

クライアントをカスタマイズする場合（ロゴの変更など）は、[クライアントのオープンソースコード](https://github.com/dataelement/bisheng-desktop)を基に変更できます。

> BISHENG チームは、DSH が公開されたその夜に、DSH のデスクトップクライアント（[dshdesktop.com](https://dshdesktop.com/)）をいち早くオープンソースとして公開しました。BISHENG クライアントは DSHDesktop を基盤に開発されています。現在、DSHDesktop は 90 万件以上のダウンロードと GitHub で 17.4K のスター ⭐️ を獲得しています。個人ユーザーは DSHDesktop を利用できます。
>
> [DSHDesktop 公式サイト](https://dshdesktop.com/zh/)

## 特徴

1. **🖥️ BISHENG クライアント：ローカル作業と企業のクラウドを接続**

   - **Chat と Work の 2 つの作業方法**：Chat はナレッジ Q&A とクラウド上の複数ステップのタスクに対応します。Work は許可されたローカルディレクトリで資料を整理し、編集可能な Word、Excel、PPT を作成して、フィードバックに応じた修正を続けられます。
   - **アカウントの権限に従って企業リソースを利用**：企業アカウントで許可されたモデル、API/MCP ツール、スキル、ナレッジスペースを利用し、アプリセンターで公開済みのアプリを開けます。ナレッジ検索は、その従業員がアクセス権を持つスペースとファイルの内容だけを返します。
   - **モデルとクレジットを一元管理**：管理者はモデルの利用権限、月間クレジット、呼び出し履歴を管理します。Chat と Work での企業モデルの呼び出しは、現在のユーザーの同じクレジット台帳に記録され、残高と利用量を確認できます。
   - **企業向け拡張機能を一括配布**：管理者がプラグインとワークベンチをまとめてインポートし、従業員は企業の設定と権限に従って利用します。

2. **🛠️ ホスティングアプリ：チームで開発したアプリを同僚に公開**

   - **業務上のニーズをアプリに**：申し込みフォーム、プロジェクト台帳、部門ダッシュボードなどの専用ページを作成します。アプリの公開後、権限を持つ従業員はアプリセンターで「アプリに入る」をクリックすると、新しいタブでそのまま利用できます。再ログインは不要です。
   - **ローカルで開発してプラットフォームに提出**：開発者は bisheng コマンドラインツールをインストールし、サービスアカウントのキーでログインして、ローカルでアプリを開発・デバッグします。Coding Agent の支援を受けることもできます。開発者はアプリマニフェストにランタイム、リソースプラン、利用するプラットフォームのモデルとナレッジベースを宣言し、アプリをプラットフォームに提出します。プラットフォームは提出されたアプリに対して事前チェック、シークレットスキャン、ビルドを行います。
   - **承認後に公開**：承認者は承認センターでアプリのソースファイルツリーを確認し、アプリをプレビューしてから、承認または却下を決めます。
   - **オーナーによる一元管理**：アプリのオーナーは「構築 → アプリ」で、リソースプランの確認、公開範囲の設定、サードパーティのシークレットの登録、アプリデータのオンライン閲覧・編集、公開・非公開・削除を行えます。
   - **プラットフォームの機能を再利用**：プラットフォームが現在のアクセスユーザーの ID をアプリに渡すため、アプリは独自のログインを作る必要がありません。アプリはプラットフォームのモデルを呼び出し、アクセスユーザーの権限に従ってナレッジベースを検索できます。

   ![BISHENG ホスティングアプリの公開管理画面](docs/images/readme/bisheng-vibe-app.png)

3. **🚀 タスクモード：複数ステップの複雑な作業に対応する汎用エージェント**
   目標を伝え、必要に応じてファイル、ナレッジベース、ツール、スキルを添付すると、エージェントがタスクを分解して順に実行し、最後に HTML、Markdown、PPT、Excel、Word のファイルを納品します。

   - 🧠 **タスク計画 + サブエージェントの並列実行**：メインエージェントがタスクリストを動的に作成して進捗を管理し、独立した調査はサブエージェントに任せて並列に進めます。
   - 🙋 **Human in the loop**：あなたしか知らない重要な情報が必要になると、タスクを一時停止して回答を待ちます。
   - 🧰 **スキル（Skill）をそのまま追加**：Word、Excel、PPT、HTML レポートの 4 つのスキルパックを内蔵し、すぐに使えます。チーム独自のスキルをローカルや GitHub からインポートすることもできます。
   - 📎 **結論の出典を追跡可能**：レポートには引用マークが付き、クリックすると原文を開いて引用箇所を表示します。
   <p align="center"><img src="docs/images/readme/task-mode.png" alt="task-mode"></p>

4. **📚 ナレッジスペース：企業向けチームナレッジベース**

   - 🗂️ **整理しやすい構成**：多階層フォルダ、タグ、カード表示とリスト表示に対応し、キーワードとタグを組み合わせて検索できます。
   - 👥 **チームで共同構築**：権限テンプレート（所有者／管理者／編集者／閲覧者）でメンバーを招待できます。ナレッジ広場に公開して、他のユーザーに参加してもらうこともできます。スーパー管理者は部門ごとに「部門ナレッジスペース」をワンクリックで作成できます。
   - 🔐 **ファイル単位の権限管理**：スペース、フォルダ、ファイルの 3 階層で同じ権限テンプレートを使い、個人、部門（下位部門を含む）、ユーザーグループにまとめて権限を付与できます。フォルダとファイルは既定で上位の権限を継承し、個別に設定することもできます。
   - 💬 **AI Q&A**：1 つのドキュメントにも、スペース全体にも質問できます。回答には引用元が付き、クリックすると原文の該当箇所を表示します。
   <p align="center"><img src="docs/images/readme/knowledge-space.png" alt="knowledge-space"></p>

5. **📡 チャンネル購読：外部ニュースを毎日自動で受け取り、価値ある記事はワンクリックでナレッジに保存**

   - 📰 **テーマチャンネル**：WeChat 公式アカウントや Web サイトをテーマ別のチャンネルにまとめ、毎日自動で更新します。サブチャンネルも作成できます。
   - 🎯 **精密なフィルタリング**：カスタムルールでタイトルと本文をフィルタリングし、関連する記事だけを残します。
   <p align="center"><img src="docs/images/readme/channel.png" alt="channel"></p>

6. **🧩 独自の [BISHENG workflow](https://dataelem.feishu.cn/wiki/R7HZwH5ZGiJUDrkHZXicA9pInif)**

   - **独立した完全なオーケストレーションフレームワーク**：chatflow と workflow を区別せず、多ターン対話と自動処理を同じフローに組み込めます。
   - **Human in the loop**：フローの実行途中で、人の入力、確認、修正を待つことができます。
   - **ループ、並列、バッチ実行を自由に組み合わせ**：円を描けばループ（多くの類似製品はループに非対応）、並べれば並列、複数選択すればバッチ処理になります。ドキュメント審査や固定レイアウトのレポート生成などの複雑なシナリオに適しています。
   <p align="center"><img src="https://dataelem.com/bs/bisheng_workflow.png" alt="workflow"></p>

7. **🏢 エンタープライズ機能：企業で AI を導入するために必要な管理機能**

   - **クライアントの一元管理**：管理者は BISHENG クライアントで利用できるモデル、スキル、API/MCP ツール、ナレッジスペースをまとめて設定し、企業向けプラグインマーケットでプラグインやワークベンチを配布し、モデルの利用権限、月間クレジット、呼び出し履歴を一元管理します。
   - **部門とユーザーの管理**：組織構造、ユーザー、クォータを管理します。
   - **機能とリソースの権限を分けて管理**：RBAC のロールで機能メニューと操作を制御します。ReBAC はナレッジスペース、フォルダ、個別ファイルへのアクセスを制御し、個人、部門（下位部門を含む）、ユーザーグループに権限を付与できます。フォルダとファイルは既定で上位の権限を継承し、個別に設定することもできます。
   - **承認フロー**：ナレッジスペースへの参加、チャンネル購読、メニュー権限の申請などに承認を設定でき、承認フローとノードはカスタマイズできます。
   - **監査**：会話内容とシステム操作ログを記録し、ユーザー、時間、モジュール別に追跡できます。
   - **統計ダッシュボード**（商用版）：ユーザーのアクティブ度、アプリ利用、token 使用量、ナレッジベース利用などのダッシュボードを用意しています。
   - **API キーの権限範囲**：管理者はサービスアカウント用のキーを発行し、有効期限と API の操作権限を設定して、利用可能なアプリやナレッジベースなどのリソースを指定します。API の操作権限が「何ができるか」を、リソースへの権限が「どの対象を操作できるか」を決めます。キーを取得しても、プラットフォーム全体へのアクセス権は得られません。

     ![BISHENG API キーの発行と権限設定画面](docs/images/readme/bisheng-api-key.png)

   - **国産 IT 基盤（信創）対応**：MySQL と達夢（Dameng）DM8 の両方に対応しています。
   - そのほか、SSO/LDAP、高可用性デプロイ、コンテンツセキュリティ審査、トラフィック制御、モニタリングと統計、脆弱性スキャンと修正に対応しています。
   <p align="center"><img src="https://dataelem.com/bs/pro.png" alt="enterprise"></p>

   ![BISHENG 企業管理画面のクライアント用クレジットと利用量](docs/images/readme/bisheng-enterprise-management.png)

8. **🔍 高精度ドキュメント解析**：5 年間蓄積した大量の高品質データで学習した高精度ドキュメント解析モデルを、無料でプライベート環境にデプロイできます。高精度な印刷文字・手書き文字・難読文字の認識モデル、表認識モデル、レイアウト解析モデル、印鑑モデルなどを含みます。
   <p align="center"><img src="https://dataelem.com/bs/ocr.png" alt="ocr"></p>


## クイックスタート

BISHENG をインストールする前に、以下の条件を満たしていることを確認してください：

- CPU >= 8 コア
- RAM >= 32 GB
- Docker がインストールされ、起動していること
- Docker Compose（V2 推奨）
- Bash

デフォルトのデプロイには MySQL、Redis、MinIO、OpenFGA、ES、Milvus などが含まれます。OnlyOffice はオプションで、基本構成では起動しません。

次のいずれかの方法で BISHENG をダウンロードします：

```bash
git clone https://github.com/dataelement/bisheng.git
cd bisheng
```

Git がない場合は、ZIP ファイルをダウンロードして展開します：

```bash
wget https://github.com/dataelement/bisheng/archive/refs/heads/main.zip
unzip main.zip
cd bisheng-main
```

リポジトリのルートディレクトリでインストーラーを実行します：

```bash
bash docker/install.sh
```

初回実行時に `docker/.env.example` から `docker/.env` を生成し、設定の検証、イメージレジストリへのログイン、イメージの取得、サービスの起動を行います。既存の `.env` は保持されます。Compose の設定には `.env` が必要なため、`docker compose up` を直接実行する前にインストーラーを実行してください。デプロイにはビルド済みイメージを使用し、ダウンロードしたソースコードはコンパイルしません。

サービスの状態と起動ログを確認します：

```bash
cd docker
docker compose ps
docker compose logs -f backend backend_worker
```

サービスの準備ができたら、ブラウザで `http://サーバーIP:3001` にアクセスしてユーザー登録を行います。最初に登録したユーザーがシステム管理者になります。その後、モデルを設定してください。

Gateway はデフォルトでは無効です。ホスティングアプリの実行環境には追加設定が必要です。Gateway、ホスティングアプリ、OnlyOffice、ARM イメージ、デプロイ設定の詳細は [Docker デプロイガイド](docker/README.md) を参照してください。

すべての機能（BISHENG クライアント、ホスティングアプリ、ファインチューニングなど）を有効にするには、ドキュメントをご参照ください：[プライベート環境へのデプロイ](https://dataelem.feishu.cn/wiki/BSCcwKd4Yiot3IkOEC8cxGW7nPc)

## 謝辞
このリポジトリは [langchain](https://github.com/langchain-ai/langchain)、[unstructured](https://github.com/Unstructured-IO/unstructured) および [LLaMA-Factory](https://github.com/hiyouga/LLaMA-Factory) の恩恵を受けています。素晴らしい作品に感謝します。

**貢献者に感謝します：**

<a href="https://github.com/dataelement/bisheng/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=dataelement/bisheng" />
</a>

## コミュニティと連絡先
ディスカッショングループへの参加を歓迎します。

<img src="https://www.dataelem.com/nstatic/qrcode.png" alt="Wechat QR Code">

<!--
## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=dataelement/bisheng&type=Date)](https://star-history.com/#dataelement/bisheng&Date)
-->

## 導入実績

BISHENG は、さまざまな業界の大手企業に導入されています。以下は導入先の一部です。

![中国気象局、HSBC、ボッシュ、ワトソンズ、中国移動、中糧集団](docs/images/readme/bisheng-customer-logos-row-1.png)

![首鋼集団、中国宝武、中金公司、中国輸出信用保険公司、中国石油、中国工商銀行](docs/images/readme/bisheng-customer-logos-row-2.png)

![重慶銀行、中国電建、華泰証券、華夏銀行、遼寧金控、中国民生銀行](docs/images/readme/bisheng-customer-logos-row-3.png)

![龍華資本、蘇交科、中信銀行、中英人寿、北汽集団、中債資信](docs/images/readme/bisheng-customer-logos-row-4.png)

## 企業向けお問い合わせ

BISHENG の企業向けデプロイ、デスクトップクライアント連携、製品デモ、ビジネス連携について、お気軽にお問い合わせください。

[飛書（Feishu）フォームから BISHENG チームに問い合わせる](https://dataelem.feishu.cn/share/base/form/shrcnVow7GQwwKYEBCD41Bu5qoh)
