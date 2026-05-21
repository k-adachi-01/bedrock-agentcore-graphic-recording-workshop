# Workshop Deployment Guide

この手順は、参加者が **GitHub public repository を Google Cloud Shell で clone** し、自分の新規 Google Cloud project にデモをデプロイして、Cloud Run URL で動作確認するところまでを対象にします。

ローカル PC での実行は推奨しません。ワークショップ参加者は個人 Google アカウントで参加する想定のため、ローカル `gcloud` の会社アカウント、ADC quota project、Python version の混線を避けるためです。

## Phase 0. 開場〜開始前にここまで進める

開場時は、早く来た人から次を進めます。ここまで終わっていると、本編では Agent Runtime / Cloud Run の deploy と smoke test に集中できます。

```bash
git clone REPOSITORY_URL
cd "Gemini Enterprise Agent Platform"

python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt -c constraints-workshop.txt

export PROJECT_ID="YOUR_PROJECT_ID"
export REGION="asia-northeast1"
export AGENT_RUNTIME_LOCATION="us-central1"
export GOOGLE_CLOUD_LOCATION="global"
export SERVICE_NAME="graphic-recording-agent-demo"
export APP_PASSWORD="workshop-demo-password"
export APP_SECRET_KEY="$(openssl rand -hex 32)"
export GEMINI_TEXT_MODEL="gemini-3.5-flash"
export GEMINI_IMAGE_MODEL="gemini-3-pro-image-preview"
export ARTICLE_FETCH_MAX_BYTES="2000000"
export GCS_BUCKET="${PROJECT_ID}-graphic-recording-artifacts"
export AGENT_RUNTIME_STAGING_BUCKET="${GCS_BUCKET}"
export GCS_ARTIFACT_PREFIX="artifacts"
export GCS_SIGNED_URL_TTL_SECONDS="28800"

gcloud config set project "${PROJECT_ID}"
gcloud auth application-default login
gcloud auth application-default set-quota-project "${PROJECT_ID}"

./scripts/preflight-cloud-shell.sh
./scripts/bootstrap-gcp-project.sh
```

`preflight-cloud-shell.sh` が失敗した場合は、表示された `[NG]` を直してから再実行してください。成功すると次のコマンドとして `./scripts/bootstrap-gcp-project.sh` が表示されます。

## Phase 1. Workshop 本編の流れ

本編では、まず全体構成を確認し、その後は Section 5 以降の bucket / IAM / Agent Runtime / Cloud Run deploy に進みます。deploy 待ち時間は、講師が ADK、tool 設計、JSON contract、signed URL の説明に使います。

## 0. 全体構成

- Cloud Run: Web UI、ログイン、HTMX polling、Agent Runtime 呼び出し
- Agent Runtime: ADK workflow agent の実行、記事取得、要約、style 判断、画像生成
- Vertex AI / Gemini: text model と image model
- Cloud Storage: Agent Runtime が生成した画像 artifact の保存
- Signed URL: 非公開 bucket の画像をブラウザに表示

重要な設計判断:

- Agent Runtime の local filesystem は Cloud Run から見えないため、生成物は Cloud Storage に置く
- Cloud Run は UI と polling に集中し、workflow は Agent Runtime に寄せる
- Runtime から Cloud Run へ返す値は `agent/runtime_contract.py` の JSON contract で固定する
- v1 は安定性を優先し、Runtime 完了後に progress をまとめて表示する

## 1. 事前準備

Google Cloud Console で次を済ませます。

1. 新規 project を作成する
2. Billing account を project に紐づける
3. Vertex AI / Gemini API の利用規約が表示された場合は承認する
4. Console 上部の project selector で対象 project を選ぶ
5. Cloud Shell を開く

以後のコマンドは Cloud Shell で実行します。

## 2. Repository を clone

`REPOSITORY_URL` は public GitHub repository の URL に置き換えます。

```bash
git clone REPOSITORY_URL
cd "Gemini Enterprise Agent Platform"
```

Cloud Shell の Python が 3.10 以上であることを確認します。

```bash
python3 --version
```

3.10 未満の場合、この手順では進めないでください。Agent Runtime deploy で使う Agent Engine SDK / MCP が Python 3.10+ を要求します。

