#!/usr/bin/env bash
# ==============================================================================
# Script สำหรับ SSH Deploy Zenbo Docker Services ไปยัง Server
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -f .env ]; then
  echo "❌ Error: .env file not found!"
  exit 1
fi

# Load .env
set -a
source .env
set +a

SSH_IP="${SSH_IP_SERVER:-10.101.118.149}"
USER="${SSH_USER:-ping}"

echo "=========================================================="
echo "🚀 Target Server: $USER@$SSH_IP"
echo "📦 Ports: MQTT=${MQTT_PORT:-1883}, TTS=${TTS_PORT:-8000}, CoreAPI=${CORE_API_PORT:-5005}, Compiler=${COMPILER_PORT:-5006}, MCP=${MCP_PORT:-8088}"
echo "=========================================================="

echo "📂 [1/3] Syncing files to remote server..."
rsync -avz --progress \
  --exclude 'node_modules' \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '.git' \
  --exclude '*.apk' \
  --exclude 'zenbo-client-android' \
  ./ "$USER@$SSH_IP:~/zenbo-hackathon/"

echo "🐳 [2/3] Building and starting Docker containers..."
ssh "$USER@$SSH_IP" "cd ~/zenbo-hackathon && docker compose up -d --build"

echo "✅ [3/3] Deployment complete! Checking container statuses..."
ssh "$USER@$SSH_IP" "docker compose -f ~/zenbo-hackathon/docker-compose.yml ps"

echo "🎉 All services are up and running!"
