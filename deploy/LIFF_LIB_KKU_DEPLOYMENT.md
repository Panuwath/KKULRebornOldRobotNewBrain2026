# Publish LIFF at libn.kku.ac.th

Target routes:

- `https://libn.kku.ac.th/liff/` — LIFF static application.
- `https://libn.kku.ac.th/liff-api/api/v1/...` — same-origin Core API proxy.

The static pages choose `/liff-api` from `liff-config.js`; do not rewrite API
requests in n8n and do not expose MQTT from this public virtual host.

## Host deployment checklist

1. Configure local `.env` with `SSH_USER` and `SSH_IP_SERVER`.
   `SERVER_PUBLIC_HOST` is optional and defaults to `https://libn.kku.ac.th`
   for verification. The production host keeps its own `.env`; a normal deploy
   does not copy local secrets.
2. Run `./deploy.sh --dry-run`, then `./deploy.sh`. The script runs quality
   gates, creates a timestamped source backup on the host, syncs only
   Core/LIFF/Compose files, then builds and recreates only `zenbo-core-api`.
3. Add [nginx-lib-kku-liff.conf](nginx-lib-kku-liff.conf) to the existing HTTPS server block, run `nginx -t`, then reload Nginx.
4. Confirm the exact public routes return `200`:
   - `/liff/`
   - `/liff/control/`
   - `/liff-api/api/v1/robots`
5. Set the LINE Developers LIFF endpoint URL to the final `https://libn.kku.ac.th/liff/` path and test from an actual LINE client.

`deploy.sh` intentionally does not deploy Android APKs or n8n workflows. Set
`SCENARIO_REGISTRY_TOKEN` separately in the production `.env` before importing
scenarios from n8n.

## APK MQTT provisioning

The Android client must not be built with `MQTT_TOKEN`. Build it with only the
separate `deviceProvisioningToken` and `robotSlug`; at startup it calls the
HTTPS-only endpoint `/liff-api/api/v1/device/mqtt-connection`. Core validates
that bootstrap token and returns the current broker token only in memory. The
app rejects non-HTTPS provisioning URLs and does not permit a UI to redirect
the returned token to another MQTT host.

Set these values on the production host before installing a provisioning APK:

- `ZENBO_DEVICE_PROVISIONING_TOKEN` — random, per-device bootstrap secret;
- `ZENBO_DEVICE_ROBOT_SLUG` — for example `booky-1`;
- `MQTT_CLIENT_HOST`, `MQTT_CLIENT_PORT`, `MQTT_CLIENT_TRANSPORT`, and
  `MQTT_CLIENT_TOPIC_ROOT` — externally reachable broker contract.

Use `MQTT_CLIENT_TRANSPORT=ssl` with a TLS-enabled broker in production. The
current campus listener is port 1883/TCP, so an APK configured for it retains
the existing network-security limitation: MQTT credentials travel without
transport encryption. Do not expose port 1883 to an untrusted network; enable
MQTTS before treating this as an Internet-facing connection.

An HTTP/MQTT success proves gateway receipt only.  Confirm separately that the
selected APK is installed and that Zenbo performs speech or a permitted action.

## Semi-automatic APK update

Core exposes `/liff-api/api/v1/apk-update` only when all `APK_UPDATE_*`
variables are configured. Host a **release-signed** APK on HTTPS, calculate its
SHA-256 from the exact uploaded file, then set:

- `APK_UPDATE_URL`
- `APK_UPDATE_VERSION_CODE`
- `APK_UPDATE_VERSION_NAME`
- `APK_UPDATE_SHA256`
- `APK_UPDATE_NOTES` (optional)

The Zenbo client downloads only an HTTPS URL whose SHA-256 matches the manifest
and then opens Android's installer. The device operator must approve the
installation; this deployment does not support silent install.
