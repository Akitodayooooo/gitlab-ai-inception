# TODO

## GitLab初期セットアップ

- [x] 初期パスワードを取得してrootでログイン
- [x] GitLabにrootでログイン → `http://13.193.85.82`
- [x] rootのパスワードを変更

## プロジェクト・ユーザー設定

- [x] このリポジトリをGitLabにPush（Project ID: 1）
  - CI/CD configuration file: `agent/.gitlab-ci.yml` 設定済み
- [ ] Bot user（`ai-bot`）を作成（Developerロール）
- [ ] Bot userのPersonal Access Token発行（`api` scope） → `.env` の `GITLAB_TOKEN` に設定
- [ ] Bot userのIDを確認 → `.env` の `BOT_USER_ID` に設定
  ```bash
  curl http://13.193.85.82/api/v4/users?username=ai-bot
  ```

## トークン取得・環境変数設定

- [ ] Pipeline Trigger Token発行 → `.env` の `TRIGGER_TOKEN` に設定
  - `Settings > CI/CD > Pipeline triggers`
- [ ] プロジェクトIDを確認 → `.env` の `GITLAB_PROJECT_ID` に設定
  - `Settings > General` のProject IDを確認
- [ ] `WEBHOOK_SECRET` に任意の文字列を設定
- [ ] `.env` を更新してEC2に転送・webhook-receiverを再起動
  ```bash
  scp -i gitlab-ai.pem .env ubuntu@13.193.85.82:/home/ubuntu/gitlab-ai-inception/.env
  ssh -i gitlab-ai.pem ubuntu@13.193.85.82 \
    "cd /home/ubuntu/gitlab-ai-inception && docker compose restart webhook-receiver"
  ```

## GitLab Runner登録

- [ ] GitLab RunnerをEC2上で登録
  ```bash
  ssh -i gitlab-ai.pem ubuntu@13.193.85.82
  docker exec -it gitlab-ai-inception-gitlab-runner-1 \
    gitlab-runner register \
    --url http://13.193.85.82 \
    --executor docker \
    --docker-image python:3.12-slim
  ```
  - Registration tokenは `Settings > CI/CD > Runners` で確認

## CI/CD Variables設定

- [ ] `ANTHROPIC_API_KEY` を登録（Masked）
  - `Settings > CI/CD > Variables`
- [ ] `GITLAB_TOKEN` を登録（Masked）

## Webhook設定

- [ ] GitLab WebhookにWebhook Receiverを登録
  - URL: `http://13.193.85.82:8001/webhook`
  - Secret token: `.env` の `WEBHOOK_SECRET` と同じ値
  - Trigger: **Issues events** と **Comments** にチェック
- [ ] Webhookのテスト送信で200が返ることを確認

## 動作確認

- [ ] `ai-inception` ラベルを作成
- [ ] Issueを作成して `ai-inception` ラベルを付与
- [ ] 数秒以内にAIがコメントすることを確認
- [ ] AIと数回やり取りして要件定義サマリーが投稿されることを確認
- [ ] `ai-inception-done` ラベルが自動付与されることを確認

## 今後の拡張（バックログ）

- [ ] コンストラクションフェーズの実装（`ai-inception-done` トリガー）
- [ ] AI-DLCなど複数プロジェクトへの横展開（cross-project pipeline方式）
  - 詳細は [decisions/001-ai-dlc-project-structure.md](./decisions/001-ai-dlc-project-structure.md) 参照
