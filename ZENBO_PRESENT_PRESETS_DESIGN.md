# Zenbo Preset / Presentation Mode — การออกแบบโหมดนำเสนอสำเร็จรูป

> วิเคราะห์ก่อนลงมือตามโจทย์: เพิ่ม route/mode ใหม่ใน `/liff/control/` (หรือหน้าแยก) ที่เป็น
> **โหมดนำเสนอ (Preset / Presentation)** สำเร็จรูปสำหรับ Zenbo อย่างน้อย 20 presets
> ครอบคลุมงานต้อนรับนำชม ทักทายกรรมการ ถ่ายรูป โหมดติดตาม เดินสำรวจ สื่อสาร mark ฐาน บันเทิง เล่านิทาน ฯลฯ

---

## 1. สรุปสถานะปัจจุบัน (สิ่งที่วิเคราะห์ได้จากโค้ดจริง)

### 1.1 โครงสร้างหน้า LIFF ปัจจุบัน

| Path | ไฟล์ | หน้าที่ |
|---|---|---|
| `/liff/` | `index.html` (717 L) | controller หลัก: connect, motion, head, face, lights, vision, TTS |
| `/liff/control/` | `control/index.html` (368 L) | จอยสติ๊ก + สั่งด้วยภาษาธรรมชาติ (compile-preview-dispatch) |
| `/liff/command/` | `command/index.html` (223 L) | สั่งด้วยคำพูด → compile → dispatch |
| `/liff/history/` | `history/index.html` (115 L) | ประวัติคำสั่ง |
| `/liff/navigation/` | `navigation/index.html` (8 L) | นำทาง Booky (minified) |

### 1.2 ความสามารถที่ใช้ได้จริง (จาก `InteractCommand` ใน `services/core-api/main.py:225`)

Presets ทำได้โดยการ **compose fields เหล่านี้** ผ่าน `/api/v1/robot/interact` (1 call = 1 action set):

| กลุ่ม | Field | ค่าที่รองรับ |
|---|---|---|
| พูด (TTS) | `text` + `voice_profile` | `female_child / female_young / female_adult / male_child / male_young / male_adult` |
| ใบหน้า | `face` | `HAPPY, DEFAULT, INTEREST, DOUBT, EXPECT, SHY, WORRIED, SHOCK, TIRED, SINGING, PROUD` |
| เคลื่อนที่ | `motion` | `x`(-2..2 m), `y`, `theta`(-180..180°), `speed`(1-5) |
| ศีรษะ | `head` / `head_sequence` | yaw(-45..45°), pitch(-15..55°), `delay_ms`(≤10000) |
| ท่าทาง | `action` | `action_id` ∈ {2,3,5,11,18,22,23,44}, `stop` |
| ไฟล้อ | `wheel_lights` | mode ∈ {breathing, blinking, charging, marquee, off} |
| ท่าอารมณ์ | `emotional_action` | `action_id` + `faces:[{face, duration}]` |
| พฤติกรรม | `behavior` | `look_at_user, track_face, follow_face, follow_object` |
| วิชัน | `vision` | `detect_face, detect_person, gesture_point, recognize_person, measure_height, cancel_*` |
| YouTube | `youtube` | `url` + `dance_action_ids` + `loop_dance` |
| นำทาง | `navigation` | `display_url` + `speech_text` + `step_speeches` |

### 1.3 ข้อจำกัดที่บังคับการออกแบบ (สำคัญ)

1. **1 call = 1 action set** — ปัจจุบันไม่มี "sequence player" ฝั่ง server คำสั่งหลายขั้นตอนต้อง
   ไล่ส่งทีละขั้นจากฝั่ง client (LIFF JS) โดยหน่วงเวลาเอง
2. **ไม่มี ack "พูดจบแล้ว"** — bridge เก่า (v1.28-keepalive) ยังไม่ส่งสถานะกลับ เราไม่รู้ว่าพูดจบเมื่อไร
   → ต้องประมาณ `delay_ms` จากความยาวข้อความ
3. **TTS dual-system** — ควรใช้ `voice_profile` (neural, core-api validate ได้) ไม่ใช่ `voice/rate/pitch`
   เก่าที่ผูก `:8000`
4. **persona ไม่คงที่** — connect ใช้เสียง "บุ๊คกี้...ครับ" (boy) แต่ตัวอย่าง compiler ใช้ "หนูชื่อเซนโบ"
   (girl) → ต้องตัดสินใจ persona เดียวใน presets

