# Strands Agents + Amazon Bedrock AgentCore Workshop

ブログ記事 URL を入力すると、Bedrock AgentCore Runtime 上の Strands Agent workflow が記事を要約し、グラフィックレコーディング画像を生成するワークショップ用デモです。

参加者は AWS CloudShell でこの repository を clone し、自分の AWS account に AgentCore Runtime と ECS Express Mode をデプロイします。

## 作るもの

- Amazon ECS Express Mode (Fargate): Web UI、ログイン、進行状況表示、AgentCore Runtime 呼び出し
- Bedrock AgentCore Runtime: Strands Agent workflow の実行
- Amazon Bedrock: 記事要約、style 判断、構成案作成、画像生成
- Amazon S3: 生成画像 artifact の保存
- Presigned URL: 非公開 bucket の画像をブラウザに表示

## 手順

ワークショップでは次の手順書に沿って進めます。

- [Workshop Deployment Guide](docs/workshop-deploy.md)

AWS CloudShell 前提で、AWS account の事前確認から ECS Express の default URL を開いて動作確認するところまで記載しています。

## ローカル確認

AWS へ進む前に、アプリの画面だけ確認したい場合は mock mode で起動できます。

```bash
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt -c constraints-workshop.txt

export MOCK_MODE=true
export AGENT_BACKEND=local
export APP_PASSWORD=mock
export APP_SECRET_KEY=mock-secret-key-for-local-only

uvicorn web.main:app --reload
```

ブラウザで `http://127.0.0.1:8000` を開き、パスワード `mock` でログインします。

## 主なディレクトリ

- `web/`: FastAPI Web App
- `agent/`: Strands Agent、workflow、tool 実装
- `scripts/`: AWS CloudShell 用のセットアップ、デプロイ、診断、削除 script
- `docs/`: ワークショップ手順書
- `tests/`: 主要フローのテスト

## 注意

ECS Express Mode は public URL (ALB) で公開されます。デプロイ時は必ず自分用の `APP_PASSWORD` を設定してください。

生成した画像やログは AWS account 内に残ります。ワークショップ後は [後片付け手順](docs/workshop-deploy.md#13-後片付け) に沿って削除してください。
