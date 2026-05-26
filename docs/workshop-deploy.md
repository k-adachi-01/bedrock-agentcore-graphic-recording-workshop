# Workshop Deployment Guide

この手順は、参加者が **AWS CloudShell で repository を clone** し、自分の AWS account にデモを deploy して、ECS Express の default URL で動作確認するところまでを対象にします。

ローカル PC での実行は推奨しません。ワークショップ参加者の AWS credential、Python version、Node/pnpm version の混線を避けるためです。

> 本ワークショップでは実際に AWS 上にアプリケーションを deploy し稼働させるため、AWS の料金が発生します。

## 0. 全体構成

- Amazon ECS Express Mode (Fargate): FastAPI Web UI、ログイン、HTMX polling、AgentCore Runtime 呼び出し
- Bedrock AgentCore Runtime: Strands Agent workflow の実行、記事取得、要約、style 判断、画像生成
- Amazon Bedrock: text model と image model
- Amazon S3: AgentCore Runtime が生成した画像 artifact の保存
- CloudWatch Logs: ECS Express と AgentCore Runtime のログ確認

重要な境界:

- AgentCore Runtime の local filesystem は ECS Express から見えないため、生成物は S3 に置く
- ECS Express は UI と polling に集中し、workflow は AgentCore Runtime に寄せる
- Runtime から ECS Express へ返す値は `agent/runtime_contract.py` の JSON contract で固定する

## 1. 事前準備

AWS Console で次を確認します。

- 利用する AWS account にログインできる
- Bedrock model access で text model と image model が有効
- ECS Express (Fargate)、S3、CloudWatch Logs、Bedrock、Bedrock AgentCore を使える IAM 権限がある
- ECR (Elastic Container Registry) に Docker image を push できる IAM 権限がある

推奨 region:

```bash
export AWS_REGION="us-east-1"
export AWS_DEFAULT_REGION="${AWS_REGION}"
```

## 2. Repository を取得

AWS CloudShell を開き、repository を clone します。

```bash
git clone https://github.com/kazumasa416/gemini-enterprise-agent-runtime-workshop.git
cd gemini-enterprise-agent-runtime-workshop
```

依存ツールを mise と pnpm で揃えます。

```bash
mise trust
mise install
pnpm install
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt -c constraints-workshop.txt
```

## 3. 環境変数

```bash
export AWS_REGION="us-east-1"
export AWS_DEFAULT_REGION="${AWS_REGION}"

export ECS_SERVICE_NAME="graphic-recording-agent-demo"
export APP_PASSWORD="CHANGE_ME_TO_YOUR_PASSWORD"
export APP_SECRET_KEY="$(openssl rand -hex 32)"

export BEDROCK_TEXT_MODEL_ID="us.anthropic.claude-sonnet-4-20250514-v1:0"
export BEDROCK_IMAGE_MODEL_ID="amazon.nova-canvas-v1:0"

export S3_BUCKET="graphic-recording-artifacts-${RANDOM}-${RANDOM}"
export S3_ARTIFACT_PREFIX="artifacts"
export S3_PRESIGNED_URL_TTL_SECONDS="28800"
export ECR_REPO_NAME="graphic-recording-agent-demo"
```

## 4. AWS 認証と S3 bucket

```bash
aws sts get-caller-identity
aws bedrock list-foundation-models --region "${AWS_REGION}" --max-results 5 >/dev/null
aws s3 mb "s3://${S3_BUCKET}" --region "${AWS_REGION}"
./scripts/preflight-aws-cloudshell.sh
```

Bedrock model access が無い場合は、Bedrock Console の Model access から利用する model を有効化してから再実行します。

## 5. AgentCore Runtime を deploy

AgentCore CLI は repository local の pnpm dependency として実行します。初回は AgentCore project metadata を作成します。

```bash
pnpm exec agentcore create \
  --name GraphicRecordingAgent \
  --framework Strands \
  --protocol HTTP \
  --model-provider Bedrock \
  --memory none
```

生成された AgentCore app の entrypoint から、この repository の `agent.agentcore_entrypoint:app` を使うようにします。以後の deploy は次で実行します。

```bash
python scripts/deploy-agentcore-runtime.py
```

deploy が成功したら、出力された runtime ARN を控えて設定します。

```bash
export AGENTCORE_RUNTIME_ARN="PASTE_RUNTIME_ARN_HERE"
```

AgentCore Runtime の環境変数には、少なくとも次を設定します。

```bash
BEDROCK_TEXT_MODEL_ID=${BEDROCK_TEXT_MODEL_ID}
BEDROCK_IMAGE_MODEL_ID=${BEDROCK_IMAGE_MODEL_ID}
S3_BUCKET=${S3_BUCKET}
S3_ARTIFACT_PREFIX=${S3_ARTIFACT_PREFIX}
S3_PRESIGNED_URL_TTL_SECONDS=${S3_PRESIGNED_URL_TTL_SECONDS}
MOCK_MODE=false
```