---

## 2. แนวคิดการออกแบบ (Concept)

**Preset = ลำดับขั้นตอน (sequence of steps)** แต่ละ step คือ `InteractCommand` payload หนึ่งชุด
+ `delay_ms` (รอก่อนส่งขั้นนี้)

```
preset ──► [ step1 ] ─delay─► [ step2 ] ─delay─► ... ─► [ stepN ]
             │                     │
             └─ /interact ──────── └─ /interact
```

- **Playback engine** อยู่ฝั่ง LIFF JS (client) ไล่ส่ง step ตามลำดับ
- **Stop ฉุกเฉิน** ระหว่างเล่น → `POST /api/v1/robots/{slug}/stop` (หยุดทุกอย่างทันที)
- **ไม่ต้องแก้ core-api** — presets เป็นการ compose fields ที่มีอยู่แล้ว (ลด risk, ไม่ touch server)

### 2.1 Data Schema ของ Preset

```json
{
  "id": "welcome_library",
  "category": "presentation",
  "title_th": "กล่าวต้อนรับนำชม (สำนักหอสมุด มข.)",
  "icon": "fa-solid fa-door-open",
  "duration_label": "~30 วิ",
  "safety_note": "หุ่นจะพูดพร้อมไฟเขียว แล้วโค้งคำนับ",
  "steps": [
    { "delay_ms": 0,    "payload": { "wheel_lights": { "mode": "breathing", "color": "0x00D031", "brightness": 15 } } },
    { "delay_ms": 300,  "payload": { "text": "...", "voice_profile": "female_young", "face": "HAPPY" } },
    { "delay_ms": 30000,"payload": { "head_sequence": [ { "yaw":0,"pitch":-15,"speed":2,"delay_ms":800 }, { "yaw":0,"pitch":10,"speed":2,"delay_ms":0 } ] } }
  ]
}
```

### 2.2 Route / UI

- หน้าใหม่: **`/liff/present/index.html`** (ขนานกับ `/liff/control/`)
- ข้อมูล presets เก็บเป็น **`/liff/present/presets.js`** (`window.ZENBO_PRESETS = [...]`) — แก้ไขง่าย ไม่ต้อง rebuild
- เพิ่มปุ่มลิงก์ "โหมดนำเสนอ" ใน navbar ของ `/liff/`, `/liff/control/`, `/liff/command/`
- UI หน้า: เลือก robot → กริดการ์ด preset แบ่งหมวด → กดเล่น (แสดง progress step) → ปุ่ม STOP ใหญ่

### 2.3 การประมาณ delay (ไม่มี ack)

- สูตร: `delay_ms ≈ ceil(text.length / 5) * 1000` (Thai TTS ≈ 5 ตัวอักษร/วินาที)
- ขั้นเคลื่อนที่/ศีรษะให้ delay ตามท่าจริง (หมุน 180° ≈ 3-4 วิ)
- หมายเหตุ: หลัง robot อัปเกรด bridge ให้ส่ง ack "พูดจบ" จะเปลี่ยนเป็น event-driven แทน fixed delay

---

## 3. รายการ Presets 23 ตัว (6 หมวด)

> สัญลักษณ์ย่อในตาราง: `say(txt, face)` = text+face · `move(x,y,θ)` = motion · `turn(θ)` = motion θ
> · `head(yaw,pitch)` = head · `nod()` = โค้งคำนับ (pitch ลง-ขึ้น) · `shake()` = ส่ายหัว
> · `light(mode,color)` = wheel_lights · `dance(id)` = action · `follow(on)` = behavior
> · `vision(a)` = vision · `nav(...)` = navigation · `yt(url,ids)` = youtube

### หมวด A — พิธีการ / งานนำเสนอ (Presentation & Ceremony)