依存関係をインストールします。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt -c constraints-workshop.txt
```

`constraints-workshop.txt` はワークショップ用の provisional pin です。public repository を Cloud Shell で E2E 検証した後、Cloud Shell 上の `python -m pip freeze > constraints-workshop.txt` で最終版に更新します。

## 3. 環境変数を設定

`PROJECT_ID` は自分の project ID に置き換えます。`APP_PASSWORD` はワークショップ用のログインパスワードです。

```bash
export PROJECT_ID="YOUR_PROJECT_ID"
export REGION="asia-northeast1"
export AGENT_RUNTIME_LOCATION="us-central1"
export GOOGLE_CLOUD_LOCATION="global"

export SERVICE_NAME="graphic-recording-agent-demo"
export APP_PASSWORD="workshop-demo-password"
export APP_SECRET_KEY="$(openssl rand -hex 32)"

export GEMINI_TEXT_MODEL="gemini-3.5-flash"
export GEMINI_IMAGE_MODEL="gemini-3-pro-image-preview"
export ARTICLE_FETCH_MAX_BYTES="2000000"

export GCS_BUCKET="${PROJECT_ID}-graphic-recording-artifacts"
export AGENT_RUNTIME_STAGING_BUCKET="${GCS_BUCKET}"
export GCS_ARTIFACT_PREFIX="artifacts"
export GCS_SIGNED_URL_TTL_SECONDS="28800"
```

Project と認証状態を確認します。

```bash
gcloud config set project "${PROJECT_ID}"
gcloud auth list
gcloud auth application-default login
gcloud auth application-default set-quota-project "${PROJECT_ID}"
gcloud auth application-default print-access-token >/dev/null && echo "ADC ok"
gcloud beta billing projects describe "${PROJECT_ID}"
./scripts/preflight-cloud-shell.sh
```

`billingEnabled: true` になっていない場合は、Console で billing を紐づけてから進んでください。

## 4. API と基本 IAM を準備

```bash
./scripts/bootstrap-gcp-project.sh
```

成功すると project number と Cloud Run runtime service account が表示されます。

```bash
export PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
export CLOUD_RUN_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
export GCS_SIGNING_SERVICE_ACCOUNT="${CLOUD_RUN_SA}"
```

## 5. Artifact bucket を作成

```bash
gcloud storage buckets create "gs://${GCS_BUCKET}" --location="${REGION}"
```

同じ bucket を次の 2 用途で使います。

- Agent Runtime deploy の staging bucket
- 生成画像 artifact の保存先

既に bucket が存在する場合は、`gcloud storage buckets create` は失敗します。その場合は bucket 名が自分の project 用であることを確認して先に進みます。

## 6. Runtime IAM を設定

次の script が、今回ハマった IAM 差分をまとめて処理します。

```bash
./scripts/configure-runtime-iam.sh
```

この script は次を行います。

- Vertex AI service identity を作成または確認
- Cloud Run default service account に bucket 書き込み権限を付与
- `gcp-sa-aiplatform` と `gcp-sa-aiplatform-re` の Runtime 系 service agent に bucket 書き込み権限を付与
- Runtime 系 service agent に Cloud Run default service account で signed URL を作るための `roles/iam.serviceAccountTokenCreator` を付与

script の最後に表示される値を export します。

```bash
export CLOUD_RUN_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
export GCS_SIGNING_SERVICE_ACCOUNT="${CLOUD_RUN_SA}"
```

## 7. Agent Runtime を deploy

```bash
export AGENT_DISPLAY_NAME="graphic-recording-agent"
export AGENT_RUNTIME_STAGING_BUCKET="${GCS_BUCKET}"
export GCS_SIGNING_SERVICE_ACCOUNT="${CLOUD_RUN_SA}"
export GOOGLE_CLOUD_LOCATION="global"

python scripts/deploy-agent-runtime.py
```

成功すると次のような出力になります。

```text
projects/PROJECT_NUMBER/locations/us-central1/reasoningEngines/RESOURCE_ID
effective_identity=service-PROJECT_NUMBER@gcp-sa-aiplatform-re.iam.gserviceaccount.com
```

1 行目を `AGENT_RUNTIME_RESOURCE_NAME` に設定します。

```bash
export AGENT_RUNTIME_RESOURCE_NAME="projects/PROJECT_NUMBER/locations/us-central1/reasoningEngines/RESOURCE_ID"
```

`effective_identity=...` が出た場合は、その identity も IAM 設定に含めます。

```bash
export AGENT_RUNTIME_EFFECTIVE_IDENTITY="SERVICE_AGENT_EMAIL_FROM_EFFECTIVE_IDENTITY"
./scripts/configure-runtime-iam.sh
```

注意:

- Agent Runtime の deployment env では `GOOGLE_CLOUD_PROJECT` は予約名のため渡しません
- Gemini model location は `GOOGLE_CLOUD_LOCATION=global` で固定します
- `gemini-3.5-flash` が 404 の場合は Runtime logs を確認し、model ID または利用可能 region を facilitator に確認してください

## 8. Cloud Run を deploy

```bash
export MOCK_MODE="false"
export AGENT_BACKEND="runtime"
export AGENT_RUNTIME_LOCATION="us-central1"
export GOOGLE_CLOUD_LOCATION="global"
export GCS_SIGNING_SERVICE_ACCOUNT="${CLOUD_RUN_SA}"

