---
title: AI-DLCへのインセプションエージェント適用方式
status: 決定済み
date: 2026-05-29
---

## 背景

インセプションエージェントのCIジョブ（`inception_agent.py`）はGitLabプロジェクトのリポジトリ内に存在する必要がある。
このエージェント自体は `github.com/Akitodayooooo/gitlab-ai-inception` で管理しているが、
ユーザーが実際に使うプロジェクト（例: AI-DLC）に適用するにはファイルの配置方法を決める必要があった。

## 検討した選択肢

### A. 各プロジェクトにファイルをコピー
- Pros: シンプル、依存関係なし
- Cons: 複数プロジェクトで使う場合にバージョン管理が煩雑

### B. 専用エージェントプロジェクトを作り、cross-project pipelineで呼ぶ
- Pros: エージェントを一元管理できる
- Cons: webhook-receiverの改修が必要（トリガー先プロジェクトIDを動的に切り替える仕組みが必要）

### C. このGitHubリポジトリをGitLabにImportして使う（採用）
- Pros: ファイル配置作業が不要、単一リポジトリで管理
- Cons: インセプション対象プロジェクトとエージェントのコードが同居する

## 決定

**当面はC（GitHubリポジトリをGitLabにImportして使う）を採用する。**

手順：
1. GitLab で `New project > Import project > GitHub` からこのリポジトリをインポート
2. インポート先プロジェクトの `Settings > CI/CD > General pipelines > CI/CD configuration file` を `agent/.gitlab-ci.yml` に変更
3. このプロジェクト上でIssueを作成し `ai-inception` ラベルを付与して運用

## 今後の拡張

AI-DLCなど複数の別プロジェクトに横展開したい場合は **選択肢B（専用エージェントプロジェクト）** へ移行する。
そのために必要な変更点：

- `webhook-receiver/main.py`: イベントを受けたプロジェクトIDを動的に渡すよう変更
- `agent/inception_agent.py`: `GITLAB_PROJECT_ID` を `ISSUE_PROJECT_ID` と分離（エージェントが動くプロジェクトとIssueがあるプロジェクトを別にできる）
- `agent/.gitlab-ci.yml`: `ISSUE_PROJECT_ID` を変数として受け取るよう追加
