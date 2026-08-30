# Zenbo deployment guide

This guide documents the deployment shape without storing credentials in the
repository. Keep all real connection details in a local `.env` file or the
deployment platform's secret store.

## Required configuration

Create a local `.env` file from the following shape. Do not commit it.

```dotenv
MQTT_HOST=<mqtt-host>
MQTT_PORT=1883
MQTT_USER=<mqtt-user>
MQTT_PASSWORD=<mqtt-password>
TTS_SERVICE_URL=http://<tts-host>:8025/api/tts/binary
INTELSPHERE_API_URL=http://<compiler-host>:8032
INTELSPHERE_API_KEY=<api-key>
SSH_IP_SERVER=<deployment-host>
SSH_USER=<deployment-user>
```

Use an SSH key or a secret manager for deployment authentication. Never put a
password, API key, access token, or private key in source code, workflow JSON,
or documentation.

## Deploy

1. Build and verify the relevant service locally.
2. Transfer only the tracked source and deployment manifests to the server.
3. Provide the server-side `.env` through its secret-management process.
4. Run `docker compose up -d --build` on the server.
5. Confirm the API health endpoint, MQTT heartbeat, and a physical Zenbo action
   separately before announcing a release.

## Release checklist

- Verify the LIFF interface can see the Zenbo heartbeat.
- Verify a Thai TTS request produces audio on the robot.
- Verify STOP interrupts speech and motion.
- Record the deployed commit SHA and artifact version.
