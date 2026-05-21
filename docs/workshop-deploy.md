# Workshop Deployment Guide

この手順は、参加者が public GitHub repository を clone し、自分の Google Cloud project にデモをデプロイする前提です。

## 前提

- Google Cloud project を 1 つ用意する。新規 project でも既存 project でも可
- 課金が有効化されている。これは通常 Google Cloud Console で手作業確認が必要
- `gcloud` が使える
- Cloud Run を public URL で公開し、アプリ内の簡易パスワードで保護する
- ワークショップ用の disposable project で実行する。同じ project の他の Cloud Run / GCE と権限を共有するため、組織の本番 project では実行しない

参考:

- Cloud Run source deployment: https://docs.cloud.google.com/run/docs/deploying-source-code
- Cloud Run source deployment service account: https://docs.cloud.google.com/run/docs/configuring/services/build-service-account
- Agent Runtime deployment: https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/deploy-an-agent
- ADK on Agent Runtime: https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/use-an-adk-agent

## 0. 完全新規 project の手作業

完全新規 project の場合、次は手作業になることがあります。

1. Google Cloud Console で project を作成する
2. Billing account を project に紐づける
3. Vertex AI / Gemini API の利用規約や組織ポリシーが出た場合は承認する
4. 会社・学校アカウントの場合、API 有効化や IAM 付与が制限されていないか確認する

CLI で project を作れる環境なら次でも構いません。

```bash
export PROJECT_ID="YOUR_UNIQUE_PROJECT_ID"
gcloud projects create "${PROJECT_ID}" --name="Gemini Agent Workshop"
```

Billing account の紐づけは環境ごとに違うため、この手順書では Console で確認する前提にしています。課金が無効だと Cloud Build / Cloud Run / Vertex AI の途中で失敗します。

## 1. ローカル準備

```bash
git clone REPOSITORY_URL
cd "Gemini Enterprise Agent Platform"

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

`.env` は Git に入れないでください。`.gitignore`, `.dockerignore`, `.gcloudignore` で除外済みです。

## 2. Google Cloud の準備

```bash
export PROJECT_ID="YOUR_PROJECT_ID"
export REGION="asia-northeast1"

gcloud auth login
gcloud auth application-default login
gcloud config set project "${PROJECT_ID}"
gcloud auth application-default set-quota-project "${PROJECT_ID}"

./scripts/bootstrap-gcp-project.sh
```

Cloud Run の source deployment では Cloud Build と Artifact Registry が使われます。対象 region に `cloud-run-source-deploy` repository が無い場合、Cloud Run source deployment が Artifact Registry repository を自動作成します。

`bootstrap-gcp-project.sh` はデプロイ前準備だけを行います。Cloud Run / Agent Runtime へのデプロイは実行しません。

### 必要な API

新規 project では少なくとも次を有効化します。

- `run.googleapis.com`
- `cloudbuild.googleapis.com`
- `artifactregistry.googleapis.com`
- `aiplatform.googleapis.com`
- `storage.googleapis.com`
- `compute.googleapis.com`
- `iam.googleapis.com`
- `iamcredentials.googleapis.com`
- `logging.googleapis.com`
- `cloudresourcemanager.googleapis.com`
- `serviceusage.googleapis.com`

### IAM の目安

ワークショップ参加者が project owner の場合は、通常このまま進められます。最小権限で運用する場合は、少なくとも次を確認してください。

- デプロイする人: `roles/run.sourceDeveloper`, `roles/serviceusage.serviceUsageConsumer`, Cloud Run runtime service account に対する `roles/iam.serviceAccountUser`
- API を有効化する人: `roles/serviceusage.serviceUsageAdmin`
- Cloud Build service account: project に対する `roles/run.builder`
- Cloud Run runtime service account: Gemini / Vertex AI 呼び出し用に `roles/aiplatform.user`
- GCS artifact 保存を使う場合: runtime service account に bucket への `roles/storage.objectAdmin`

Cloud Run runtime service account は、明示しない場合 `${PROJECT_NUMBER}-compute@developer.gserviceaccount.com` です。`bootstrap-gcp-project.sh` はこの default runtime service account に `roles/aiplatform.user` を付与します。

この手順は簡単さを優先し、default compute service account を Cloud Run runtime service account として使います。`compute.googleapis.com` は、この default service account を確実に materialize するために有効化します。より厳密に分離したい場合は、Cloud Run 専用 service account を作成し、`roles/aiplatform.user` と必要な GCS 権限だけを付与してください。

`bootstrap-gcp-project.sh` は Cloud Build service agent に `roles/run.builder` も付与します。組織ポリシーや既存 IAM の状態によっては手動確認が必要です。

API 有効化や service agent 作成は反映に時間がかかることがあります。`./scripts/bootstrap-gcp-project.sh` が成功した直後の deploy で `SERVICE_DISABLED` や service account 関連のエラーが出た場合は、1-2 分待って同じコマンドを再実行してください。

### よくある準備段階の失敗

- `Billing account ... is disabled`: Billing account を Console で紐づける
- `SERVICE_DISABLED`: 必要 API が無効。`./scripts/bootstrap-gcp-project.sh` を再実行する
- `Permission denied to enable service`: API 有効化権限がない。管理者に `roles/serviceusage.serviceUsageAdmin` を依頼する
- `iam.serviceAccounts.actAs denied`: Cloud Run runtime service account に対する `roles/iam.serviceAccountUser` がない
- `cloudbuild.builds.create denied`: Cloud Build 実行権限がない
- `Artifact Registry repository ...`: `artifactregistry.googleapis.com` が無効、または region / 権限の問題
- `Service account ... does not exist`: `compute.googleapis.com` や service agent 作成の反映待ち。1-2 分後に `./scripts/bootstrap-gcp-project.sh` を再実行する

## 3. Cloud Run にデプロイ

この段階では Agent Runtime 連携をまだ有効化せず、Cloud Run 上の FastAPI アプリから ADK backend を実行します。

```bash
export SERVICE_NAME="graphic-recording-agent-demo"
export APP_PASSWORD="workshop-demo-password"
export APP_SECRET_KEY="$(openssl rand -hex 32)"
export AGENT_BACKEND="adk"
export GEMINI_TEXT_MODEL="gemini-2.5-flash"
export GEMINI_IMAGE_MODEL="gemini-3-pro-image-preview"
export ARTICLE_FETCH_MAX_BYTES="2000000"

