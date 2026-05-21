# Gemini Enterprise Agent Platform Demo

ブログ記事 URL を入力すると、Agent が記事を要約し、グラレコ SVG を生成する勉強会デモです。

Phase 1 は `MOCK_MODE=true` 前提で、外部 API なしに次の流れを動かします。

1. URL 入力
2. Mock Agent が記事本文を取得した体で本文を作成
3. 3 行要約と重要ポイントを生成
4. ユーザーが要約を確認
5. グラレコ構成案を作成
6. fallback SVG を生成して表示
7. フィードバックで再生成

進行状況は HTMX polling で段階表示します。ユーザーは要約を編集してからグラレコ生成へ進めます。

## 構成

- `web/`: FastAPI Web App
- `agent/`: ADK Agent 想定の action / tool 実装
- `artifacts/`: 生成 SVG の保存先

## 起動

Python 3.10 以上が必要です。Agent Runtime deploy では Agent Engine SDK / MCP のため Python 3.10+ が必須になります。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -c constraints-workshop.txt
MOCK_MODE=true AGENT_BACKEND=local uvicorn web.main:app --reload
```

ブラウザで `http://127.0.0.1:8000` を開いてください。

## ワークショップ配布 / デプロイ

public GitHub repository として参加者に配布する前提の安全チェックとデプロイ手順は次を参照してください。

- [Publication Checklist](docs/publication-checklist.md)
- [Workshop Deployment Guide](docs/workshop-deploy.md)

個人 Google アカウントで参加するワークショップでは、ローカル `gcloud` の会社アカウントや ADC 混線を避けるため、Google Cloud Shell での実行を推奨します。

Cloud Run に public URL で出す場合は、必ず `APP_PASSWORD` と `APP_SECRET_KEY` を設定してください。Cloud Run / `APP_ENV=production` でどちらかが未設定の場合、アプリは起動時に失敗します。

参加者向けの主導線は [Workshop Deployment Guide](docs/workshop-deploy.md) です。`git clone` から Cloud Run URL を開いて smoke test するところまで、Cloud Shell 前提で記載しています。

運営・TA 向けの補助 script:

- `scripts/preflight-cloud-shell.sh`: Phase 0 で Python / gcloud / ADC / billing を確認します。
- `scripts/diagnose-deployment.sh`: Cloud Run、Agent Runtime、bucket、直近エラーをまとめて表示します。
- `scripts/cleanup-gcp-resources.sh`: Cloud Run、bucket、Agent Runtime を確認付きで削除します。

## 環境変数

- `MOCK_MODE`: `true` の場合、外部 API なしで動作します。
- `AGENT_BACKEND`: `local`, `adk`, `runtime`。
  - `local`: FastAPI から Python action/tool pipeline を直接呼びます。
  - `adk`: Google ADK `LlmAgent` + `Runner` + `InMemorySessionService` で narration turn を実行してから、同じ action/tool pipeline を実行します。
  - `runtime`: Cloud Run から Agent Runtime 上の ADK workflow agent を `stream_query` で呼びます。
- `ARTIFACT_DIR`: 生成 SVG の保存先です。
- `APP_PASSWORD`: Cloud Run など public URL で使う簡易ログインパスワードです。
- `APP_SECRET_KEY`: ログイン cookie 署名用の secret です。Cloud Run / production では必須です。Cloud Run revision 間で固定してください。
- `AUTH_COOKIE_MAX_AGE_SECONDS`: ログイン cookie の有効秒数です。既定値は 28800 秒です。
- `APP_LOG_FORMAT`: `json` の場合、Cloud Logging で扱いやすい JSON ログを stdout に出します。
- `LOG_LEVEL`: アプリケーションログレベルです。既定値は `INFO` です。
- `ARTICLE_FETCH_MAX_BYTES`: 記事 URL 取得時の最大ダウンロードサイズです。既定値は 2000000 bytes です。
- `GEMINI_MAX_ATTEMPTS`: Gemini API 呼び出しの最大試行回数です。既定値は 3 です。
- `GEMINI_RETRY_BASE_DELAY_SECONDS`: Gemini API retry の初期待機秒数です。既定値は 0.6 秒です。
- `GOOGLE_GENAI_USE_VERTEXAI=true`: Cloud Run / Gemini Enterprise Agent Platform の Gemini API を ADC で使う場合に設定します。この場合は `GOOGLE_CLOUD_PROJECT` と `GOOGLE_CLOUD_LOCATION` も必要です。
- `GEMINI_API_KEY` または `GOOGLE_API_KEY`: ローカル素振りで Gemini Developer API を使う場合に設定します。
- `GEMINI_TEXT_MODEL`: Gemini text model。既定値は `gemini-3.5-flash` です。
- `GEMINI_IMAGE_MODEL`: Gemini image model。既定値は `gemini-3-pro-image-preview`（Nano Banana Pro）です。
- `AGENT_RUNTIME_RESOURCE_NAME`: `AGENT_BACKEND=runtime` で呼び出す `projects/.../locations/.../reasoningEngines/...` resource name です。
- `AGENT_RUNTIME_LOCATION`: Agent Runtime の location です。既定値は `us-central1` です。
- `AGENT_RUNTIME_STAGING_BUCKET`: Agent Runtime deploy 時に package を一時配置する `gs://...` bucket です。未設定の場合は `GCS_BUCKET` を使います。
- `GCS_BUCKET`: 設定した場合、生成物を Cloud Storage にアップロードします。Agent Runtime backend でグラレコ生成を使う場合は必須です。
- `GCS_ARTIFACT_PREFIX`: Cloud Storage 上の object prefix です。既定値は `artifacts` です。
- `GCS_SIGNED_URL_TTL_SECONDS`: Cloud Storage artifact の signed URL 有効秒数です。既定値は 28800 秒です。
- `GCS_SIGNING_SERVICE_ACCOUNT`: signed URL 生成に使う service account email です。Agent Runtime backend では Cloud Run runtime service account など、project 内に実在する service account を signer として設定します。

