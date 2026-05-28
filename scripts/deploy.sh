#!/usr/bin/env bash
# EC2へアプリファイルを転送してdocker composeを起動するデプロイスクリプト

set -euo pipefail

STACK_NAME="GitlabAiInceptionStack"
APP_DIR="/home/ubuntu/gitlab-ai-inception"
KEY_FILE="./gitlab-ai.pem"

echo "=== CDKスタックから接続情報を取得 ==="
INSTANCE_IP=$(aws cloudformation describe-stacks \
  --stack-name "${STACK_NAME}" \
  --query "Stacks[0].Outputs[?OutputKey=='PublicIP'].OutputValue" \
  --output text)

if [[ -z "${INSTANCE_IP}" ]]; then
  echo "Error: PublicIPが取得できません。CDKデプロイが完了しているか確認してください。"
  exit 1
fi
echo "EC2 IP: ${INSTANCE_IP}"

echo "=== SSH秘密鍵をSSMから取得 ==="
if [[ ! -f "${KEY_FILE}" ]]; then
  KEY_PARAM=$(aws cloudformation describe-stacks \
    --stack-name "${STACK_NAME}" \
    --query "Stacks[0].Outputs[?OutputKey=='SshKeyCommand'].OutputValue" \
    --output text)
  # SshKeyCommandに含まれるパラメータ名を抽出して実行
  SSM_PARAM=$(echo "${KEY_PARAM}" | grep -oP '(?<=--name )\S+')
  aws ssm get-parameter \
    --name "${SSM_PARAM}" \
    --with-decryption \
    --query Parameter.Value \
    --output text > "${KEY_FILE}"
  chmod 600 "${KEY_FILE}"
  echo "秘密鍵を保存しました: ${KEY_FILE}"
fi

SSH_OPTS="-i ${KEY_FILE} -o StrictHostKeyChecking=no -o ConnectTimeout=10"

echo "=== アプリファイルを転送 ==="
rsync -avz \
  --exclude='.git/' \
  --exclude='infra/node_modules/' \
  --exclude='infra/cdk.out/' \
  --exclude='infra/dist/' \
  --exclude='*.pem' \
  --exclude='*.key' \
  -e "ssh ${SSH_OPTS}" \
  ./ "ubuntu@${INSTANCE_IP}:${APP_DIR}/"

echo "=== .envファイルを転送 ==="
if [[ -f ".env" ]]; then
  scp ${SSH_OPTS} .env "ubuntu@${INSTANCE_IP}:${APP_DIR}/.env"
else
  echo "警告: .envファイルが見つかりません。${APP_DIR}/.envを手動で設定してください。"
fi

echo "=== docker compose up ==="
ssh ${SSH_OPTS} "ubuntu@${INSTANCE_IP}" \
  "cd ${APP_DIR} && docker compose pull && docker compose up -d --build"

echo ""
echo "=== デプロイ完了 ==="
echo "GitLab URL:      http://${INSTANCE_IP}"
echo "Webhook URL:     http://${INSTANCE_IP}:8001/webhook"
echo "SSH:             ssh -i ${KEY_FILE} ubuntu@${INSTANCE_IP}"
echo ""
echo "GitLab初回起動には5分程度かかります。"
echo "初期パスワード: docker exec gitlab cat /etc/gitlab/initial_root_password"
