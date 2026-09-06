# n8n Workflows — เตรียมนำขึ้น n8n (n8n-centric)

ชุด workflow ใหม่ที่ออกแบบให้ **n8n เป็นแกนกลางจริง** แทนที่จะเป็นแค่ตัวรับ webhook แล้ว delegate ให้ compiler `auto_dispatch` ไปเอง

## สรุปปัญหาที่แก้ (จากผลวิเคราะห์ Section 11)

| ปัญหาเดิม | การแก้ไขใน workflow ใหม่ |
|---|---|
| n8n เข้าถึง `core-api` แบบอ้อมผ่าน `auto_dispatch` เท่านั้น | n8n เรียก `core-api` ตรง 2 จุด: `/api/v1/commands/compile` (preview) และ `/api/v1/robot/interact` + `/api/v1/robots/{slug}/stop` (dispatch) |
| ไม่รองรับ multi-robot ใน chat/voice | เพิ่ม node "Resolve Target Robot" (รองรับ `@slug`, `robot:slug`, `USER_ROBOT_MAP`) + query `/api/v1/robots` เพื่อเลือกเครื่องจริง |
| TTS ผูกกับ server นอก `:8025` (schema ต่างจาก compose) | ใช้ `core-api` เป็น unified proxy ผ่าน `/api/v1/robot/interact` + `voice_profile` (ไม่แตะ TTS ตรง) |
| n8n ไม่รู้สถานะ robot / telemetry | เพิ่ม workflow MQTT trigger ฟัง `zenbo/+/status/#` แล้ว normalize + forward |

## ไฟล์ที่สร้าง

| ไฟล์ | หน้าที่ |
|---|---|
| `zenbo_line_chat_orchestrator.json` | ตัวหลัก: LINE text → parse → resolve robot → compile preview → dispatch ตรง + emergency branch → reply LINE |
| `zenbo_line_voice_orchestrator.json` | LINE voice → download → resolve robot → compile → dispatch → reply |
| `zenbo_robot_status_monitor.json` | MQTT trigger ฟัง heartbeat/vision/error → normalize → forward ไป webhook ปลายทาง |
| `zenbo_tts_gateway.json` | TTS webhook → resolve robot → `/api/v1/robot/interact` (voice_profile) → respond |
| `zenbo_scenario_run_gateway.json` | scenario webhook → Core API creates an idempotent pending run; it does not publish MQTT directly |
| `zenbo_scenario_confirm_gateway.json` | explicit-confirmation webhook → Core API dispatches one existing scenario run |
| `zenbo_scenario_registry_import.json` | reviewed L0 scenario webhook → token-gated Core registry import |
| `zenbo_music_playlist_registry_import.json` | reviewed YouTube playlist webhook → token-gated Core registry import; it never plays media by itself |
| `zenbo_music_dance_every_10_minutes.json` | every 10 minutes → one bounded, safety-gated playlist dance window |
| `zenbo_field_attestation_gateway.json` | operator checklist → token-gated L7 field-attestation record |

## Environment Variables ที่ต้องตั้งใน n8n

ตั้งใน **n8n → Settings → Variables** (หรือ Credentials) ก่อน activate:

| ตัวแปร | ค่า | หมายเหตุ |
|---|---|---|
| `CORE_API_URL` | `http://10.101.118.149:5005` | (หรือ host จริงของ core-api) |
| `LINE_CHANNEL_ACCESS_TOKEN` | `<channel access token>` | ใช้ใน header `Authorization: Bearer ...` |
| `STATUS_FORWARD_URL` | webhook ปลายทางที่รับสถานะ | ใช้ใน status monitor |
| `SCENARIO_REGISTRY_TOKEN` | `<long random shared secret>` | ใช้เฉพาะ registry import; ต้องตรงกับ Core API |

## Credentials ที่ต้องผูก

| Credential | ใช้ใน workflow | หมายเหตุ |
|---|---|---|
| LINE Messaging API (httpHeaderAuth) | chat + voice orchestrator | workflow ใช้ `LINE_CHANNEL_ACCESS_TOKEN` env แทน credential เดิม ถ้าต้องการแบบ credential ให้แก้ `headerParameters` เป็น credential id |
| MQTT (`Zenbo-Mosquitto-149`) | status monitor | id `vFZ4IDOfufWTtfrj` (ถ้าไม่มีใน instance ให้สร้างใหม่) |