./scripts/deploy-cloud-run.sh
```

デプロイ後、表示された Cloud Run URL を開くとログイン画面が出ます。`APP_PASSWORD` に設定した値でログインします。

再デプロイ時は同じ `APP_SECRET_KEY` を使ってください。値を変えると既存のログイン cookie はすべて無効になります。ワークショップ中に再デプロイする場合は、shell history やメモに控えた値を再 export してから実行します。

現状のアプリは `sessions`, `jobs`, `graphics` を in-memory dict で持つため、Cloud Run は `--max-instances 1` でデプロイしています。複数インスタンスにする場合は Firestore などへ状態を外出ししてください。

`scripts/deploy-cloud-run.sh` は `/healthz` を startup / liveness probe に設定します。Cloud Run の probe は Dockerfile の `HEALTHCHECK` ではなく Cloud Run service revision の設定として扱います。

この Dockerfile は non-root user でアプリを起動します。生成 artifact をローカルにも保存するため、container 内の `/app` は build 時に `app` user へ chown しています。

生成物を Cloud Storage にも保存したい場合は、先に bucket を作成して `GCS_BUCKET` を設定します。

```bash
export GCS_BUCKET="${PROJECT_ID}-graphic-recording-artifacts"
gcloud storage buckets create "gs://${GCS_BUCKET}" --location="${REGION}"

PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
gcloud storage buckets add-iam-policy-binding "gs://${GCS_BUCKET}" \
  --member "serviceAccount:${RUNTIME_SA}" \
  --role "roles/storage.objectAdmin"

gcloud run services update "${SERVICE_NAME}" \
  --region "${REGION}" \
  --update-env-vars "GCS_BUCKET=${GCS_BUCKET},GCS_ARTIFACT_PREFIX=artifacts"
```

この実装では、画面表示は現インスタンスの `/artifacts` を使い、永続バックアップとして同じ生成物を Cloud Storage にアップロードします。

## 4. Agent Runtime に ADK Agent をデプロイ

Agent Runtime は Python のみ対応です。このリポジトリでは `agent/runtime_entrypoint.py` の `root_agent` を Agent Runtime 用 entrypoint として用意しています。

```bash
export PROJECT_ID="YOUR_PROJECT_ID"
export AGENT_RUNTIME_LOCATION="us-central1"
export AGENT_DISPLAY_NAME="graphic-recording-agent"

python scripts/deploy-agent-runtime.py
```

成功すると次の形式の resource name が出力されます。

```text
projects/PROJECT_NUMBER/locations/LOCATION/reasoningEngines/RESOURCE_ID
```

この値は控えておきます。Cloud Run から実際に Agent Runtime を呼ぶには、`RuntimeAgentClient` の workflow contract を実装し、`AGENT_BACKEND=runtime` と `AGENT_RUNTIME_RESOURCE_NAME` を設定して再デプロイします。

現時点では `AGENT_BACKEND=runtime` は fail-fast します。Runtime を使っているつもりで local backend に落ちる事故を防ぐためです。

## 4.5. デプロイ直前チェック

デプロイ前に、ローカルで次を確認します。

```bash
.venv/bin/pytest
./scripts/check-publication-safety.sh
git diff --check
```

Cloud Run の実デプロイに進む前に、`.env` が Git 管理されていないこと、`APP_PASSWORD` と `APP_SECRET_KEY` が shell environment にだけ設定されていることを確認してください。Cloud Run / `APP_ENV=production` では両方が必須です。

## 5. 後片付け

```bash
gcloud run services delete "${SERVICE_NAME}" \
  --region "${REGION}" \
  --quiet
```

Agent Runtime の削除は、Google Cloud Console または Agent Platform SDK から対象の reasoning engine を削除してください。

Cloud Storage bucket も削除する場合:

```bash
gcloud storage rm --recursive "gs://${GCS_BUCKET}"
```

## 6. 公開前チェック

運営者は public repository に push する前に必ず実行します。

```bash
./scripts/check-publication-safety.sh
git status --short
git log --all --oneline -- .env
```

`git log --all -- .env` に履歴が出る場合は、公開前に履歴から削除し、漏洩した値をローテーションしてください。
