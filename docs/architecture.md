# GitLab AI Agent アーキテクチャ

## 概要

EC2上にDockerでセルフホストしたGitLabに対して、AIがインセプション〜コンストラクションフェーズを自動進行する仕組み。
IssueにラベルをつけるだけでAIとの対話が始まり、要件定義・コード実装・MR作成まで自動化する。

---

## 全体フロー

```
【インセプションフェーズ】
Issueに ai-inception ラベル付与
        │ Webhook (Issues events)
        ▼
FastAPI Webhook Receiver
        │ Pipeline Trigger API
        ▼
GitLab CI Job: inception_agent.py
        ├─ GitLab API → Issue・コメント取得
        ├─ Claude API (claude-opus-4-7) → 質問生成
        └─ GitLab API → Issueにコメント投稿

    ↕ Q&Aを繰り返す（Webhook → CI → コメント）

AIが要件定義完了と判断
        ├─ Issueにサマリーコメント投稿
        ├─ docs/inception/issue-{N}.md をmainにコミット  ← ハイブリッド設計
        └─ ai-inception-done ラベルを自動付与

【コンストラクションフェーズ】
ai-inception-done ラベル付与
        │ Webhook (Issues events)
        ▼
FastAPI Webhook Receiver
        │ Pipeline Trigger API
        ▼
GitLab CI Job: construction_agent.py（Agenticループ）
        ├─ docs/inception/issue-{N}.md から要件を読み込み
        ├─ list_files / read_file ツール → コードベース調査
        ├─ write_file ツール → ブランチにコードを実装
        └─ create_merge_request ツール → MR作成

【MRレビュー対応】
MRにレビューコメント
        │ Webhook (Note events / MergeRequest)
        ▼
GitLab CI Job: construction_agent.py（レビューモード）
        ├─ コメントを読んでコード修正
        └─ MRに返答コメント投稿
```

---

## コンポーネント構成

### docker-compose サービス

| サービス | 役割 |
|---|---|
| `gitlab` | GitLab CE 本体 |
| `gitlab-runner` | CI Jobの実行環境（Docker executor） |
| `webhook-receiver` | FastAPI。GitLab Webhookを受けてPipeline Triggerに変換 |

### AWS インフラ（CDK管理）

| リソース | 仕様 |
|---|---|
| EC2 | t3.large (8GB RAM) ※t3.mediumはメモリ不足 |
| EBS | 50GB GP3（暗号化） |
| EIP | 固定IPアドレス |
| Security Group | SSH (自宅IPのみ) / HTTP 80 / HTTPS 443 / Git 2222 / Webhook 8001 |
| EventBridge Scheduler | 18:00-24:00 JST のみEC2を起動（コスト削減） |
| AWS Budget | 月$20超過でメールアラート |

---

## フェーズ設計

### インセプションフェーズ

**ハイブリッド方式**（コメントQ&A ＋ MDファイル生成）

| トリガー | 処理 |
|---|---|
| `ai-inception` ラベル付与 | AIが最初の質問をIssueにコメント投稿 |
| Issueへのコメント | AIが会話を継続（1往復ごとにPipeline実行） |
| AIが要件定義完了と判断 | ① Issueにサマリーコメント投稿<br>② `docs/inception/issue-{N}.md` をmainにコミット<br>③ `ai-inception-done` ラベルを自動付与 |

### コンストラクションフェーズ

AI-DLC (AI-Driven Development Life Cycle) に基づいた実装フロー：

1. **Functional Design**: `docs/inception/issue-{N}.md` から要件を読み込み、コードベースを調査
2. **Implementation**: `write_file` ツールでブランチにコードをコミット
3. **MR Creation**: `create_merge_request` ツールでMR作成・Issueに通知
4. **Review Response**: MRコメントを読んで修正・返答

---

## 設計上の決定事項

### 会話履歴の管理：DBレス設計

毎回GitLab APIでIssueのコメント一覧を取得し、Claude APIの `messages` 形式に変換する。
BotコメントはHTMLコメントマーカー `<!-- ai-inception-bot -->` で識別する。

**理由:** DynamoDB/Redisなどの追加インフラが不要でコストゼロ。

### ハイブリッドインセプション

コメントでQ&Aしつつ、完了時に `docs/inception/issue-{N}.md` をリポジトリに保存する。

**理由:** コメントQ&Aはリアルタイム性があり使いやすい。MDファイルはコンストラクションフェーズへの確実な引き継ぎと履歴管理に使える。

### GitLab Runner のネットワーク設定

Runner を `gitlab-ai-inception_default`（docker-compose内部ネットワーク）に接続する。
`CI_SERVER_URL` が GitLab コンテナ名で解決できるため、ECIPへのラウンドトリップが不要。

### 無限ループ防止

`BOT_USER_ID` をWebhook receiverに設定し、Bot自身のコメントによるWebhookイベントを無視する。

### AI-DLC 統合

`aidlc-rules/` ディレクトリがリポジトリに存在する場合、construction_agent.py が自動的に読み込む。
`./scripts/setup-aidlc.sh` で `awslabs/aidlc-workflows` からルールをダウンロードできる。

---

## ファイル構成

```
gitlab-ai-inception/
├── docs/
│   ├── architecture.md              # このファイル
│   ├── gitlab-setup-guide.md        # セットアップ手順
│   ├── TODO.md                      # 進捗チェックリスト
│   └── decisions/                   # 意思決定記録 (ADR)
│       └── 001-ai-dlc-project-structure.md
├── agent/
│   ├── .gitlab-ci.yml               # CIジョブ定義（inception / construction）
│   ├── inception_agent.py           # インセプションエージェント
│   └── construction_agent.py        # コンストラクションエージェント
├── webhook-receiver/
│   ├── main.py                      # FastAPI Webhook受信・Pipeline Trigger
│   ├── Dockerfile
│   └── requirements.txt
├── infra/                           # AWS CDK (TypeScript)
│   ├── bin/app.ts                   # スタック設定（インスタンスタイプ・スケジュール等）
│   └── lib/gitlab-stack.ts          # VPC / EC2 / EIP / SG / Scheduler / Budget
├── scripts/
│   ├── deploy.sh                    # EC2へのrsyncデプロイ
│   └── setup-aidlc.sh               # AI-DLC rulesのセットアップ
├── docker-compose.yml               # GitLab CE + Runner + webhook-receiver
└── .env.example
```

自動生成されるファイル（GitLabリポジトリ内）:
```
docs/inception/
└── issue-{N}.md     # インセプション完了時に自動コミット
```

---

## 環境変数

| 変数名 | 説明 | 設定場所 |
|---|---|---|
| `GITLAB_HOST` | EC2のパブリックIP | `.env` |
| `GITLAB_TOKEN` | ci-bot の Personal Access Token | `.env` / CI Variables |
| `WEBHOOK_SECRET` | Webhook検証用シークレット | `.env` |
| `TRIGGER_TOKEN` | Pipeline Trigger Token | `.env` |
| `GITLAB_PROJECT_ID` | 対象プロジェクトのID | `.env` |
| `BOT_USER_ID` | Bot userのID（無限ループ防止） | `.env` |
| `ANTHROPIC_API_KEY` | Anthropic API Key | CI Variables（Masked） |

---

## コスト試算

| リソース | 月額（スケジュール適用後） |
|---|---|
| EC2 t3.large × 6h/day | ~$16 |
| EBS 50GB GP3 | ~$4 |
| **合計** | **~$20/月** |
