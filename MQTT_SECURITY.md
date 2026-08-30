# MQTT token security

## Current contract

Zenbo MQTT authentication is enabled by default. Mosquitto rejects anonymous
clients and validates a username plus token; the token is supplied as the MQTT
password during the CONNECT handshake.

| Component | Required configuration |
| --- | --- |
| Mosquitto | `MQTT_AUTH_REQUIRED=true`, `MQTT_USERNAME`, `MQTT_TOKEN` |
| Core API | the same three values; it fails closed when a credential is missing |
| Android APK | build with `-PmqttUsername` and `-PmqttToken` |

## Rollout

1. Generate a long random token in the deployment secret store.
2. Set it in the server `.env`; do not commit that file.
3. Build a new Android APK with the matching device credential.
4. Deploy the MQTT broker and Core API together.
5. Install the new APK, verify a heartbeat, then issue a non-motion command and
   finally a supervised movement command.

## Operational limits

This change authenticates the MQTT connection. A single shared credential is
appropriate only for a small controlled deployment. For multiple robots, use a
different username/token and topic ACL per robot before granting network access
outside the trusted LAN. Use TLS (`mqtts://`) when the broker leaves that LAN.