./scripts/deploy-cloud-run.sh
```

成功すると Cloud Run URL が表示されます。

```text
Service URL: https://SERVICE_NAME-PROJECT_NUMBER.REGION.run.app
```

この URL を控えます。

再 deploy する場合は、同じ shell session の `APP_SECRET_KEY` を使い続けてください。値を変えると既存の login cookie は無効になります。

## 9. ブラウザで smoke test

Cloud Run URL を開きます。

```text
https://SERVICE_NAME-PROJECT_NUMBER.REGION.run.app
```

ログインパスワードは `APP_PASSWORD` に設定した値です。

```text
workshop-demo-password
```

次を確認します。

1. ログインできる
2. 公開ブログ記事 URL を入力して `Agent に要約させる` を押す
3. 実行中に `Agent Runtime で処理中`、経過秒数、`現在の目安` が表示される
4. 要約確認画面が表示される
5. `グラレコを生成` を押す
6. 実行中に画像生成の待ち時間目安と `現在の目安` が表示される
7. グラレコ結果が表示される
8. `Agent style` と style 判断理由が表示される
9. 画像 artifact が表示され、`画像を開く` / `画像を開いて保存` が使える
10. フィードバックを入力して再生成できる

画像生成は 1〜3 分かかることがあります。止まって見える場合でも、経過秒数が更新されていれば Cloud Run の polling は動いています。通常より長い場合は画面に注意メッセージが表示されます。

Smoke test では、参加者が自由に URL を選ぶ前に次のどちらかで確認してください。サイト構造や bot 対策によって本文抽出に失敗する URL があるためです。

```text
https://zenn.dev/ubie_dev/articles/modern-web-guidance
https://developer.chrome.com/docs/modern-web-guidance/get-started?hl=en
```

## 10. Plan B: Cloud Shell mock fallback

Billing、IAM、Agent Runtime deploy で詰まり、時間内に復旧できない参加者は mock fallback に切り替えます。GCP deploy は完了しませんが、Cloud Shell の Web Preview でアプリの体験を確認できます。

Cloud Shell ターミナルで起動します。

```bash
export MOCK_MODE="true"
export AGENT_BACKEND="local"
export APP_PASSWORD="mock"
export APP_SECRET_KEY="mock-secret-key-for-local-only"

python -m uvicorn web.main:app --host 0.0.0.0 --port 8080
```

起動したら、Cloud Shell 右上の **Web Preview** から **Preview on port 8080** を開きます。ログインパスワードは `mock` です。

この fallback はデモ体験用です。Agent Runtime、Cloud Run、Cloud Storage、signed URL は使いません。参加者が講義内容を追うための避難経路として扱ってください。

## 11. ログ確認

TA に相談する場合は、まず診断 script の出力を共有してください。

```bash
./scripts/diagnose-deployment.sh
```

先頭の `SUMMARY` だけで、Cloud Run、Agent Runtime、bucket、直近エラーの大半を切り分けられます。必要な場合だけ `DETAILS` 以降を確認します。

Cloud Run logs:

```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="'"${SERVICE_NAME}"'"' \
  --project="${PROJECT_ID}" \
  --limit=100 \
  --format='value(timestamp,severity,textPayload,jsonPayload.message,jsonPayload.error)'
```

Agent Runtime logs:

```bash
RUNTIME_ID="$(echo "${AGENT_RUNTIME_RESOURCE_NAME}" | awk -F/ '{print $NF}')"
gcloud logging read 'resource.type="aiplatform.googleapis.com/ReasoningEngine" AND resource.labels.reasoning_engine_id="'"${RUNTIME_ID}"'"' \
  --project="${PROJECT_ID}" \
  --limit=100 \
  --format='value(timestamp,textPayload)'
