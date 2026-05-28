# GitLab セットアップガイド

新しいGitLabインスタンスにインセプションエージェントを導入する手順。

---

## 前提条件

- GitLab CE が起動していること
- `root` でログインできること
- このリポジトリのコードをGitLabにpush済みであること
- GitLab Runner コンテナが起動していること（docker-compose）

---

## 1. rootパスワードの変更

初回ログイン後すぐに変更する（初期パスワードは24時間で失効）。

```
右上アバター > Edit profile > Password
```

---

## 2. プロジェクト作成とコードのPush

### GitLabに空プロジェクトを作成

```
New project > Create blank project
Project name: gitlab-ai-inception
Initialize repository: チェックを外す
```

### ローカルからPush

```bash
# rootのPATを発行してからpush
git remote add gitlab http://<GITLAB_IP>/root/gitlab-ai-inception.git
git push gitlab main --force
```

> ブランチ保護でforce pushが弾かれる場合は一時的に解除する  
> `Settings > Repository > Protected branches > main > Unprotect`

### CI設定ファイルパスを変更

```
Settings > CI/CD > General pipelines
CI/CD configuration file: agent/.gitlab-ci.yml
```

---

## 3. Bot userの作成

### ユーザー作成

```
Admin Area > Users > New user
Username: ci-bot  （※ ai- / duo- は予約済みで使用不可）
Email: ci-bot@localhost
Access level: Regular
```

### プロジェクトにDeveloperとして追加

```
プロジェクト > Manage > Members > Invite members
Username: ci-bot
Role: Developer
```

### Bot userのPersonal Access Token発行

APIで一括実行する場合：

```bash
ROOT_TOKEN="<rootのPAT>"
GITLAB="http://<GITLAB_IP>"

# ci-bot のユーザーID取得
BOT_ID=$(curl -s -H "PRIVATE-TOKEN: $ROOT_TOKEN" \
  "$GITLAB/api/v4/users?username=ci-bot" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['id'])")

# プロジェクトにDeveloperとして追加
curl -s -X POST -H "PRIVATE-TOKEN: $ROOT_TOKEN" \
  "$GITLAB/api/v4/projects/1/members" \
  -d "user_id=$BOT_ID&access_level=30"

# PATを発行
curl -s -X POST -H "PRIVATE-TOKEN: $ROOT_TOKEN" \
  -H "Content-Type: application/json" \
  "$GITLAB/api/v4/users/$BOT_ID/personal_access_tokens" \
  -d '{"name":"inception-agent","scopes":["api"]}'
```

→ レスポンスの `token` を `.env` の `GITLAB_TOKEN` に設定

---

## 4. トークン類の取得

### Pipeline Trigger Token

```bash
curl -s -X POST -H "PRIVATE-TOKEN: $ROOT_TOKEN" \
  "$GITLAB/api/v4/projects/1/triggers" \
  -d "description=inception-agent"
```

→ レスポンスの `token` を `.env` の `TRIGGER_TOKEN` に設定

### WEBHOOK_SECRET

```bash
openssl rand -hex 24
```

→ 生成した文字列を `.env` の `WEBHOOK_SECRET` に設定

### BOT_USER_ID・GITLAB_PROJECT_ID

- `BOT_USER_ID`: 上の手順で取得した `$BOT_ID`
- `GITLAB_PROJECT_ID`: `Settings > General` のProject ID（通常は `1`）

---

## 5. .env の更新と反映

```bash
# .env を編集
GITLAB_HOST=<EC2のIP>
GITLAB_TOKEN=glpat-xxxx
WEBHOOK_SECRET=xxxx
TRIGGER_TOKEN=glptt-xxxx
GITLAB_PROJECT_ID=1
BOT_USER_ID=<ci-botのID>
GITLAB_URL=http://gitlab

# EC2に転送してwebhook-receiverを再起動
scp -i gitlab-ai.pem .env ubuntu@<EC2_IP>:/home/ubuntu/gitlab-ai-inception/.env
ssh -i gitlab-ai.pem ubuntu@<EC2_IP> \
  "cd /home/ubuntu/gitlab-ai-inception && docker compose restart webhook-receiver"
```

---

## 6. GitLab Runner の登録

GitLab 16以降は新方式（認証トークン）を使用する。

```bash
ROOT_TOKEN="<rootのPAT>"
GITLAB="http://<GITLAB_IP>"

# Runnerの認証トークンを発行
RUNNER_TOKEN=$(curl -s -X POST \
  -H "PRIVATE-TOKEN: $ROOT_TOKEN" \
  -H "Content-Type: application/json" \
  "$GITLAB/api/v4/user/runners" \
  -d '{"runner_type":"project_type","project_id":1,"description":"inception-agent","run_untagged":true}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")

# Runner登録（EC2上で実行）
ssh -i gitlab-ai.pem ubuntu@<EC2_IP> \
  "docker exec gitlab-ai-inception-gitlab-runner-1 \
    gitlab-runner register \
    --non-interactive \
    --url http://<EC2_IP> \
    --token $RUNNER_TOKEN \
    --executor docker \
    --docker-image python:3.12-slim \
    --docker-network-mode gitlab-ai-inception_default \
    --description inception-agent"
```

### 登録確認

```bash
curl -s -H "PRIVATE-TOKEN: $ROOT_TOKEN" \
  "$GITLAB/api/v4/projects/1/runners" \
  | python3 -c "import sys,json; [print(r['description'], r['status']) for r in json.load(sys.stdin)]"
```

`inception-agent online` と表示されればOK。

---

## 7. CI/CD Variables の設定

```
Settings > CI/CD > Variables > Add variable
```

| Key | Value | Masked |
|---|---|---|
| `ANTHROPIC_API_KEY` | `sk-ant-xxxx` | ✅ |
| `GITLAB_TOKEN` | `glpat-xxxx`（ci-botのPAT） | ✅ |

---

## 8. Webhook の設定

```
Settings > Webhooks > Add new webhook
URL: http://<EC2_IP>:8001/webhook
Secret token: .env の WEBHOOK_SECRET と同じ値
Trigger: Issues events ✅ / Comments ✅
SSL verification: 無効（HTTP環境の場合）
```

### 疎通確認

Webhookを保存後、`Test > Push events` で200が返ることを確認。

---

## 9. ラベル作成

```
Project > Manage > Labels > New label
Name: ai-inception  （色は任意）
Name: ai-inception-done  （色は任意）
```

---

## 10. 動作確認

1. Issueを作成
2. `ai-inception` ラベルを付与
3. 数秒以内にAI（ci-bot）がコメントすることを確認
4. コメントで返答して会話を続ける
5. AIが要件定義完了と判断すると `ai-inception-done` ラベルが付与される

---

## トラブルシューティング

### AIがコメントしない

```bash
# webhook-receiverのログを確認
ssh -i gitlab-ai.pem ubuntu@<EC2_IP> \
  "docker logs gitlab-ai-inception-webhook-receiver-1 --tail 50"

# Pipelineの実行履歴を確認
# GitLab > CI/CD > Pipelines
```

### Pipelineが失敗する

```bash
# GitLab > CI/CD > Pipelines > 失敗したジョブ > ログを確認
# よくある原因:
# - ANTHROPIC_API_KEY が未設定
# - GITLAB_TOKEN の権限不足
# - Runner が offline
```

### メモリ不足でGitLabが落ちる

t3.medium（4GB）ではメモリ不足になる場合がある。t3.large（8GB）を推奨。