## วิธี Import เข้า n8n

1. เข้า n8n UI (`https://libn.kku.ac.th` หรือ `http://localhost:5678`)
2. กด **Workflows → Import from File** แล้วเลือก `.json` ในโฟลเดอร์ `n8n_workflows/`
3. ตั้ง Environment Variables ตามตารางด้านบน
4. ผูก Credentials (LINE, MQTT)
5. เปิดใช้งาน (Active) workflow ที่ต้องการ

### Scenario run gateway

Import `zenbo_scenario_run_gateway.json` for a low-code entry point to the
scenario registry. POST a validated request such as
`{"scenario_id":"intro_booky","robot_slug":"10-153-54-75","idempotency_key":"<unique key>","source":"n8n"}`
to its webhook. It returns `AWAITING_CONFIRMATION`; a LIFF/operator call to
Core's `/api/v1/scenario-runs/{run_id}/confirm` is still required before the
client receives a command. This separation is intentional: n8n must not
publish raw MQTT robot commands.

### Scenario confirmation gateway

Import `zenbo_scenario_confirm_gateway.json` when the approval step lives in
n8n. POST `{"run_id":"<run id>"}` only after an operator or LIFF has shown the
scenario preview. It calls Core's confirm endpoint; retrying after a successful
confirmation returns a conflict rather than dispatching twice. Query
`GET /api/v1/scenario-runs/{run_id}` for the state; `DISPATCHED` is gateway
acceptance, while `SUCCEEDED` requires telemetry from the Zenbo client.

### Scenario registry import

Import `zenbo_scenario_registry_import.json` only after a scenario has been
reviewed. It calls the token-protected `/api/v1/scenario-definitions` endpoint.
Core accepts L0 stationary speech/expression/head/light payloads, L1 scripts
with 2–8 stationary `steps`, L2 anonymous `detect_face`/`detect_person` gates,
and L3 anonymous `gesture_point` gates with short local detect/timeout response
scripts. L4 chains anonymous presence detection to a spoken prompt and an
anonymous gesture gate; it never interprets or stores pointing coordinates.
L5 uses the same consent flow and may open only a Core-approved display URL
after gesture detection; the built-in library map URL is allow-listed. Core forces
`confirmation=REQUIRED` and rejects movement, person recognition, debug camera
preview, behavior, media, canned actions, and remote-control fields, except for
the separately validated L8 `autonomous_motion` contract below.
L6 additionally refuses dispatch until the selected APK reports fresh RobotAPI,
isolated MQTT topic, enabled collision/fall guards, and required capabilities.
For L7, import `zenbo_field_attestation_gateway.json` and post an operator name
with `tts_checked`, `vision_checked`, and `display_checked` all set to `true`.
Core accepts the token-gated attestation for 15 minutes, then requires a new
field check before dispatching another L7 run.
Every scene must include a supported `face`; Core then attaches a stationary
head gesture and post-speech resting cue, and publishes the Thai behavior
description to LIFF. Set the same non-empty
`SCENARIO_REGISTRY_TOKEN` in Core and n8n; without it, importing is disabled.

### Music and dance every 10 minutes

Import `zenbo_music_dance_every_10_minutes.json` only after the selected
playlist and canned dance action are calibrated on the physical Zenbo. Set
`ZENBO_MUSIC_PLAYLIST_ID`, `ZENBO_MUSIC_ROBOT_SLUG`, `ZENBO_DANCE_ACTION_ID`,
and optionally `ZENBO_MUSIC_DANCE_DURATION_SECONDS` in n8n. Core must also set
`MUSIC_DANCE_AUTOMATION_ENABLED=true`; each run requires fresh field-readiness
telemetry and sends to the selected robot topic only. The scheduled workflow
does not publish raw MQTT and each music/dance window is bounded to 10–180
seconds so an emergency stop can cancel it before the next cycle.

### Music playlist registry import

Import `zenbo_music_playlist_registry_import.json` after reviewing each
YouTube URL.  The webhook posts a playlist with `playlist_id`, `version`,
`title`, `mood`, and one or more `{title, youtube}` tracks. Core validates that
each URL is an HTTPS YouTube video, stores it under the same registry token,
and returns metadata only. `POST /api/v1/music-playlists/{playlist_id}/pick`
returns one random **preview** for the selected Zenbo; the LIFF operator must
still explicitly confirm the normal YouTube command before it is dispatched.