| # | id | ชื่อ | steps (ย่อ) | duration |
|---|---|---|---|---|
| A1 | `welcome_library` | กล่าวต้อนรับนำชม (สำนักหอสมุด มข.) | `light(breathing,green)` → `say(สคริปต์ต้อนรับ 30วิ, HAPPY)` → `nod()` → `turn(180)` + `say(เชิญชม) face PROUD` | ~30-40 วิ |
| A2 | `greet_committee` | กล่าวทักทายกรรมการ | `light(breathing,blue)` → `say(ทักทาย+แนะนำตัว, SHY)` → `nod()` → `say(พร้อมรับฟัง, EXPECT)` | ~20 วิ |
| A3 | `intro_photo` | แนะนำตัว + ขอถ่ายรูป | `say(แนะนำตัว, HAPPY)` → `dance(22)` + `face SINGING` → `say(ช่วยถ่ายรูปหน่อยครับ, SHY)` → `light(marquee,white)` | ~25 วิ |
| A4 | `open_event` | กล่าวเปิดงาน | `light(charging,green)` → `say(กล่าวเปิด, PROUD)` → `nod()` | ~15 วิ |
| A5 | `close_event` | กล่าวปิดงาน | `say(กล่าวขอบคุณ+ปิด, HAPPY)` → `nod()` → `light(off)` | ~12 วิ |
| A6 | `tour_library` | นำชมเส้นทางภายในห้องสมุด | `say(กำลังนำชม, HAPPY)` → `nav(display_url, speech, steps)` → `follow(on)` | ~30 วิ |

### หมวด B — เคลื่อนที่ / สำรวจ (Motion & Exploration)

| # | id | ชื่อ | steps (ย่อ) | duration |
|---|---|---|---|---|
| B1 | `follow_mode` | โหมดติดตาม (Follow Me) | `vision(detect_face)` → `follow(on)` → `say(ตามผมมาเลยครับ, HAPPY)` | ต่อเนื่อง |
| B2 | `explore_route` | โหมดเดินสำรวจในแผนที่ที่กำหนด | `say(เริ่มเดินสำรวจ, HAPPY)` → `nav(route)` → `move(x=1.0)` × N ตาม route → `follow(off)` | ตาม route |
| B3 | `mark_base` | โหมด mark ฐาน (กลับจุดเริ่มต้น) | `say(บันทึกจุดฐานแล้ว, PROUD)` → `light(blinking,amber)` → `turn(180)` → `move(x=-1.0)` กลับฐาน | ~20 วิ |
| B4 | `patrol_area` | ตรวจพื้นที่ / ลาดตระเวน | `vision(detect_person)` → `turn(90)` → `move(1.0)` → `turn(90)` → `move(1.0)` → `vision(cancel_person)` | ~30 วิ |

### หมวด C — สื่อสาร (Communication)

| # | id | ชื่อ | steps (ย่อ) | duration |
|---|---|---|---|---|
| C1 | `reception_mode` | โหมดสื่อสาร / รับแขก | `vision(detect_face)` → `say(สวัสดี ยินดีต้อนรับ, HAPPY)` → `look_at_user(on)` → `follow(off)` | ต่อเนื่อง |
| C2 | `faq_answer` | ถาม-ตอบ FAQ ห้องสมุด | `say(ตอบคำถาม: เวลาทำการ/บริการ, EXPECT)` → `face HAPPY` → `say(มีคำถามเพิ่มไหมครับ, INTEREST)` | ~20 วิ |

### หมวด D — บันเทิง (Entertainment)

| # | id | ชื่อ | steps (ย่อ) | duration |
|---|---|---|---|---|
| D1 | `tell_story` | เล่านิทาน | `light(breathing,violet)` → `say(นิทานสั้น 1 เรื่อง, HAPPY)` → `face TIRED` (จบ) | ~40 วิ |
| D2 | `dance_youtube` | เต้นตามเพลง (YouTube) | `yt(url, [22,23])` + `face SINGING` → `light(marquee,multicolor)` | ตามเพลง |
| D3 | `sing_show` | ร้องเพลง + ประกอบท่าทาง | `say(ร้องเพลงสั้น, SINGING)` → `dance(18)` → `say(ขอบคุณครับ, HAPPY)` | ~25 วิ |
| D4 | `quiz_game` | เล่นเกมทายคำ/ทายสัตว์ | `say(มาเล่นเกมกัน, HAPPY)` → `face DOUBT` (รอตอบ) → `say(ถูกต้องครับ, PROUD)` | ~30 วิ |

### หมวด E — บริการห้องสมุด (Library Service)

