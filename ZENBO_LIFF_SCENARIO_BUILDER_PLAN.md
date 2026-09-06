# แผนออกแบบ /liff/scenario/ โหมดสร้าง Scenario แบบลาก-วาง

## 1. เป้าหมาย

เพิ่มโหมด "สร้าง" ในหน้า `services/liff-app/scenario/index.html` ให้ผู้ใช้ที่มีสิทธิ์ operator/admin สามารถลากบล็อกต่าง ๆ มาเชื่อมเป็น Scenario สำหรับ Zenbo ได้ โดยไม่ต้องเขียน JSON หรือผ่าน n8n

## 2. สถานะปัจจุบันทีี่เกี่ยวข้อง

- หน้าเลือก/ส่ง Preset: `services/liff-app/scenario/index.html`
- หน้า Run Scenario: `services/liff-app/scenarios/index.html`
- LIFF Config: `services/liff-app/liff-config.js`
- Auth & Role: `services/liff-app/shared/zenbo-common.js`
- Core API: `services/core-api/main.py`
  - มี `ScenarioDefinitionRequest` และ endpoint `POST /api/v1/scenario-definitions`
  - ปัจจุบัน import scenario ต้องใช้ `x_scenario_registry_token` (n8n-only)
  - มี `SCENARIO_REGISTRY` built-in และ `scenario_registry()` merge กับ sqlite `scenario_definitions`

## 3. ขอบเขตที่อนุญาต (Safety-First)

| ระดับ | อนุญาต | ไม่อนุญาต |
| --- | --- | --- |
| L0 | บล็อกพูด + สีหน้า + ไฟล้อ | ไม่ motion / vision / media |
| L1 | ลำดับขั้นตอน `steps` (2-8 ขั้นตอน) | ไม่เกิน 8 ขั้นตอน |
| L2/L3 | ตรวจคน/ท่าชี้ + แขนง `on_detect` / `on_timeout` | ไม่บันทึกพิกัด/ใบหน้า |
| L4/L5 | 2 gates + prompt + navigation URL ทีี่เชื่อถือได้ | ไม่ `autonomous_motion` / `calibrated_route` |
| L8/L10 | ไม่อนุญาตสร้างจาก UI | ต้องผ่าน operator attestation / calibrated route เท่านั้น |

## 4. โครงสร้างหน้าจอ

หน้า `scenario/index.html` แบ่งเป็น 2 แท็บ:

- แท็บ "สำเร็จรูป" — เก็บหน้าเดิมไว้
- แท็บ "สร้าง" — แสดง builder

หน้าจอ builder:

- แถบบน: ชื่อ scenario, รายละเอียด, ระดับความเสี่ยง, หมวดหมู่, icon
- Palette ซ้าย/ล่าง: บล็อกทั้งหมด
- Canvas กลาง: แสดงบล็อกเรียงลำดับ แนวตั้ง
- แถบล่าง: ปุ่ม "ตัวอย่าง JSON", "บันทึก", "ยกเลิก"

### ปฏิสัมพันธ์บนมือถือ

- Desktop: drag-and-drop ด้วย HTML5 DnD
- Mobile/Touch:
  - แตะบล็อกใน palette → แทรกตำแหน่งทีี่เลือก
  - ลากจัดเรียงผ่าน handle ด้านขวา หรือใช้ปุ่ม ↑/↓
  - เชื่อมบล็อก: เปิดโหมด "เชื่อม" → แตะ source → แตะ target

## 5. ประเภทบล็อก

| บล็อก | ฟิลด์ | ผลลัพธ์ |
| --- | --- | --- |
| `speak` | ข้อความ, voice_profile, face, rate, pitch, wheel_lights | เป็น `ScenarioScriptStep` |
| `head` | yaw, pitch, speed | ใส่ head ใน step |
| `head_sequence` | หลายขั้นตอน + delay_ms | head_sequence |
| `wheel_lights` | mode, color, brightness | wheel_lights |
| `wait` | delay_ms | สำหรับ head_sequence delay |
| `vision_gate` | action, interval_ms, timeout_ms | เริ่ม gate |
| `branch_detect` | บล็อกย่อย | `on_detect.steps` |
| `branch_timeout` | บล็อกย่อย | `on_timeout.steps` |
| `navigation` | display_url, speech_text | ใน `on_second_detect` ของ L5 |
| `stop` | ไม่มี | จุดสิ้นสุด scenario |

## 6. Data Model บน Client