## จุดที่ต้องปรับตามสภาพแวดล้อมจริงก่อนขึ้น production

1. **`USER_ROBOT_MAP`** ใน node "Resolve Target Robot" — ปัจจุบันเป็น `{}` เปล่า ให้ใส่ map เช่น `{ "U123...": "zenbo1" }` เพื่อผูก LINE user กับ robot เฉพาะเครื่อง (แก้ 2 ไฟล์: chat + voice)
2. **`CORE_API_URL`** — ถ้า core-api ไม่ได้ expose ที่ `10.101.118.149:5005` ให้เปลี่ยนตามจริง
3. **LINE reply** — workflow ใช้ `LINE_CHANNEL_ACCESS_TOKEN` จาก env; ถ้า instance ปัจจุบันใช้ credential แบบ httpHeaderAuth อยู่แล้ว ให้สลับเป็น credential เพื่อความปลอดภัย
4. **Voice ASR** — workflow ปัจจุบันส่ง `messageId` เป็น placeholder ไป compile (ยังไม่ทำ ASR จริง) ต้องต่อ ASR service (KKU IntelSphere STT) ตาม path เดิมของ `zenbo_line_voice_workflow.json` ที่อัปโหลดไฟล์เสียงจริง

## ความสัมพันธ์กับ workflow เดิม (ไม่ลบทิ้ง)

workflow เดิมใน `n8n_workflows/` ยังเก็บไว้เป็น reference:
- `zenbo_line_text_ai_workflow.json` / `zenbo_line_bot_workflow.json` → ถูกแทนที่ด้วย `zenbo_line_chat_orchestrator.json`
- `zenbo_line_voice_workflow.json` → ถูกแทนที่ด้วย `zenbo_line_voice_orchestrator.json`
- `zenbo_tts_server_workflow.json` → ถูกแทนที่ด้วย `zenbo_tts_gateway.json`
- `zenbo_connect_booky_workflow.json` → ยังใช้ได้ (handshake แบบ broadcast) แต่ไม่ multi-robot
- `zenbo_dev_test_workflow.json` → ยังใช้เป็น endpoint ทดสอบ compiler ได้
### L8: guarded autonomous micro-movement

The scenario registry also accepts `risk_level: "L8"` with exactly one
`autonomous_motion` object. It can only send a straight 0.05-0.15m forward
movement at speed 1, with collision/fall guard and a <=1.5-second watchdog.
Core additionally requires a current client heartbeat with Sonar and Drop
Laser capabilities, a fresh operator field attestation, and
`AUTONOMOUS_MOTION_ENABLED=true`. n8n must import the manifest; it cannot
construct raw `motion` or MQTT payloads.

### L9: movement completion telemetry

For L8 runs, `SPEECH_COMPLETED` is no longer interpreted as success. The APK
publishes `MOTION_STARTED`, then only publishes `MOTION_COMPLETED` after its
local watchdog calls the Zenbo SDK stop operation. A manual stop, new safety
policy, or Sonar/Drop-Laser breach publishes `SAFETY_STOPPED` instead. Use
`GET /api/v1/scenario-runs/{run_id}` to observe `RUNNING`, `SUCCEEDED`, or
`SAFETY_STOPPED`; do not infer physical motion from MQTT acceptance alone.

### L10: calibrated route, one segment at a time

Use the token-gated `POST /api/v1/calibrated-routes` endpoint to publish a
reviewed route of 1-6 L8-compatible forward micro-motion segments. Start with
`POST /api/v1/calibrated-route-runs`, then call
`POST /api/v1/calibrated-route-runs/{route_run_id}/confirm-next` for exactly
one segment. Core refuses the next segment until the previous segment reports
`MOTION_COMPLETED`; it aborts the route after `FAILED` or `SAFETY_STOPPED`.
Every segment independently requires fresh field readiness, attestation, and
`AUTONOMOUS_MOTION_ENABLED=true`. Do not have n8n publish MQTT motion payloads.

### L11: recovery after a safety stop

When a segment reports `SAFETY_STOPPED`, Core changes the route run to
`RECOVERY_REQUIRED`; n8n must not retry automatically. An operator first checks
the physical area and records a new field attestation, then a token-gated
`POST /api/v1/calibrated-route-runs/{route_run_id}/recover` with
`{"operator_name":"...","action":"retry"}` returns the run to
`AWAITING_SEGMENT_CONFIRMATION`. `action: "cancel"` permanently cancels that
run. The replacement attestation must be newer than the safety stop.

