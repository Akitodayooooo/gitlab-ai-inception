# TODO

## GitLab初期セットアップ

- [x] 初期パスワードを取得してrootでログイン
- [x] GitLabにrootでログイン → `http://13.193.85.82`
- [x] rootのパスワードを変更

## プロジェクト・ユーザー設定

- [x] このリポジトリをGitLabにPush（Project ID: 1）
  - CI/CD configuration file: `agent/.gitlab-ci.yml` 設定済み
- [x] Bot user（`ci-bot`）を作成（Developerロール、User ID: 3）
- [x] Bot userのPersonal Access Token発行 → `.env` 設定済み
- [x] Bot userのID確認 → `BOT_USER_ID=3`

## トークン取得・環境変数設定

- [x] Pipeline Trigger Token発行 → `.env` 設定済み
- [x] プロジェクトID確認 → `GITLAB_PROJECT_ID=1`
- [x] `WEBHOOK_SECRET` 設定済み
- [x] `.env` をEC2に転送・webhook-receiver再起動済み

## GitLab Runner登録

- [x] GitLab Runner登録済み（name: inception-agent, status: online）

## CI/CD Variables設定

- [x] `ANTHROPIC_API_KEY` を登録（Masked）
- [x] `GITLAB_TOKEN` を登録（Masked）

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
