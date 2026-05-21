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

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
MOCK_MODE=true AGENT_BACKEND=local uvicorn web.main:app --reload
```

ブラウザで `http://127.0.0.1:8000` を開いてください。

## ワークショップ配布 / デプロイ

public GitHub repository として参加者に配布する前提の安全チェックとデプロイ手順は次を参照してください。

- [Publication Checklist](docs/publication-checklist.md)
- [Workshop Deployment Guide](docs/workshop-deploy.md)

Cloud Run に public URL で出す場合は、必ず `APP_PASSWORD` と `APP_SECRET_KEY` を設定してください。Cloud Run / `APP_ENV=production` でどちらかが未設定の場合、アプリは起動時に失敗します。

## 環境変数

- `MOCK_MODE`: `true` の場合、外部 API なしで動作します。
- `AGENT_BACKEND`: `local`, `adk`, `runtime`。
  - `local`: FastAPI から Python action/tool pipeline を直接呼びます。
  - `adk`: Google ADK `LlmAgent` + `Runner` + `InMemorySessionService` で narration turn を実行してから、同じ action/tool pipeline を実行します。
  - `runtime`: Agent Runtime 呼び出し用の拡張ポイントです。
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
- `GCS_BUCKET`: 設定した場合、生成物を Cloud Storage にもアップロードします。
- `GCS_ARTIFACT_PREFIX`: Cloud Storage 上の object prefix です。既定値は `artifacts` です。

Cloud Run / Gemini Enterprise Agent Platform 側に寄せる場合の例:

```bash
export MOCK_MODE=false
export AGENT_BACKEND=adk
export GOOGLE_GENAI_USE_VERTEXAI=true
export GOOGLE_CLOUD_PROJECT=your-project-id
export GOOGLE_CLOUD_LOCATION=global
export GEMINI_TEXT_MODEL=gemini-3.5-flash
export GEMINI_IMAGE_MODEL=gemini-3-pro-image-preview
```

## Phase 2 以降の差し替えポイント

- `agent/adk_agent.py`
  - Google ADK `LlmAgent` factory と Runner 実行を実装しています。
  - `AGENT_BACKEND=adk` では ADK narration step が progress に表示されます。
- `agent/tools.py`
  - `fetch_article`: 実 URL から本文取得
  - `generate_image`: `gemini-3-pro-image-preview`（Nano Banana Pro）呼び出し。失敗時は fallback SVG に戻ります。
  - `save_artifact`: Cloud Storage 保存
  - Gemini API 呼び出しは native async client と retry/backoff を使います。
  - URL 取得は private/local address を拒否し、最大 response size を制限します。
- `web/agent_client.py`
  - `RuntimeAgentClient` に Agent Runtime 呼び出しを実装
  - 現時点では `AGENT_BACKEND=runtime` は fail-fast します。local fallback で Runtime 利用を装う事故を避けるためです。
- `agent/actions.py`
  - local / ADK backend の両方から同じ action/tool pipeline を呼びます。
  - グラレコ生成では Agent が `business` / `pop` / `minimal` から visual style を選び、その判断が plan / image prompt / fallback SVG に反映されます。

## 講義での説明文言

現状の demo は、Web App から Agent backend を呼び、ADK backend では `LlmAgent` / `Runner` / `SessionService` による narration turn を実行したうえで、同じ action/tool pipeline を進めます。この LlmAgent は現状ナレーター役です。tool 群を持つ `build_graphic_recording_agent` を次フェーズで接続すると、LlmAgent 自身が tool 呼び出しを選ぶ構成へ進められます。

また、グラレコ生成フェーズでは Agent が記事内容から `business` / `pop` / `minimal` の visual style を選択します。この style decision は progress と結果画面に表示され、後続の visual plan と画像生成 prompt に反映されます。

次フェーズではこの tool 群を Agent Runtime 上の Agent として deploy し、`AGENT_BACKEND=runtime` から呼び出す構成に差し替えます。
