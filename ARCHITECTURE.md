# GitLab AI Inception Agent 実装方針

## 概要

EC2上にDockerでセルフホストしたGitLabに対して、AIがインセプションフェーズを自動進行する仕組み。
IssueにラベルをつけるだけでAIとの対話が始まり、要件定義サマリーまで自動生成する。

---

## アーキテクチャ

```
Issueに ai-inception ラベル付与
        │
        │ Webhook (Issues events / Note events)
        ▼
FastAPI Webhook Receiver  ← EC2上のDockerコンテナとしてGitLabと同居
        │
        │ Pipeline Trigger API
        ▼
GitLab CI Job (inception_agent.py)
        │
        ├─ GitLab API → Issue・コメント取得
        ├─ Claude API → 返答生成
        └─ GitLab API → Issueにコメント投稿
```

### コンポーネント構成（docker-compose）

| サービス | 役割 |
|---|---|
| `gitlab` | GitLab本体 (CE) |
| `gitlab-runner` | CI Jobの実行環境 |
| `webhook-receiver` | FastAPI。Webhookを受けてPipeline Triggerに変換 |

---

## フェーズ設計

### インセプションフェーズ

| トリガー | 処理 |
|---|---|
| `ai-inception` ラベル付与 | AIが最初の質問をIssueにコメント投稿 |
| Issueへのコメント | AIが会話を継続 |
| AIが要件定義完了と判断 | `ai-inception-done` ラベルを自動付与、要件定義サマリーを投稿 |

### コンストラクションフェーズ（今後実装）

`ai-inception-done` ラベルをトリガーに起動。インセプションの要件定義サマリーを元に以下をAIが実行する。

- タスク分解・計画
- ブランチ作成・コード実装
- MR作成・レビューコメント対応
- MR承認は人間が行う

---

## 設計上の決定事項

### 会話履歴の管理：DBレス設計

毎回GitLab APIでIssueのコメント一覧を取得し、Claude APIの `messages` 形式に変換する。
BotコメントはHTMLコメントマーカー `<!-- ai-inception-bot -->` で識別する。

**理由:** DynamoDB/Redisなどの追加インフラが不要でコストゼロ。インセプションフェーズの会話量なら全履歴をコンテキストに載せても問題ない。

### Webhook変換層：EC2同居のFastAPI

GitLab WebhookのペイロードはPipeline Trigger APIと仕様が異なるため変換層が必要。
EC2上のDockerコンテナとしてGitLabと同居させることで追加のAWSリソース（Lambda等）を使わない。

**理由:** コスト最小化。同一EC2内の通信なのでレイテンシも無視できる。

### リアルタイム応答：Webhook駆動

ScheduledパイプリングではなくWebhook駆動にすることでコメントへの応答を数秒以内に行う。

### 無限ループ防止

`BOT_USER_ID` をWebhook receiverに設定し、Bot自身のコメントによるWebhookイベントを無視する。

---

## ファイル構成

```
gitlab-ai-inception/
├── docker-compose.yml
├── .env.example
├── .gitignore
├── webhook-receiver/
│   ├── Dockerfile
│   ├── main.py          # FastAPI。Webhookを受けてラベル判定・Pipeline起動
│   └── requirements.txt
└── gitlab-ci/
    ├── .gitlab-ci.yml   # CIジョブ定義。triggerイベントのみ起動
    └── inception_agent.py  # AIエージェント本体
```

---

## 環境変数

| 変数名 | 説明 | 設定場所 |
|---|---|---|
| `GITLAB_TOKEN` | Bot userのPersonal Access Token | `.env` / CI Variables |
| `WEBHOOK_SECRET` | Webhook検証用シークレット | `.env` |
| `TRIGGER_TOKEN` | Pipeline Trigger Token | `.env` |
| `GITLAB_PROJECT_ID` | 対象プロジェクトのID | `.env` |
| `BOT_USER_ID` | Bot userのID（無限ループ防止） | `.env` |
| `ANTHROPIC_API_KEY` | Anthropic API Key | CI Variables（Masked） |

---

## セットアップ手順

1. EC2インスタンスを起動（推奨: t3.medium以上、Ubuntu 22.04）
2. Docker / Docker Composeをインストール
3. `docker compose up -d` でGitLab起動（初回5分ほどかかる）
4. GitLab上でBot userを作成しPersonal Access Tokenを発行（Developerロール以上）
5. `Settings > CI/CD > Pipeline triggers` でTrigger Tokenを発行
6. GitLab Runnerを登録
7. `.env` を `.env.example` を元に作成
8. `Settings > Webhooks` でWebhookを設定
   - URL: `http://<EC2 IP>:8001/webhook`
   - Events: Issue events / Comments
9. `Settings > CI/CD > Variables` に `ANTHROPIC_API_KEY` と `GITLAB_TOKEN` を設定
10. Issueを作成し `ai-inception` ラベルを付与して動作確認

---

## 今後の拡張

- コンストラクションフェーズの実装（ブランチ作成・コード実装・MR作成）
- AWS-DLCワークフローとの連携
- MRレビュー・レビュー対応の自動化
- 複数プロジェクト対応
