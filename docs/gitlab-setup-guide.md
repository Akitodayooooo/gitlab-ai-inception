# GitLab セットアップガイド

新しいGitLabインスタンスにインセプション/コンストラクションエージェントを導入する手順。
今回の実際の構築作業を元に作成した実践的なガイドです。

---

## 前提条件

- AWS CLI 設定済み（`aws configure` 実行済み）
- Node.js 20+ / npm
- Docker / Docker Compose（EC2上）
- Anthropic API Key（https://console.anthropic.com で取得）

---

## 1. インフラ構築（AWS CDK）

### CDKデプロイ

```bash
cd infra
npm install
cdk bootstrap   # 初回のみ
cdk deploy
```

> **重要**: `t3.large`（8GB）以上を使用すること。
> `t3.medium`（4GB）ではGitLab CE + Runner + webhook-receiverの同時起動でメモリ不足になる。

デプロイ後の出力例：
```
Outputs:
  PublicIP      = 13.x.x.x
  SshKeyCommand = aws ssm get-parameter --name /ec2/keypair/... > gitlab-ai.pem && chmod 600 gitlab-ai.pem
  GitlabUrl     = http://13.x.x.x
  WebhookUrl    = http://13.x.x.x:8001/webhook
```

### SSHキーの取得

```bash
aws ssm get-parameter \
  --name /ec2/keypair/<key-id> \
  --with-decryption \
  --query Parameter.Value \
  --output text > gitlab-ai.pem && chmod 600 gitlab-ai.pem
```

---

## 2. アプリのデプロイ

```bash
cp .env.example .env
# .env の GITLAB_HOST にEC2のIPを設定

scp -i gitlab-ai.pem .env ubuntu@<EC2_IP>:/home/ubuntu/gitlab-ai-inception/.env
ssh -i gitlab-ai.pem ubuntu@<EC2_IP> \
  "cd /home/ubuntu/gitlab-ai-inception && docker compose up -d"
```

GitLabの初回起動には**10〜15分**かかる。

---

## 3. GitLab初期設定

### 起動確認

```bash
# healthy になるまで待機
ssh -i gitlab-ai.pem ubuntu@<EC2_IP> \
  "docker inspect --format='{{.State.Health.Status}}' gitlab-ai-inception-gitlab-1"
```

### 初期パスワード取得

```bash
ssh -i gitlab-ai.pem ubuntu@<EC2_IP> \
  "docker exec gitlab-ai-inception-gitlab-1 grep 'Password:' /etc/gitlab/initial_root_password"
```

`http://<EC2_IP>` にアクセスして `root` / 取得したパスワードでログイン。
**ログイン後すぐにパスワードを変更すること**（初期パスワードは24時間で失効）。

```
右上アバター > Edit profile > Password
```

---

## 4. プロジェクト作成とコードのPush

### GitLabに空プロジェクトを作成

```
New project > Create blank project
Project name: gitlab-ai-inception
Initialize repository: チェックを外す  ← 重要
```

### rootのPATを発行してPush

```
右上アバター > Edit profile > Access Tokens > Add new token
Name: deploy
Scopes: api, write_repository
```

```bash
git remote add gitlab http://<EC2_IP>/root/gitlab-ai-inception.git
git push gitlab main
```

> **ブランチ保護でforce pushが拒否される場合:**
> ```bash
> ROOT_TOKEN="glpat-xxxx"
> # ブランチ保護を一時解除
> curl -X DELETE -H "PRIVATE-TOKEN: $ROOT_TOKEN" \
>   "http://<EC2_IP>/api/v4/projects/1/protected_branches/main"
> git push gitlab main --force
> # 再保護
> curl -X POST -H "PRIVATE-TOKEN: $ROOT_TOKEN" \
>   "http://<EC2_IP>/api/v4/projects/1/protected_branches" \
>   -d "name=main&push_access_level=40&merge_access_level=40"
> ```

### CI設定ファイルパスを変更（API）

```bash
curl -X PUT -H "PRIVATE-TOKEN: $ROOT_TOKEN" \
  -H "Content-Type: application/json" \
  "http://<EC2_IP>/api/v4/projects/1" \
  -d '{"ci_config_path": "agent/.gitlab-ci.yml"}'
```

---

## 5. Bot userの作成

> **注意①**: GitLab 16以降、`ai-` / `duo-` で始まるユーザー名は予約済みで使用不可。
> `ci-bot` や `inception-bot` など別の名前を使うこと。

