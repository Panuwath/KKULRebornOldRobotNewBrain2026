#!/usr/bin/env python3
"""Minimal MQTT-speaking fake Zenbo for local development."""
import json
import os
import sys
import threading
import time
import uuid

import paho.mqtt.client as mqtt


SLUG = sys.argv[1] if len(sys.argv) > 1 else os.getenv("ZENBO_DEVICE_ROBOT_SLUG", "booky-1")
HOST = os.getenv("MQTT_HOST", "localhost")
PORT = int(os.getenv("MQTT_PORT", "1883"))
TRANSPORT = os.getenv("MQTT_CLIENT_TRANSPORT", "tcp").lower()
PAHO_TRANSPORT = "websockets" if TRANSPORT in {"ws", "websocket", "websockets"} else "tcp"
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"fake-zenbo-{SLUG}", transport=PAHO_TRANSPORT)


def publish(kind, payload):
    client.publish(f"zenbo/{SLUG}/status/{kind}", json.dumps(payload), qos=1)


def later(delay, kind, payload):
    timer = threading.Timer(delay, publish, args=(kind, payload))
    timer.daemon = True
    timer.start()


def on_connect(current, userdata, flags, reason_code, properties):
    if reason_code != 0:
        print(f"MQTT connection failed: {reason_code}", file=sys.stderr)
        return
    current.subscribe(f"zenbo/{SLUG}/cmd/#", qos=1)
    print(f"fake Zenbo {SLUG} connected to {HOST}:{PORT}")


def on_message(current, userdata, message):
    raw = message.payload.decode("utf-8", errors="replace")
    print(f"{message.topic} {raw}", flush=True)
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        payload = {}
    command = message.topic.rsplit("/", 1)[-1]
    if command == "interact" and payload.get("text"):
        later(1, "action_done", {"state": "DONE", "command": "interact"})
    elif command == "youtube":
        publish("youtube", {"state": "PLAYING"})
        later(3, "youtube", {"state": "ENDED"})
    elif command == "camera" and payload.get("action") == "start":
        later(1, "camera", {"type": "offer", "sdp": "v=0...", "session_id": str(uuid.uuid4())})


def heartbeat():
    while True:
        publish("heartbeat", {"version": "fake-1.0.0", "online": True})
        time.sleep(5)


username, token = os.getenv("MQTT_USERNAME"), os.getenv("MQTT_TOKEN")
if username or token:
    client.username_pw_set(username or "", token or "")
if TRANSPORT in {"ssl", "tls"}:
    client.tls_set()
client.on_connect = on_connect
client.on_message = on_message
client.connect(HOST, PORT, 60)
threading.Thread(target=heartbeat, daemon=True).start()
try:
    client.loop_forever()
except KeyboardInterrupt:
    client.disconnect()