```

Staging / artifact bucket:

```bash
gcloud storage ls -r "gs://${GCS_BUCKET}/agent_engine/**"
gcloud storage ls -r "gs://${GCS_BUCKET}/${GCS_ARTIFACT_PREFIX}/**" | tail
```

## 12. よくあるエラー

### Billing が無効

症状:

```text
Billing account for project ... is not found
UREQ_PROJECT_BILLING_NOT_FOUND
```

対処: Console で billing account を project に紐づけます。

### Python 3.9 で deploy している

症状:

```text
MCP requires Python 3.10 or above
module 'google.genai.types' has no attribute ...
```

対処: Cloud Shell で `python3 --version` を確認し、3.10+ の venv を作り直します。

### staging_bucket がない

症状:

```text
Please provide a `staging_bucket`
```

対処: `GCS_BUCKET` と `AGENT_RUNTIME_STAGING_BUCKET` を export してから `python scripts/deploy-agent-runtime.py` を実行します。

### `GOOGLE_CLOUD_PROJECT` が reserved

症状:

```text
Environment variable name 'GOOGLE_CLOUD_PROJECT' is reserved
```

対処: Agent Runtime deployment env に `GOOGLE_CLOUD_PROJECT` を渡してはいけません。最新の `scripts/deploy-agent-runtime.py` を使ってください。

### `gemini-3.5-flash` が 404

症状:

```text
Publisher Model ... locations/us-central1 ... gemini-3.5-flash was not found
```

対処: Agent Runtime に `GOOGLE_CLOUD_LOCATION=global` が渡っているか確認し、Runtime を再 deploy します。

### 画面のエラーが空

対処: 最新の Cloud Run revision に再 deploy してください。現在の実装では例外本文が空でも型名を表示し、Cloud Logging に stack trace を出します。

### signed URL が 403

対処: `./scripts/configure-runtime-iam.sh` を再実行し、Cloud Run service account を signer にして Runtime effective identity に `roles/iam.serviceAccountTokenCreator` が付いていることを確認します。

## 13. コスト確認

正確な発生額は、この repository や `gcloud` の通常コマンドだけでは分かりません。Cloud Billing Console で project filter をかけて確認します。

1. Google Cloud Console で Billing を開く
2. Reports を開く
3. Filter で `PROJECT_ID` を選ぶ
4. 今日の日付範囲にする
5. Service ごとの cost を確認する

今回の構成で課金対象になり得るもの:

- Cloud Build
- Artifact Registry
- Cloud Run
- Vertex AI / Agent Runtime
- Gemini text model
- Gemini image model
- Cloud Storage
- Cloud Logging

短時間の spike でも画像生成と Agent Runtime は課金対象になり得ます。ワークショップ後は必ず後片付けしてください。

## 14. 後片付け

まず script で workshop リソースを削除します。`--yes` を付けない場合は、確認 prompt で `delete` と入力しない限り削除されません。

```bash
./scripts/cleanup-gcp-resources.sh
```

自動実行やリハーサルで confirmation を省略したい場合だけ、明示的に `--yes` を付けます。

```bash
./scripts/cleanup-gcp-resources.sh --yes
```

削除前に状態を見たい場合:

```bash
./scripts/diagnose-deployment.sh
```

この cleanup script は Google Cloud project 自体は削除しません。

Disposable project の場合は、project ごと削除するのが最も確実です。ただし、これは **ワークショップ専用に作った disposable project 限定** です。個人利用中の project や会社 project では実行しないでください。削除前に Console の project selector と `PROJECT_ID` を必ず確認してください。

```bash
gcloud projects describe "${PROJECT_ID}"
```

問題なければ project を削除します。削除すると project 内のリソースは復元できません。

```bash
gcloud projects delete "${PROJECT_ID}"
```

## 15. 公開前チェック

運営者は public repository に push する前に必ず実行します。

```bash
python -m pip install -e '.[dev]'
python -m pytest
./scripts/check-publication-safety.sh
bash -n scripts/*.sh
git diff --check
git status --short
git log --all --oneline -- .env
```

`.env`, `.venv`, `.python-version`, `artifacts/`, local screenshots, local backup directories を commit しないでください。

`constraints-workshop.txt` は、public repository を Cloud Shell で clone して E2E 検証が通った後、Cloud Shell 上で次を実行して最終化します。

```bash
python -m pip freeze > constraints-workshop.txt
```
