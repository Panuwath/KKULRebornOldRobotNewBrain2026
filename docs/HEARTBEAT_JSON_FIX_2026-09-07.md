# Heartbeat JSON encoding and guard reporting — 2026-09-07

Baseline main b356689. Production booky-1 was sending fresh MQTT messages,
but Core registry contained raw rather than decoded fields. Strict parsing
reported an invalid control character at position 280 in a 783-character
payload. A one-off read-only diagnostic decoded only the reported version/IP
and presence of a newline: 1.9.48-stable, 10.152.253.98, newline in broker.summary.
That diagnostic was never used for readiness or written back to Core.

Source confirms getActiveBrokerSummary joins two lines with a newline while
escapeJson only handled quotes/backslashes. Every heartbeat includes this
summary, so the unescaped newline invalidates the complete JSON object.

JsonStrings now escapes all U+0000–U+001F controls, quotes, backslashes and
surrogate code units. Thai text remains intact. ZenboClientService uses it for
all existing escaped string fields. Version advances to 1.9.49/code 725 to
distinguish the corrected artifact. A local debug build succeeds; it is not a
published, installed or field-approved release. Relative flags remain OFF.

Core keeps strict JSON parsing. Malformed/non-object heartbeats withdraw all
previous readiness evidence, retain live transport receipt only, and report a
Core-owned heartbeat_payload_state of INVALID_JSON or INVALID_SHAPE. Valid
objects report VALID; payload fields cannot override that state. Raw malformed
heartbeat text is no longer returned from discovery. Retained malformed
heartbeats never become fresh. LIFF explains the APK JSON problem explicitly.

Existing guard visuals also treated absent fields as ON or OFF inconsistently.
The selected-robot badge and toggle now distinguish unknown, partial and mixed
reports, requiring strict booleans and a receipt within ten seconds. The twin
starts with hidden rings and withdraws them on incomplete, disconnected or
expired telemetry. HTTP policy submission is labeled as a request awaiting
heartbeat, not confirmed physical application. No policy request body, command
endpoint or actuator behavior changes.

Validation: 205 Core tests + 34 scenario subtests; eight Node suites; 22 Android
unit tests. Eight opt-in PostgreSQL migration tests skipped (no database
changes). Actual Java encoder output round-trips through Python's strict JSON
parser for Thai, emoji, quotes, backslashes and all 32 control characters.
Both page scripts and twin script parse. Chrome fixture shows INVALID_JSON,
empty evidence rows, Guard UNKNOWN and hidden safety rings. Production release
requires source/running/public hash comparison and authenticated browser readback.

ADB lists no USB device; connection to the reported robot IP on port 5555 was
refused. Installing the corrected signed APK and proving fresh valid heartbeat
remain pending device access. No OTA request, install, policy mutation or robot
motion is performed. Physical S5/T8 and T9 activation remain separate gates.
