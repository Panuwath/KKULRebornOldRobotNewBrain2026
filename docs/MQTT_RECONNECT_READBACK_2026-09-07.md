# MQTT reconnect and heartbeat readback — 2026-09-07

Baseline main 88e334b. SSH readback at 10.101.118.149 confirmed Core configured
for mosquitto-server:1884 (TCP) and provisioning robot slug booky-1. A unique,
read-only diagnostic MQTT client authenticated and received SUBACK. During a
10-second observation it received only retained heartbeats for booky-1,
10-153-54-75 and 10-152-254-165, with no live heartbeat. No diagnostic published
any message. The booky-1 retained record did not contain current timestamp_ms,
version_name, robot_api_ready or IP fields requested for readback.

Source inspection found status subscription only in startup, with no CONNACK
callback. Clean-session reconnects can therefore lose the status subscription.
The robot's current device/app state remains unverified; this reconnect defect
is independently confirmed by source and callback regression tests.

Core now installs Paho v2 callbacks before connecting, subscribes after every
successful CONNACK and reports ready only after a matching successful SUBACK.
Disconnect, rejection, socket failure and setup errors withdraw readiness.
An asynchronous loop retries initial failures with bounded 1–30 second retry
delay. Local installed Paho source confirms loop_start's thread calls
loop_forever(retry_first_connection=True). No command publisher or command replay
logic is added or changed.

GET /health and /api/v1/robots expose process-local connection/SUBACK status and
separate live/retained heartbeat receipt counters and times. Discovery also
reports the configured robot slug. Status contains no broker credentials.
The existing API health remains a process-health response; mqtt.subscribed is
separate. Counters reset on Core restart. Retained replay never renews motion
eligibility or live robot freshness. LIFF explains transport vs subscription vs
fresh heartbeat and clearly labels retained-only records.

Validation: 204 Core tests + 34 scenario subtests pass using process isolation;
all seven Node suites pass. Eight opt-in PostgreSQL tests were not rerun because
no database query/schema/configuration changed. Tests cover reconnect resubscribe,
CONNACK/SUBACK rejection, late SUBACK after disconnect, stale SUBACK IDs,
callback-before-connect ordering, retained-vs-live evidence, setup errors and
UI descriptions. Chrome local fixture shows subscription ready, retained-only
records and zero live robots. No physical motion or APK change is performed.

Deployment must verify exact running source/public asset hashes, actual broker
CONNACK/SUBACK READY state, retained-vs-live counts, and motion flag OFF. Physical
calibration remains blocked pending fresh robot heartbeat, installed artifact,
sensors, operator and STOP evidence. This release does not claim a robot is online.
