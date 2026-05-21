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
- Agent Runtime deploy 用に Python 3.10+ が必要なことが明記されている
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
- background workflow のため Cloud Run の CPU throttling を無効化する
- 複数インスタンス化する場合は `sessions`, `jobs`, `graphics` を Firestore などに移す

## Gemini / URL fetch

- Gemini API 呼び出しに retry/backoff がある
- google-genai SDK の native async API を使っている
- 記事 URL の private/local address を拒否している
- 記事 URL の response size 上限を設けている
- ADK tools の docstring に `Args` / `Returns` がある

## Agent Runtime

- `agent/runtime_entrypoint.py` の `root_agent` が deploy entrypoint
- `agent/runtime_contract.py` の入出力 contract を Agent 側と Client 側で共有する
- `AGENT_BACKEND=runtime` では `AGENT_RUNTIME_RESOURCE_NAME` を必須にする
- Runtime artifact は Cloud Storage に保存し、signed URL で画面表示する
- Runtime backend でグラレコ生成する場合は `GCS_BUCKET` を必須にする
- signed URL 生成用に `roles/iam.serviceAccountTokenCreator` と `GCS_SIGNING_SERVICE_ACCOUNT` の手順がある

## ワークショップ運営

- 手順書に project ID, region, service name の置換箇所が明示されている
- 個人 Google アカウント参加者向けに Cloud Shell 推奨手順がある
- 開場〜開始前の Phase 0 手順がある
- `constraints-workshop.txt` を使った依存固定 install 手順がある
- `scripts/preflight-cloud-shell.sh` で事前確認できる
- `scripts/diagnose-deployment.sh` で TA が状態を確認できる
- Cloud Shell Web Preview を使う mock fallback 手順がある
- 参加者に課金とリソース削除を案内する
- `scripts/cleanup-gcp-resources.sh` は確認 prompt 付きで、project 削除は docs 案内に留める
- デプロイ失敗時の切り戻し手順がある
- 生成物や入力 URL に機密情報を入れないよう案内する