Runtime role には Bedrock invoke と S3 put/get の権限が必要です。

## 6. ECS Express Mode を deploy

単一の script で ECR repository 作成、Docker build / push、ECS Express Mode service 作成まで行います。

```bash
./scripts/deploy-ecs-express.sh
```

この script は以下を自動で実行します:

1. ECR repository (`graphic-recording-agent-demo`) を作成
2. リポジトリの Dockerfile を build して ECR に push
3. ECS Express Mode に必要な IAM role (`ecsTaskExecutionRole`, `ecsInfrastructureRoleForExpressServices`) がなければ作成
4. `aws ecs create-express-gateway-service` で Fargate + ALB + オートスケーリングを一括プロビジョニング

Provisioning には 3〜5 分かかります。完了後、service の default URL を取得します。

```bash
aws ecs describe-services --cluster express --services "${ECS_SERVICE_NAME}" --region "${AWS_REGION}" --query 'services[0].networkConfiguration.defaultEndpoint' --output text
```

ECS タスクから AgentCore Runtime を呼び出せるよう、ecsTaskExecutionRole に invoke 権限を追加します。

```bash
aws iam put-role-policy \
  --role-name ecsTaskExecutionRole \
  --policy-name InvokeAgentCore \
  --policy-document '{
    "Version":"2012-10-17",
    "Statement":[{
      "Effect":"Allow",
      "Action":"bedrock-agentcore:InvokeAgentRuntime",
      "Resource":"'"${AGENTCORE_RUNTIME_ARN}"'"
    }]
  }'
```

> ECS Express Mode は最低 1 タスクが常時稼働するため、ワークショップ後は必ず削除してください。`scripts/cleanup-aws-resources.sh` を参照ください。

## 7. Smoke test

ECS Express の default URL を開き、`APP_PASSWORD` でログインします。

1. 公開記事 URL を入力する
2. 要約が表示されることを確認する
3. 要約を必要に応じて編集して「画像を生成」を押す
4. グラレコ結果が表示されることを確認する
5. フィードバックを入力して再生成する

画像生成は 1〜3 分かかることがあります。止まって見える場合でも、経過秒数が更新されていれば ECS Express の polling は動いています。

## 8. Mock mode

IAM や Bedrock model access で進めない場合は、mock mode で画面確認できます。

```bash
export MOCK_MODE=true
export AGENT_BACKEND=local
export APP_PASSWORD=mock
export APP_SECRET_KEY=mock-secret-key-for-local-only
uvicorn web.main:app --host 0.0.0.0 --port 8080
```

この mode は画面確認用です。AgentCore Runtime、S3、presigned URL は使いません。

## 9. 診断

```bash
./scripts/diagnose-deployment.sh
```

確認する場所:

- ECS Express service status (describe-services) と CloudWatch Logs
- AgentCore Runtime logs
- ALB target group の health check が healthy か
- S3 bucket の `artifacts/` prefix
- IAM role に Bedrock invoke、AgentCore invoke、S3 put/get があるか

## 10. よくあるエラー

### Bedrock model access がない

症状:

```text
AccessDeniedException
```

対処: Bedrock Console の Model access で利用 model を有効化し、region と model ID を確認します。

### AgentCore invoke 権限がない

症状:

```text
bedrock-agentcore:InvokeAgentRuntime denied
```

対処: ecsTaskExecutionRole に Runtime ARN への invoke 権限を付与します。

```bash
aws iam put-role-policy \
  --role-name ecsTaskExecutionRole \
  --policy-name InvokeAgentCore \
  --policy-document '{
    "Version":"2012-10-17",
    "Statement":[{
      "Effect":"Allow",
      "Action":"bedrock-agentcore:InvokeAgentRuntime",
      "Resource":"'"${AGENTCORE_RUNTIME_ARN}"'"
    }]
  }'
```

### S3 保存または presigned URL が失敗する

症状:

```text
AccessDenied for s3:PutObject or s3:GetObject
```

対処: Runtime role に対象 bucket/prefix への `s3:PutObject` と `s3:GetObject` を付与します。

### Runtime から期待した JSON が返らない

対処: CloudWatch Logs で AgentCore Runtime の stack trace を確認します。`agent/runtime_contract.py` の JSON contract と `agent/agentcore_entrypoint.py` の戻り値を確認します。

## 11. Cost check

正確な発生額は AWS Billing Console で確認します。主な対象は次です。

- Amazon ECS Express Mode (Fargate vCPU / メモリ)
- Application Load Balancer
- Amazon Bedrock text model
- Amazon Bedrock image model
- Bedrock AgentCore Runtime
- Amazon S3
- CloudWatch Logs

## 12. 後片付け

```bash
export ECS_SERVICE_NAME="graphic-recording-agent-demo"
./scripts/cleanup-aws-resources.sh
```

必要に応じて AgentCore Runtime を AgentCore console または AgentCore CLI で削除します。S3 bucket をこのワークショップ専用に作った場合は、empty 後に bucket も削除します。