> **注意②**: Bot userには **Maintainerロール** が必要。
> インセプション完了時に `docs/inception/` へ直接コミットするため、
> Developerでは保護ブランチへの書き込みができない。

### APIで一括実行（推奨）

```bash
ROOT_TOKEN="glpat-xxxx"
GITLAB="http://<EC2_IP>"

# ci-bot のユーザーID取得
BOT_ID=$(curl -s -H "PRIVATE-TOKEN: $ROOT_TOKEN" \
  "$GITLAB/api/v4/users?username=ci-bot" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['id'])")
echo "BOT_USER_ID: $BOT_ID"

# プロジェクトにMaintainerとして追加（access_level=40）
curl -X POST -H "PRIVATE-TOKEN: $ROOT_TOKEN" \
  "$GITLAB/api/v4/projects/1/members" \
  -d "user_id=$BOT_ID&access_level=40"

# PATを発行（admin権限で他ユーザーのPATを発行可能）
curl -X POST -H "PRIVATE-TOKEN: $ROOT_TOKEN" \
  -H "Content-Type: application/json" \
  "$GITLAB/api/v4/users/$BOT_ID/personal_access_tokens" \
  -d '{"name":"inception-agent","scopes":["api"]}'
# → レスポンスの token を .env の GITLAB_TOKEN に設定
```

> **既にDeveloperで追加済みの場合の昇格:**
> ```bash
> curl -X PUT -H "PRIVATE-TOKEN: $ROOT_TOKEN" \
>   "$GITLAB/api/v4/projects/1/members/$BOT_ID" \
>   -d "access_level=40"
> ```

---

## 6. トークン類の取得

### Pipeline Trigger Token

```bash
curl -X POST -H "PRIVATE-TOKEN: $ROOT_TOKEN" \
  "$GITLAB/api/v4/projects/1/triggers" \
  -d "description=inception-agent"
# → token を .env の TRIGGER_TOKEN に設定
```

### WEBHOOK_SECRET

```bash
openssl rand -hex 24
# → 生成した文字列を .env の WEBHOOK_SECRET に設定
```

### プロジェクトID

`Settings > General` のProject ID（通常 `1`）

---

## 7. .env の完成と反映

```bash
# .env を編集
GITLAB_HOST=<EC2のIP>
GITLAB_TOKEN=glpat-xxxx     # ci-botのPAT
WEBHOOK_SECRET=xxxx
TRIGGER_TOKEN=glptt-xxxx
GITLAB_PROJECT_ID=1
BOT_USER_ID=<ci-botのID>    # 上の手順で確認
GITLAB_URL=http://gitlab

# EC2に転送してwebhook-receiverを再起動（コンテナ再作成が確実）
scp -i gitlab-ai.pem .env ubuntu@<EC2_IP>:/home/ubuntu/gitlab-ai-inception/.env
ssh -i gitlab-ai.pem ubuntu@<EC2_IP> \
  "cd /home/ubuntu/gitlab-ai-inception && docker compose up -d --force-recreate webhook-receiver"

# 環境変数が反映されたか確認
ssh -i gitlab-ai.pem ubuntu@<EC2_IP> \
  "docker exec gitlab-ai-inception-webhook-receiver-1 env | grep WEBHOOK_SECRET"
```

> **注意**: `docker compose restart` ではenv fileが再読み込みされないことがある。
> `--force-recreate` でコンテナを再作成すること。

---

## 8. GitLab Runner の登録

GitLab 16以降は**新方式**（認証トークン）を使用する。旧方式（registration token）は廃止。

```bash
ROOT_TOKEN="glpat-xxxx"
GITLAB="http://<EC2_IP>"

# Step1: GitLab側でRunnerの認証トークンを発行
RUNNER_TOKEN=$(curl -s -X POST \
  -H "PRIVATE-TOKEN: $ROOT_TOKEN" \
  -H "Content-Type: application/json" \
  "$GITLAB/api/v4/user/runners" \
  -d '{"runner_type":"project_type","project_id":1,"description":"inception-agent","run_untagged":true}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")

# Step2: EC2上のRunnerコンテナに登録
# --docker-network-mode でGitLabと同一ネットワークに接続（CI_SERVER_URL解決に必要）
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
# → inception-agent online
```

---

## 9. CI/CD Variables の設定

```
Settings > CI/CD > Variables > Add variable
```