| # | id | ชื่อ | steps (ย่อ) | duration |
|---|---|---|---|---|
| E1 | `intro_services` | แนะนำบริการห้องสมุด | `say(บริการ: ยืม-คืน, ห้องศึกษา, eBook, EXPECT)` → `say(ติดต่อเคาน์เตอร์ได้เลย, HAPPY)` | ~25 วิ |
| E2 | `recommend_books` | แนะนำหนังสือ / หมวดหนังสือ | `say(แนะนำหมวดหนังสือใหม่, HAPPY)` → `head(yaw=-15)` → `head(yaw=15)` (กวาดสายตา) | ~20 วิ |
| E3 | `announcement` | แจ้งประกาศ / แจ้งเตือน | `light(blinking,amber)` → `say(ประกาศ..., PROUD)` → `light(breathing,green)` | ~15 วิ |
| E4 | `guide_room` | ชี้ทาง / นำทางไปห้อง | `say(กรุณาตามผมไป, HAPPY)` → `nav(route_to_room)` → `move(x=1.0)` | ตามเส้นทาง |

### หมวด F — โหมดสถานะ (Utility / State)

| # | id | ชื่อ | steps (ย่อ) | duration |
|---|---|---|---|---|
| F1 | `wake_mode` | โหมดตื่น / พลังงานเต็ม | `say(พร้อมทำงานแล้วครับ, HAPPY)` → `head(0,10)` → `light(breathing,green)` → `move(0.3)` | ~8 วิ |
| F2 | `sleep_mode` | โหมดพัก / Sleep | `say(ขอนอนพักสักครู่ครับ, TIRED)` → `head(0,-15)` → `light(off)` | ~8 วิ |
| F3 | `photo_group` | ถ่ายรูปหมู่ | `say(รวมตัวกันถ่ายรูปครับ, HAPPY)` → `turn(0)` → `head(0,10)` → `light(marquee,white)` → `say(3,2,1, ยิ้ม!)` | ~20 วิ |
| F4 | `emergency_all` | หยุดฉุกเฉิน / ยกเลิกทุกอย่าง | `POST /api/v1/robots/{slug}/stop` (ไม่ใช่ interact) | ทันที |

**รวม 24 presets** (เกินโจทย์ขั้นต่ำ 20)

---

## 4. ตัวอย่าง Preset ฉบับเต็ม (JSON พร้อมใช้)

### 4.1 `welcome_library` — กล่าวต้อนรับนำชมสำนักหอสมุด มข. (~30 วิ)

```json
{
  "id": "welcome_library",
  "category": "presentation",
  "title_th": "กล่าวต้อนรับนำชม (สำนักหอสมุด มข.)",
  "icon": "fa-solid fa-door-open",
  "duration_label": "~30 วิ",
  "steps": [
    { "delay_ms": 0, "payload": { "wheel_lights": { "mode": "breathing", "color": "0x00D031", "brightness": 15 } } },
    { "delay_ms": 300, "payload": {
        "text": "สวัสดีครับ ผมบุ๊คกี้ หุ่นยนต์นำชม สำนักหอสมุด มหาวิทยาลัยขอนแก่นครับ วันนี้ผมจะพาทุกท่านชมไฮไลต์ของห้องสมุด ทั้งโซนบริการยืมคืน ฐานข้อมูลออนไลน์ และพื้นที่เรียนรู้ร่วมกัน ใช้เวลาประมาณครึ่งชั่วโมงครับ เชิญทุกท่านตามผมมาเลยครับ",
        "voice_profile": "male_young", "face": "HAPPY" } },
    { "delay_ms": 30000, "payload": {
        "head_sequence": [
          { "yaw": 0, "pitch": -15, "speed": 2, "delay_ms": 800 },
          { "yaw": 0, "pitch": 10, "speed": 2, "delay_ms": 0 } ] } },
    { "delay_ms": 1500, "payload": {
        "motion": { "x": 0, "y": 0, "theta": 180, "speed": 2 },
        "face": "PROUD" } }
  ]
}
```

### 4.2 `follow_mode` — โหมดติดตาม

```json
{
  "id": "follow_mode",
  "category": "motion",
  "title_th": "โหมดติดตาม (Follow Me)",
  "icon": "fa-solid fa-person-walking",
  "duration_label": "ต่อเนื่อง",
  "steps": [
    { "delay_ms": 0,   "payload": { "vision": { "action": "detect_face", "interval_ms": 1000, "debug_preview": false } } },
    { "delay_ms": 800, "payload": { "behavior": { "action": "follow_face", "enabled": true, "track": true } } },
    { "delay_ms": 500, "payload": { "text": "ตามผมมาเลยครับ", "voice_profile": "male_young", "face": "HAPPY" } }
  ]
}
```