### L12: certify the exact route version

Before creating a calibrated route run, use token-gated
`POST /api/v1/calibrated-routes/{route_id}/certification` with an operator name
and all three checks set to `true`: path clearance, segment measurements, and
emergency stop. Certification lasts 24 hours and is tied to the route version;
any edit makes it stale. With `ROUTE_CERTIFICATION_REQUIRED=true` (the default),
`POST /api/v1/calibrated-route-runs` rejects missing or stale certification.

### L13-L20: supervised autonomy governance

For every calibrated-route run, n8n must create the following short-lived,
token-gated records; Core rejects a route run without the resulting L20 permit.

1. **L13 operator authorization:** `POST /api/v1/autonomy/authorizations`.
   Use a role and the required scope (`route_release`, `operation_permit`, or
   `safety_recovery`). The registry token authenticates n8n; the recorded name
   is an audit attribution, not a substitute for enterprise identity proof.
2. **L14 route release:** `POST /api/v1/calibrated-routes/{route_id}/release`.
   An active release is tied to the exact route version and optional robot list.
3. **L15 localization readiness:** record a map/pose/drift/fallback-stop check
   at `POST /api/v1/robots/{robot_slug}/localization-attestation`.
4. **L16 safety envelope:** record obstacle stop, exclusion zone, and manual
   takeover checks at `POST /api/v1/robots/{robot_slug}/safety-envelope`.
5. **L17 zone lease:** reserve one area using
   `POST /api/v1/autonomy/zone-reservations`; a second active reservation for
   the same zone is rejected. Core releases the lease automatically after a
   route completes, aborts, or is cancelled; it deliberately keeps the lease
   during `SAFETY_STOPPED` recovery. An operator may release it using
   `POST /api/v1/autonomy/zone-reservations/{reservation_id}/release`.
6. **L19 fault drill:** record emergency stop, lost-localization stop and
   obstacle-stop drills at `POST /api/v1/robots/{robot_slug}/fault-drills`.
   A drill expires after seven days.
7. **L20 operation permit:** create at
   `POST /api/v1/autonomy/operation-permits`, then provide its `permit_id` as
   `operation_permit_id` when calling `POST /api/v1/calibrated-route-runs`.
   The permit expires within 1-15 minutes and binds route version, robot and
   zone reservation.

Core stores the `operation_permit_id` on the route run and revalidates it before
each segment. `SAFETY_STOPPED` revokes that permit automatically. A recovery
retry must therefore provide a newly issued `operation_permit_id` alongside its
newer L11 field attestation; it cannot reuse the permit from before the stop.
An operator workflow may revoke a permit early through token-gated
`POST /api/v1/autonomy/operation-permits/{permit_id}/revoke`.

**L18 supervision:** read `GET /api/v1/autonomy/supervisor` for current permits,
zone leases and unresolved alerts. A `SAFETY_STOPPED` segment opens a critical
alert and still requires the L11 recovery flow. These are governance and
telemetry controls only; do not present them as proof that physical localization,
obstacle sensing, or autonomous movement has passed on a real Zenbo.

Before requesting a permit, call the read-only
`GET /api/v1/autonomy/preflight?route_id=...&robot_slug=...` with the optional
`zone_reservation_id`, `authorization_id`, and `permit_id`. It separates
`permit_blockers` (L12–L19 records still missing) from `dispatch_blockers`
(including current L7 field attestation and client telemetry). This endpoint
never creates a permit or publishes motion.

Import `zenbo_operation_permit_gateway.json` only after the L13–L19 records
have been created by approved operator workflows. It receives a reviewed permit
request and forwards it to Core; it cannot bypass any Core prerequisite.

Import `zenbo_operation_permit_revoke_gateway.json` for an operator-approved
early revoke. Import `zenbo_route_recovery_gateway.json` only after the physical
area has been rechecked, a new L7 field attestation was recorded and a new L20
permit was issued. Its `retry` payload must include `operation_permit_id`;
`cancel` intentionally does not need one.

For the physical acceptance sequence and expected Core states, use
[`FIELD_TEST_L13_L20.md`](../FIELD_TEST_L13_L20.md). Do not put MQTT, registry,
or provisioning tokens into the field-test notes.
