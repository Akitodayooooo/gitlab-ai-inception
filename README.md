# GitLab AI Inception Agent

GitLabのIssueに `ai-inception` ラベルを付けるだけで、AIが要件定義のヒアリングを自動で進めてくれる仕組みです。

## 概要

```
Issueに ai-inception ラベル付与
        │
        │ Webhook (Issues events / Note events)
        ▼
FastAPI Webhook Receiver
        │
        │ Pipeline Trigger API
        ▼
GitLab CI Job (inception_agent.py)
        │
        ├─ GitLab API → Issue・コメント取得
        ├─ Claude API → 返答生成
        └─ GitLab API → Issueにコメント投稿
```

AIはIssueのコメント履歴をすべてコンテキストに乗せて対話を継続します（DBレス設計）。要件定義が完了したと判断すると、構造化されたサマリーを投稿して `ai-inception-done` ラベルを自動付与します。

## ファイル構成

```
├── docs/
│   ├── architecture.md              # システム設計詳細
│   └── decisions/                   # 意思決定記録 (ADR)
│       └── 001-ai-dlc-project-structure.md
├── infra/                           # AWS CDK (TypeScript)
│   ├── bin/app.ts
│   └── lib/gitlab-stack.ts          # VPC / EC2 / EIP / Security Group
├── agent/
│   ├── .gitlab-ci.yml               # CIジョブ定義
│   └── inception_agent.py           # AIエージェント本体 (Claude Opus 4.7)
├── webhook-receiver/
│   ├── main.py                      # FastAPI: Webhook → Pipeline Trigger変換
│   ├── Dockerfile
│   └── requirements.txt
├── scripts/
│   └── deploy.sh                    # EC2へのrsyncデプロイ
├── docker-compose.yml               # GitLab CE + Runner + webhook-receiver
└── .env.example
```

## セットアップ

### 前提条件

- AWS CLI（設定済み）
- Node.js 20+
- Docker / Docker Compose

### 1. インフラ構築 (AWS CDK)

```bash
cd infra
npm install
cdk bootstrap   # 初回のみ
cdk deploy
```

デプロイ後にEC2のIPアドレスとSSH接続コマンドが出力されます。

```
Outputs:
  PublicIP         = 1.2.3.4
  SshKeyCommand    = aws ssm get-parameter --name /ec2/keypair/... > gitlab-ai.pem && chmod 600 gitlab-ai.pem
  SshCommand       = ssh -i gitlab-ai.pem ubuntu@1.2.3.4
  GitlabUrl        = http://1.2.3.4
  WebhookUrl       = http://1.2.3.4:8001/webhook
```

### 2. アプリのデプロイ

```bash
cp .env.example .env
# .env を編集 (GITLAB_HOST に EC2 の IP を設定)

./scripts/deploy.sh
```

GitLabの初回起動には5〜15分かかります。初期パスワードは以下で確認できます。

```bash
ssh -i gitlab-ai.pem ubuntu@<EC2_IP> \
  "docker exec gitlab-ai-inception-gitlab-1 cat /etc/gitlab/initial_root_password"
```

### 3. GitLab初期設定

#### プロジェクトのインポート

1. GitLab に root でログイン
2. `New project > Import project > GitHub` でこのリポジトリ（`gitlab-ai-inception`）をインポート
3. プロジェクトの `Settings > CI/CD > General pipelines > CI/CD configuration file` を `agent/.gitlab-ci.yml` に変更

#### Bot userの作成

1. Bot user（例: `ai-bot`）を Developer ロールで作成
2. Bot userでログインし `Settings > Access Tokens` でPersonal Access Token（`api` scope）を発行

#### トークン類の取得

| 取得場所 | 変数 |
|---|---|
| Bot userのPAT | `GITLAB_TOKEN` |
| `Settings > CI/CD > Pipeline triggers` | `TRIGGER_TOKEN` |
| `Settings > General > Project ID` | `GITLAB_PROJECT_ID` |
| `GET /api/v4/users?username=ai-bot` | `BOT_USER_ID` |

#### `.env` の完成・反映

```bash
# .env を編集後
ssh -i gitlab-ai.pem ubuntu@<EC2_IP> \
  "cd /home/ubuntu/gitlab-ai-inception && docker compose restart webhook-receiver"
```

#### CI/CD Variablesの設定

`Settings > CI/CD > Variables` に以下を登録（`ANTHROPIC_API_KEY` はMaskedにする）

| 変数名 | 説明 |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API Key |
| `GITLAB_TOKEN` | Bot userのPersonal Access Token |

#### GitLab Runner登録

```bash
docker exec -it gitlab-ai-inception-gitlab-runner-1 \
  gitlab-runner register \
  --url http://<EC2_IP> \
  --executor docker \
  --docker-image python:3.12-slim
```

#### Webhookの設定

`Settings > Webhooks` で以下を設定します。

- **URL**: `http://<EC2_IP>:8001/webhook`
- **Secret token**: `.env` の `WEBHOOK_SECRET` と同じ値
- **Trigger**: Issues events / Comments にチェック

### 4. 動作確認

1. GitLabでIssueを作成
2. `ai-inception` ラベルを付与
3. AIが最初の質問をコメント投稿（数秒以内）
4. コメントで返答すると会話が継続
5. AIが要件定義完了と判断するとサマリーを投稿し、`ai-inception-done` ラベルが付与される

## 環境変数一覧

| 変数名 | 設定場所 | 説明 |
|---|---|---|
| `GITLAB_HOST` | `.env` | EC2のIPアドレスまたはドメイン |
| `GITLAB_TOKEN` | `.env` + CI Variables | Bot userのPersonal Access Token |
| `WEBHOOK_SECRET` | `.env` | Webhook検証用シークレット |
| `TRIGGER_TOKEN` | `.env` | Pipeline Trigger Token |
| `GITLAB_PROJECT_ID` | `.env` | 対象プロジェクトのID |
| `BOT_USER_ID` | `.env` | Bot userのID（無限ループ防止） |
| `ANTHROPIC_API_KEY` | CI Variables (Masked) | Anthropic API Key |

## ドキュメント

- [アーキテクチャ詳細](./docs/architecture.md)
- [意思決定記録](./docs/decisions/)
