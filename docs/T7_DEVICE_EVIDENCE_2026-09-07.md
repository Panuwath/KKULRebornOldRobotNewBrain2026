# T7 device evidence readback — 2026-09-07

Baseline main: 9a64b4a. SSH readback confirmed a fresh booky-1 heartbeat,
but it supplied no version_name, apk_sha256, robot_api_ready, safety_monitor,
motion or safety_guard fields. Field calibration returned ready=false with
15 blockers. Local adb devices listed no attached device. Fresh MQTT receipt
therefore does not identify the installed APK or establish RobotAPI readiness.

LIFF now includes an expandable device evidence panel for exactly one selected
robot. It shows the client-reported APK version/SHA256, RobotAPI, monitor,
sensor coverage, collision/fall guards and watchdog claim. Strict booleans
distinguish missing or malformed evidence from explicit true/false. Hash format
validation is not approval of the artifact. All strings render with textContent.
No claim is made about measured physical behavior or permission to move.

The panel uses the existing robot discovery response and receipt timestamp.
Selection changes, absent robots, missing/future receipts and receipts older
than ten seconds clear its rows. Existing one-second UI refresh expires data
even between discovery requests; discovery failure clears the source records.
No additional network request, publisher, installation or flag change is added.

A regression test also found IP and topic prefix surviving an incomplete new
heartbeat. Core now removes these alongside the existing readiness fields so
a fresh incomplete report cannot present an older client's network identity.
The regression failed before this change and passed afterward.

Validation: 204 Core tests and 34 scenario subtests pass with pytest in separate
processes per file; all eight Node suites pass. Eight opt-in PostgreSQL migration
tests are skipped; no database query/schema/config change is included. Chrome
fixture QA confirms missing versus explicit false, expansion, and row clearing
on deselection; screenshot inspected. Fixture rejects POST and sends no MQTT.

Release checks compare baseline Compose/runtime hashes, merge through a PR,
deploy using source backup and the previous image, then verify deployed hashes
and live GET-only browser/API readback. Core and APK relative flags remain OFF.
Installed APK verification and supervised S5/T8/T9 physical acceptance remain
pending device access, operator, sensor and STOP evidence.
