#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${CORE_API_URL:-http://localhost:${CORE_API_PORT:-5005}}"
ROBOT="${ROBOT:-${ZENBO_DEVICE_ROBOT_SLUG:-booky-1}}"
curl -fsS "${BASE_URL}/api/v1/robots" >/dev/null
status="$(curl -sS -o /dev/null -w '%{http_code}' "${BASE_URL}/api/v1/web-auth/me")"
[ "$status" = 401 ] || { echo "web-auth/me returned ${status}, expected 401" >&2; exit 1; }
python - "$ROBOT" <<'PY'
import json, os, sys
import paho.mqtt.publish as publish

transport = os.getenv("MQTT_CLIENT_TRANSPORT", "tcp").lower()
auth = None
if os.getenv("MQTT_USERNAME") or os.getenv("MQTT_TOKEN"):
    auth = {"username": os.getenv("MQTT_USERNAME", ""), "password": os.getenv("MQTT_TOKEN", "")}
tls = {} if transport in {"ssl", "tls"} else None
publish.single(
    f"zenbo/{sys.argv[1]}/cmd/interact",
    json.dumps({"text": "smoke test"}),
    hostname=os.getenv("MQTT_HOST", "localhost"),
    port=int(os.getenv("MQTT_PORT", "1883")),
    auth=auth,
    tls=tls,
)
PY
echo "smoke passed for ${ROBOT}"
