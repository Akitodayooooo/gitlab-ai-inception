# TODO

## GitLab初期セットアップ

- [x] 初期パスワードを取得してrootでログイン
- [x] GitLabにrootでログイン → `http://13.193.85.82`
- [x] rootのパスワードを変更

## プロジェクト・ユーザー設定

- [x] このリポジトリをGitLabにPush（Project ID: 1）
  - CI/CD configuration file: `agent/.gitlab-ci.yml` 設定済み
- [x] Bot user（`ci-bot`）を作成（**Maintainerロール**、User ID: 3）
  - ※ `ai-` / `duo-` 始まりのユーザー名は GitLab 予約済みで使用不可
  - ※ `docs/inception/` へのコミットのため Maintainer が必要
- [x] Bot userのPersonal Access Token発行 → `.env` 設定済み
- [x] Bot userのID確認 → `BOT_USER_ID=3`

## トークン取得・環境変数設定

- [x] Pipeline Trigger Token発行 → `.env` 設定済み
- [x] プロジェクトID確認 → `GITLAB_PROJECT_ID=1`
- [x] `WEBHOOK_SECRET` 設定済み
- [x] `.env` をEC2に転送・webhook-receiver再起動済み

## GitLab Runner登録

- [x] GitLab Runner登録済み（name: inception-agent, status: online）
  - GitLab 16+ 新方式（`/api/v4/user/runners`）で登録
  - `--docker-network-mode gitlab-ai-inception_default` 設定済み

## CI/CD Variables設定

- [x] `ANTHROPIC_API_KEY` を登録（Masked）
- [x] `GITLAB_TOKEN` を登録（Masked）

## Webhook設定

- [x] GitLab WebhookにWebhook Receiverを登録（URL: http://13.193.85.82:8001/webhook）
- [x] Webhookのテスト送信で201が返ることを確認

## ラベル作成

- [x] `ai-inception` ラベルを作成（#5843b0）
- [x] `ai-inception-done` ラベルを作成（#2da44e）

## 動作確認

- [x] Issueを作成して `ai-inception` ラベルを付与
- [x] AIがコメントすることを確認（インセプション開始）
- [x] コメントへの返答でAIが継続応答することを確認
- [ ] 要件定義完了まで会話して `ai-inception-done` が付与されることを確認
- [ ] `docs/inception/issue-{N}.md` がリポジトリに生成されることを確認
- [ ] コンストラクションフェーズが自動開始されることを確認
- [ ] ブランチが作成されコードが実装されることを確認
- [ ] MRが自動作成されることを確認
- [ ] MRにレビューコメントを書いてAIが対応することを確認

## 今後の拡張（バックログ）

- [ ] AI-DLC rulesの統合（`./scripts/setup-aidlc.sh` を実行してpush）
  - 詳細は [decisions/001-ai-dlc-project-structure.md](./decisions/001-ai-dlc-project-structure.md) 参照
- [ ] 複数プロジェクトへの横展開（cross-project pipeline方式）
- [ ] OPERATIONSフェーズ（デプロイ・モニタリング自動化）