### 4.3 `sleep_mode` — โหมดพัก

```json
{
  "id": "sleep_mode",
  "category": "utility",
  "title_th": "โหมดพัก / Sleep",
  "icon": "fa-solid fa-moon",
  "duration_label": "~8 วิ",
  "steps": [
    { "delay_ms": 0,    "payload": { "text": "ขอนอนพักสักครู่ครับ", "voice_profile": "male_young", "face": "TIRED" } },
    { "delay_ms": 6000, "payload": { "head": { "yaw": 0, "pitch": -15, "speed": 2 } } },
    { "delay_ms": 1500, "payload": { "wheel_lights": { "mode": "off", "color": "0x000000", "brightness": 0 } } }
  ]
}
```

---

## 5. Playback Engine (Flow ฝั่ง client)

```
playPreset(preset)
 ├─ validate selectedRobot → else error
 ├─ for each step:
 │    ├─ await sleep(step.delay_ms)
 │    ├─ POST /api/v1/robot/interact  { ...step.payload, robot_slug, source: 'liff_present' }
 │    └─ if response !ok → break + show error (optional: auto-stop)
 ├─ on finish → show "จบ preset"
 └─ STOP button (anytime) → POST /api/v1/robots/{slug}/stop + abort loop
```

Key points:
- ใช้ `AbortController` / flag เพื่อยกเลิกลำดับตอนกด STOP
- แสดง `step n/N` + ชื่อ preset + progress bar
- ล็อกปุ่มอื่นระหว่างเล่น (กันคำสั่งชนกัน)

---

## 6. แผนการ Implement (Phases)

| Phase | งาน | ไฟล์ |
|---|---|---|
| 1 | สร้าง `presets.js` (24 presets) + `index.html` (player UI) | `services/liff-app/present/presets.js`, `services/liff-app/present/index.html` |
| 2 | เพิ่มปุ่มลิงก์ "โหมดนำเสนอ" ใน navbar | `/liff/index.html`, `/liff/control/index.html`, `/liff/command/index.html` |
| 3 | Playback engine + STOP + progress | ใน `present/index.html` |
| 4 | ตัดสิน persona (Booky boy vs Zenbo girl) แล้ว normalize `voice_profile` ทั้ง 24 | presets.js |
| 5 | (optional) ย้าย presets ขึ้น server → `GET /api/v1/presets` เพื่อแก้ไขได้ไม่ต้อง redeploy | `core-api/main.py` |
| 6 | (หลัง bridge ใหม่) เปลี่ยน fixed `delay_ms` → event-driven "พูดจบ" ack | ทุก preset |

---

## 7. จุดที่ต้องตัดสินใจ / ความเสี่ยง

1. **Persona**: ใช้ `male_young` (บุ๊คกี้ หนุ่มน้อย) ตลอดทั้ง 24 presets หรือเก็บ `female_young` (เซนโบ)? → แนะนำ `male_young` ให้ตรงกับ connect handshake ("บุ๊คกี้พร้อมครับ")
2. **Timing ไร้ ack**: fixed `delay_ms` จะเพี้ยนถ้า TTS เร็ว/ช้ากว่า ~5 ตัวอักษร/วิ → แก้เมื่อ bridge ใหม่ส่ง "พูดจบ" ack
3. **follow/vision ต่อเนื่อง**: B1, B4, C1 เปิด behavior/vision ค้าง → ต้องมี preset "ปิดติดตาม/ปิดวิชัน" หรือปุ่ม STOP ฝั่งคู่ เพื่อหยุด (แนะนำเพิ่ม preset `follow_off` คู่กับ `follow_mode`)
4. **navigation**: `display_url` ต้องขึ้นต้น `http://10.101.118.149:8032/` (server validate) → presets ที่ใช้ `nav()` ต้องดึง route จาก `/api/v1/navigation/route` ก่อน ไม่ hardcode URL
5. **dance action_id**: ใช้ได้เฉพาะ {2,3,5,11,18,22,23,44} — อย่าใช้ id นอกชุดนี้
6. **multi-robot**: player ใช้ `robot_slug` เดียวกับ control page (`sessionStorage['zenbo-control-robot']`)
