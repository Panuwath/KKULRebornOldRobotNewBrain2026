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

## Environment Variables ที่ต้องตั้งใน n8n

ตั้งใน **n8n → Settings → Variables** (หรือ Credentials) ก่อน activate:

| ตัวแปร | ค่า | หมายเหตุ |
|---|---|---|
| `CORE_API_URL` | `http://10.101.118.149:5005` | (หรือ host จริงของ core-api) |
| `LINE_CHANNEL_ACCESS_TOKEN` | `<channel access token>` | ใช้ใน header `Authorization: Bearer ...` |
| `STATUS_FORWARD_URL` | webhook ปลายทางที่รับสถานะ | ใช้ใน status monitor |

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
