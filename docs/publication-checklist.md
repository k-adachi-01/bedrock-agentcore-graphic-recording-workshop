# Publication Checklist

public repository として公開する前に確認する項目です。

## Secret と build context

- `.env` が Git 管理されていない
- `.env` が過去 commit に含まれていない
- `.dockerignore` が `.env`, `.git`, `.venv`, `artifacts/` を除外している
- `.gcloudignore` が `.env`, `.git`, `.venv`, `artifacts/` を除外している
- `scripts/check-publication-safety.sh` が通る

## Cloud Run

- 完全新規 project 用の API 有効化手順がある
- Billing は Console で手作業確認することが明記されている
- Cloud Build / Artifact Registry を source deployment の前提として説明している
- `compute.googleapis.com` と default runtime service account の扱いが明記されている
- API 有効化 / service agent 作成の propagation 待ちが明記されている
- ワークショップ用 disposable project に閉じる注意がある
- Cloud Run runtime service account に `roles/aiplatform.user` を付与する手順がある
- Cloud Build service agent に `roles/run.builder` を付与する手順がある
- `APP_PASSWORD` を必ず設定する
- `APP_SECRET_KEY` を必ず設定し、revision 間で固定する
- Dockerfile が non-root user で起動する
- `/healthz` を startup / liveness probe に設定する
- stdout が JSON ログになっている
- `--allow-unauthenticated` は Cloud Run IAM の認証を外すだけで、アプリ内パスワードで保護する
- in-memory state のため `--max-instances 1` を維持する
- 複数インスタンス化する場合は `sessions`, `jobs`, `graphics` を Firestore などに移す

## Gemini / URL fetch

- Gemini API 呼び出しに retry/backoff がある
- google-genai SDK の native async API を使っている
- 記事 URL の private/local address を拒否している
- 記事 URL の response size 上限を設けている
- ADK tools の docstring に `Args` / `Returns` がある

## Agent Runtime

- `agent/runtime_entrypoint.py` の `root_agent` が deploy entrypoint
- `AGENT_BACKEND=runtime` は未実装時に fail-fast する
- Runtime 呼び出しを実装するまでは Cloud Run は `AGENT_BACKEND=adk` で運用する
- Runtime 実装時は `async_stream_query` の入出力 contract を固定し、テストを追加する

## ワークショップ運営

- 手順書に project ID, region, service name の置換箇所が明示されている
- 参加者に課金とリソース削除を案内する
- デプロイ失敗時の切り戻し手順がある
- 生成物や入力 URL に機密情報を入れないよう案内する