Cloud Run / Gemini Enterprise Agent Platform 側に寄せる場合の例:

```bash
export MOCK_MODE=false
export AGENT_BACKEND=runtime
export GOOGLE_GENAI_USE_VERTEXAI=true
export GOOGLE_CLOUD_PROJECT=your-project-id
export GOOGLE_CLOUD_LOCATION=global
export GEMINI_TEXT_MODEL=gemini-3.5-flash
export GEMINI_IMAGE_MODEL=gemini-3-pro-image-preview
export AGENT_RUNTIME_RESOURCE_NAME=projects/PROJECT_NUMBER/locations/us-central1/reasoningEngines/RESOURCE_ID
export GCS_BUCKET=your-project-id-graphic-recording-artifacts
export AGENT_RUNTIME_STAGING_BUCKET="${GCS_BUCKET}"
```

## Phase 2 以降の差し替えポイント

- `agent/adk_agent.py`
  - Google ADK `LlmAgent` factory と Runner 実行を実装しています。
  - `AGENT_BACKEND=adk` では ADK narration step が progress に表示されます。
  - Agent Runtime deploy entrypoint では JSON contract を返す workflow agent を使います。
- `agent/tools.py`
  - `fetch_article`: 実 URL から本文取得
  - `generate_image`: `gemini-3-pro-image-preview`（Nano Banana Pro）呼び出し。失敗時は fallback SVG に戻ります。
  - `save_artifact`: Cloud Storage 保存と signed URL 生成
  - Gemini API 呼び出しは native async client と retry/backoff を使います。
  - URL 取得は private/local address を拒否し、最大 response size を制限します。
- `web/agent_client.py`
  - `RuntimeAgentClient` が Agent Runtime の `stream_query` を呼び、`agent/runtime_contract.py` の schema で検証します。
- `agent/actions.py`
  - local / ADK backend の両方から同じ action/tool pipeline を呼びます。
  - グラレコ生成では Agent が `business` / `pop` / `minimal` から visual style を選び、その判断が plan / image prompt / fallback SVG に反映されます。

## 講義での説明文言

現状の demo は、Web App から Agent backend を呼びます。`AGENT_BACKEND=runtime` では Cloud Run が Agent Runtime 上の ADK workflow agent を呼び、Runtime 側で記事取得、要約、構成案、画像生成、Cloud Storage 保存を実行します。Cloud Run は UI と polling、Agent Runtime は workflow 実行という分担です。

また、グラレコ生成フェーズでは Agent が記事内容から `business` / `pop` / `minimal` の visual style を選択します。この style decision は progress と結果画面に表示され、後続の visual plan と画像生成 prompt に反映されます。

Runtime backend の v1 は安定性を優先し、完了後に Runtime から返った `progress[]` をまとめて表示します。細かい streaming progress は次の拡張ポイントです。

facilitator は、Agent が判断しているポイントとして次を説明してください。

- 記事内容とフィードバックから visual style を選ぶ
- 選んだ style に合わせて visual plan を変える
- 画像生成が失敗した場合も fallback SVG で成果物まで進める
- Artifact は Agent Runtime 側で生成し、Cloud Storage に保存して signed URL で表示する
