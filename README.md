# Gemini Enterprise Agent Runtime Workshop

ブログ記事 URL を入力すると、Agent Runtime 上の ADK Agent が記事を要約し、グラフィックレコーディング画像を生成するワークショップ用デモです。

参加者は Google Cloud Shell でこの repository を clone し、自分の Google Cloud project に Agent Runtime と Cloud Run をデプロイします。

## 作るもの

- Cloud Run: Web UI、ログイン、進行状況表示、Agent Runtime 呼び出し
- Agent Runtime: ADK Agent workflow の実行
- Vertex AI / Gemini: 記事要約、style 判断、構成案作成、画像生成
- Cloud Storage: 生成画像 artifact の保存
- Signed URL: 非公開 bucket の画像をブラウザに表示

## 手順

ワークショップでは次の手順書に沿って進めます。

- [Workshop Deployment Guide](docs/workshop-deploy.md)

Cloud Shell 前提で、project 作成後の `git clone` から Cloud Run URL を開いて動作確認するところまで記載しています。

## ローカル確認

Cloud Shell / Google Cloud に進む前に、アプリの画面だけ確認したい場合は mock mode で起動できます。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -c constraints-workshop.txt

export MOCK_MODE=true
export AGENT_BACKEND=local
export APP_PASSWORD=mock
export APP_SECRET_KEY=mock-secret-key-for-local-only

uvicorn web.main:app --reload
```

ブラウザで `http://127.0.0.1:8000` を開き、パスワード `mock` でログインします。

## 主なディレクトリ

- `web/`: FastAPI Web App
- `agent/`: ADK Agent、workflow、tool 実装
- `scripts/`: Cloud Shell / Google Cloud 用のセットアップ、デプロイ、診断、削除 script
- `docs/`: ワークショップ手順書
- `tests/`: 主要フローのテスト

## 注意

Cloud Run は public URL で公開されます。デプロイ時は必ず自分用の `APP_PASSWORD` を設定してください。

生成した画像やログは Google Cloud project 内に残ります。ワークショップ後は [後片付け手順](docs/workshop-deploy.md#14-後片付け) に沿って削除してください。