| Key | Masked | 説明 |
|---|---|---|
| `ANTHROPIC_API_KEY` | ✅ | Anthropic API Key（https://console.anthropic.com で取得） |
| `GITLAB_TOKEN` | ✅ | ci-botのPersonal Access Token |

> **セキュリティ**: `ANTHROPIC_API_KEY` はチャットやコードに直接貼り付けず、
> GitLab UIから直接入力すること。

---

## 10. Webhook の設定

```bash
# APIで登録
ROOT_TOKEN="glpat-xxxx"
curl -X POST -H "PRIVATE-TOKEN: $ROOT_TOKEN" \
  -H "Content-Type: application/json" \
  "http://<EC2_IP>/api/v4/projects/1/hooks" \
  -d "{
    \"url\": \"http://<EC2_IP>:8001/webhook\",
    \"token\": \"<WEBHOOK_SECRET>\",
    \"issues_events\": true,
    \"note_events\": true,
    \"enable_ssl_verification\": false
  }"

# 疎通確認（201が返ればOK）
curl -X POST -H "PRIVATE-TOKEN: $ROOT_TOKEN" \
  "http://<EC2_IP>/api/v4/projects/1/hooks/1/test/push_events"
```

---

## 11. ラベル作成

```bash
ROOT_TOKEN="glpat-xxxx"
for label in "ai-inception:#5843b0" "ai-inception-done:#2da44e"; do
  NAME="${label%%:*}"; COLOR="${label##*:}"
  curl -X POST -H "PRIVATE-TOKEN: $ROOT_TOKEN" \
    "http://<EC2_IP>/api/v4/projects/1/labels" \
    -d "name=$NAME&color=$COLOR"
done
```

---

## 12. AI-DLC 統合（オプション）

AI-DLCのワークフロールールをリポジトリに追加すると、
コンストラクションエージェントが自動的に読み込んで活用します。

```bash
# AI-DLCルールをダウンロードしてコピー
./scripts/setup-aidlc.sh

# GitLabにpush
git add aidlc-rules/
git commit -m "Add AI-DLC workflow rules"
git push && git push gitlab main
```

---

## 13. 動作確認

### インセプションフェーズ

1. GitLabでIssueを作成
2. `ai-inception` ラベルを付与
3. 数秒以内にci-botがコメント（ヒアリング開始）
4. コメントで返答を繰り返す
5. AIが要件定義完了と判断 → サマリーを投稿し `ai-inception-done` ラベルが自動付与

### コンストラクションフェーズ

`ai-inception-done` ラベルが付与されると自動的に開始：

6. ブランチが自動作成（`feature/issue-{N}-{slug}`）
7. AIがコードベースを分析して実装
8. MRが自動作成される
9. MRにレビューコメントを書くとAIが対応してコードを修正

---

## トラブルシューティング

### AIがコメントしない

```bash
# webhook-receiverのログを確認
ssh -i gitlab-ai.pem ubuntu@<EC2_IP> \
  "docker logs gitlab-ai-inception-webhook-receiver-1 --tail 50"
```

よくある原因と対処：
- `Invalid token` → `--force-recreate` でwebhook-receiverを再作成
- `Pipeline triggered` と出ているが動かない → GitLab CI/CDのPipelinesで失敗ログを確認

### Pipelineが失敗する

```
GitLab > CI/CD > Pipelines > 失敗したジョブ > ログ
```

よくある原因：
- `credit balance is too low` → https://console.anthropic.com でクレジット追加
- `ANTHROPIC_API_KEY not set` → CI/CD Variablesに登録されているか確認
- `Runner offline` → `gitlab-runner register` を再実行

### SSH接続タイムアウト

GitLab起動直後はメモリ/CPU高負荷でSSHがタイムアウトする場合がある。
数分待つか、SSM Session Managerを使用：

```bash
aws ssm start-session --target <instance-id>
```

### メモリ不足でGitLabが落ちる

`t3.medium`（4GB）では不足。`t3.large`（8GB）に変更：

```typescript
// infra/bin/app.ts
instanceType: ec2.InstanceType.of(ec2.InstanceClass.T3, ec2.InstanceSize.LARGE),
```

```bash
cd infra && cdk deploy
```

---

## コスト目安（スケジュール適用後）

| リソース | 月額 |
|---|---|
| EC2 t3.large（18:00-24:00 JST のみ起動） | ~$16 |
| EBS 50GB GP3 | ~$4 |
| **合計** | **~$20/月** |

スケジュールは `infra/bin/app.ts` の `startHourUtc` / `stopHourUtc` で変更可能。