```js
{
  id: "b-<uuid>",
  type: "speak",
  params: { text: "สวัสดีครับ", voice_profile: "male_child", face: "HAPPY" },
  next: ["b-2"],
  branches: {
    on_detect: ["b-d1"],
    on_timeout: ["b-t1"]
  }
}
```

ตัวแกร่งสูงสุดต้องเป็น tree กล่ายเดียว ไม่ cyclic

## 7. Compilation เป็น ScenarioDefinitionRequest

อัลกอริทึมฝั่่ client เพื่อ preview:

1. หาบล็อกเริ่มต้น (ไม่มีใครชี้มา)
2. Traversal `next` ไปเรื่อย ๆ
3. รวมลำดับ `speak`/`head`/`wheel_lights` ต่อเนื่อง:
   - ถ้ามีบล็อกเดียวและไม่มี vision_gate → `command: { text, voice_profile, face, wheel_lights }` (L0)
   - ถ้ามีหลายบล็อกและไม่มี vision_gate → `command: { steps: [...] }` (L1)
4. ถ้าพบ `vision_gate` → สร้าง `command: { vision_gate, on_detect, on_timeout }` (L2/L3)
5. ถ้าพบ 2 gates + prompt → สร้าง `command: { first_gate, prompt, second_gate, on_first_timeout, on_second_detect, on_second_timeout }` (L4/L5)
6. ตรวจสอบระดับความเสี่ยงและ required_capabilities อัตโนมัติ

ตัวอย่าง JSON สุดท้ายทีี่ส่งไป backend:

```json
{
  "scenario_id": "user-welcome",
  "version": "1.0.0",
  "title": "ทักทายผู้ใช้",
  "description": "บุ๊คกี้ทักทายพร้อมสีหน้าและไฟล้อ",
  "risk_level": "L0",
  "required_capabilities": ["THAI_TTS", "EXPRESSION", "WHEEL_LIGHTS"],
  "command": {
    "text": "สวัสดีครับ",
    "voice_profile": "male_child",
    "face": "HAPPY",
    "wheel_lights": { "mode": "breath", "color": "#00D031", "brightness": 12 }
  }
}
```

## 8. Backend Changes

### ตัวเลือกที่ 1: ใช้ Token (Phase 1)

หน้า builder compile เป็น JSON แล้วให้ admin ก๊อป JSON ไปใส่ n8n เพื่อ import

### ตัวเลือกทีี่แนะนำ: Endpoint ใหม่ (Phase 2)

เพิ่ม endpoint `POST /api/v1/scenario-drafts` ใน `services/core-api/main.py`:

- ตรวจสอบ user session/role จาก web-auth
- ยอมรับ `ScenarioDefinitionRequest`
- บันทึกลง sqlite `scenario_definitions` เช่นเดียวกับ `import_scenario_definition`
- ต้องการสิทธิ์ operator ขึ้นไป

หรือแก้ไข `import_scenario` ให้ยอมรับทั้ง `x_scenario_registry_token` และ operator session

## 9. ลำดับงาน

| Phase | งาน | ผลลัพธ์ |
| --- | --- | --- |
| 1 | ออกแบบ wireframe + ลิสต์บล็อกทั้งหมด | เอกสาร + sketch |
| 2 | สร้าง builder section ใน `scenario/index.html` | หน้า builder มองเห็นได้ |
| 3 | ทำ interaction: เพิ่ม ลบ ลาก จัดเรียง บน touch/desktop | ใช้งานได้ |
| 4 | ทำ compiler บล็อก → JSON | ดู preview JSON ได้ |
| 5 | ต่อ backend endpoint บันทึก draft | บันทึก scenario ได้ |
| 6 | ทดสอบ run ผ่าน `scenarios/index.html` | สั่่ง Zenbo ได้ |
| 7 | ปรับ UX + ข้อความ error ภาษาไทย | สมบูรณ์ |

## 10. ข้อควรระวัง

- ต้องเปิด LIFF size `Full` + `module mode` สำหรับหน้า builder
- ไม่เก็บ `SCENARIO_REGISTRY_TOKEN` บน client
- validation ฝั่่ง server เป็นหลัก เพราะ client ถูก bypass ได้
- บล็อกทีี่เกี่ยวกับ motion/autonomous/route ต้องถูกซ่อนหรือ disabled
- ควรบันทึก draft ลง localStorage ก่อนกดบันทึกจริง เพื่อป้องกัน reload/refresh
