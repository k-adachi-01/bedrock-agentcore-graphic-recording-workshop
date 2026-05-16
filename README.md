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
- `AGENT_BACKEND`: `local`, `adk`, `runtime`。
  - `local`: FastAPI から Python action/tool pipeline を直接呼びます。
  - `adk`: Google ADK `LlmAgent` + `Runner` + `InMemorySessionService` で narration turn を実行してから、同じ action/tool pipeline を実行します。
  - `runtime`: Agent Runtime 呼び出し用の拡張ポイントです。
- `ARTIFACT_DIR`: 生成 SVG の保存先です。
- `GOOGLE_GENAI_USE_VERTEXAI=true`: Cloud Run / Gemini Enterprise Agent Platform の Gemini API を ADC で使う場合に設定します。この場合は `GOOGLE_CLOUD_PROJECT` と `GOOGLE_CLOUD_LOCATION` も必要です。
- `GEMINI_API_KEY` または `GOOGLE_API_KEY`: ローカル素振りで Gemini Developer API を使う場合に設定します。
- `GEMINI_TEXT_MODEL`: Gemini text model。既定値は `gemini-2.5-flash` です。
- `GEMINI_IMAGE_MODEL`: Gemini image model。既定値は `gemini-3-pro-image-preview`（Nano Banana Pro）です。

Cloud Run / Gemini Enterprise Agent Platform 側に寄せる場合の例:

```bash
export MOCK_MODE=false
export AGENT_BACKEND=adk
export GOOGLE_GENAI_USE_VERTEXAI=true
export GOOGLE_CLOUD_PROJECT=your-project-id
export GOOGLE_CLOUD_LOCATION=global
export GEMINI_TEXT_MODEL=gemini-2.5-flash
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
- `web/agent_client.py`
  - `RuntimeAgentClient` に Agent Runtime 呼び出しを実装
- `agent/actions.py`
  - local / ADK backend の両方から同じ action/tool pipeline を呼びます。
  - グラレコ生成では Agent が `business` / `pop` / `minimal` から visual style を選び、その判断が plan / image prompt / fallback SVG に反映されます。

## 講義での説明文言

現状の demo は、Web App から Agent backend を呼び、ADK backend では `LlmAgent` / `Runner` / `SessionService` による narration turn を実行したうえで、同じ action/tool pipeline を進めます。この LlmAgent は現状ナレーター役です。tool 群を持つ `build_graphic_recording_agent` を次フェーズで接続すると、LlmAgent 自身が tool 呼び出しを選ぶ構成へ進められます。

また、グラレコ生成フェーズでは Agent が記事内容から `business` / `pop` / `minimal` の visual style を選択します。この style decision は progress と結果画面に表示され、後続の visual plan と画像生成 prompt に反映されます。

次フェーズではこの tool 群を Agent Runtime 上の Agent として deploy し、`AGENT_BACKEND=runtime` から呼び出す構成に差し替えます。
