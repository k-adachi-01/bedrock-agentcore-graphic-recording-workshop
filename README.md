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

## 環境変数

- `MOCK_MODE`: `true` の場合、外部 API なしで動作します。
- `AGENT_BACKEND`: `local` または `runtime`。Phase 1 では `runtime` でも Mock Agent にフォールバックします。
- `ARTIFACT_DIR`: 生成 SVG の保存先です。
- `GOOGLE_GENAI_USE_VERTEXAI=true`: Cloud Run / Gemini Enterprise Agent Platform の Gemini API を ADC で使う場合に設定します。この場合は `GOOGLE_CLOUD_PROJECT` と `GOOGLE_CLOUD_LOCATION` も必要です。
- `GEMINI_API_KEY` または `GOOGLE_API_KEY`: ローカル素振りで Gemini Developer API を使う場合に設定します。
- `GEMINI_TEXT_MODEL`: Gemini text model。既定値は `gemini-2.5-flash` です。
- `GEMINI_IMAGE_MODEL`: Gemini image model。既定値は `gemini-3-pro-image-preview`（Nano Banana Pro）です。

Cloud Run / Gemini Enterprise Agent Platform 側に寄せる場合の例:

```bash
export MOCK_MODE=false
export GOOGLE_GENAI_USE_VERTEXAI=true
export GOOGLE_CLOUD_PROJECT=your-project-id
export GOOGLE_CLOUD_LOCATION=global
export GEMINI_TEXT_MODEL=gemini-2.5-flash
export GEMINI_IMAGE_MODEL=gemini-3-pro-image-preview
```

## Phase 2 以降の差し替えポイント

- `agent/adk_agent.py`
  - Google ADK `LlmAgent` の factory。Phase 1 では optional skeleton として配置しています。
- `agent/tools.py`
  - `fetch_article`: 実 URL から本文取得
  - `generate_image`: `gemini-3-pro-image-preview`（Nano Banana Pro）呼び出し。失敗時は fallback SVG に戻ります。
  - `save_artifact`: Cloud Storage 保存
- `web/agent_client.py`
  - `RuntimeAgentClient` に Agent Runtime 呼び出しを実装
- `agent/actions.py`
  - Google ADK の Agent / Tool 定義に接続
