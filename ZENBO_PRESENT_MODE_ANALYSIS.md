# วิเคราะห์และออกแบบ Zenbo Present Mode

วันที่: 30 สิงหาคม 2026  
สถานะ: **Phase 1 implemented — ต้องผ่านการยืนยันบน Zenbo จริงก่อนเปิดใช้งานการเคลื่อนที่อัตโนมัติ**

## เป้าหมาย

เพิ่ม route ใหม่ `/liff/present/` สำหรับเลือก **presentation preset** ด้วยการแตะ ไม่ต้องเขียน JSON เอง โดยทุก preset ต้องเลือกหุ่นยนต์ก่อน, แสดงสิ่งที่จะเกิดขึ้น, กดยืนยัน, และเห็นสถานะจาก Zenbo ระหว่างทำงาน

กลุ่มใช้งานหลักคือสำนักหอสมุด มหาวิทยาลัยขอนแก่น: กล่าวต้อนรับ, นำชม, กิจกรรมกรรมการ, การสื่อสาร, และกิจกรรมเด็ก/ความบันเทิง

## หลักฐานและข้อจำกัดปัจจุบัน

| ความสามารถ | สถานะทางซอฟต์แวร์ | ข้อจำกัดก่อนใช้เป็น preset |
|---|---|---|
| Thai TTS ผ่าน `:8025` | มีใน APK v1.7.2 | ต้องรอสถานะ TTS/จบเสียงก่อน step ถัดไป |
| สีหน้า, คอ, ไฟล้อ, canned action | มี API และ MQTT payload | ความหมาย/ระยะเวลาของ action ID ต้องทดสอบกับเครื่องจริง |
| จอยสติ๊ก/หยุดฉุกเฉิน | มี `/liff/control/` | ห้ามแทนด้วยคำสั่งเดินอัตโนมัติบนพื้นที่ไม่ตรวจ obstacle |
| แผนที่ `:8032` | มี `/liff/navigation/` | ปัจจุบันเปิดแผนที่และพูดเท่านั้น **ไม่สั่งเดินตามแผนที่** |
| YouTube + เต้น | APK v1.7.2 มี player ในตัว | ต้องทดสอบเครือข่าย YouTube/เสียงบน Zenbo; ไม่ถือว่าเล่นสำเร็จจนมี client status |
| vision/behavior | มี command model | โหมด follow/ตรวจคนยังไม่มีหลักฐานการทำงานทางกายภาพ จึงต้องเป็น gated beta |
| marker ฐาน | ยังไม่มีระบบ marker persistence | ต้องนิยามเป็น virtual checkpoint ก่อน ไม่ควรอ้างว่าเป็นการระบุตำแหน่งจริง |

### ข้อสรุปการออกแบบ

ไม่ควรทำเป็นปุ่ม 20 ปุ่มที่ยิง `interact` หลายครั้งจาก browser เพราะคำสั่งปัจจุบันทำงานแบบ asynchronous และอาจทับกันได้ เช่น เพลงเริ่มช้าแต่ action เริ่มแล้ว หรือ TTS สองประโยคซ้อนกัน

จึงควรเพิ่ม **Presentation Runner ใน APK** เพื่อรับแผนเดียว, ทำทีละ step, รอ RobotAPI/TTS callback, ส่ง `RUNNING / STEP_DONE / FAILED / STOPPED` กลับ MQTT และยกเลิกได้ด้วยปุ่ม STOP เดิม

## Route และ UX ที่เสนอ

### Route

- `/liff/present/` — แกลเลอรี preset แบบกราฟิก
- `/liff/present/?preset=library-welcome` — เปิด card ที่เลือกพร้อม preview
- `/liff/present/history/` — filter ประวัติ command เฉพาะ `source=liff_present` (ใช้ history เดิมเพิ่ม filter ได้)

หน้าแรกใช้ grid card 2 คอลัมน์บนมือถือ: ไอคอน, ชื่อสั้น, ระยะเวลา, ป้ายระดับความพร้อม และปุ่ม “ดูตัวอย่าง” ไม่ต้องโชว์ JSON เป็นค่าเริ่มต้น

เมื่อเลือก card ให้แสดง:

1. เลือก Zenbo ที่ออนไลน์
2. Preview ข้อความ/เวลาประมาณ/ขั้นตอน
3. toggle เฉพาะที่อนุญาต เช่น ชื่อผู้ต้อนรับ, ภาษา, เสียง, จุดเริ่ม–ปลายทาง
4. แถบความปลอดภัยและปุ่ม `ยืนยันเริ่ม` สีเขียว
5. หน้าสถานะสด พร้อม `หยุดทันที` สีแดง และปุ่มกลับจอยสติ๊ก

## Catalog: preset เริ่มต้น 22 รายการ

สัญลักษณ์: **A** = สร้างได้จากความสามารถปัจจุบัน แต่ยังต้องทดสอบหุ่นจริง; **B** = ต้องทำ Presentation Runner/ตรวจ callback ก่อน; **G** = gated beta ต้องมีการสอบเทียบหรือบริการเพิ่ม

| ID | Preset | เนื้อหาหลัก | ระดับ |
|---|---|---|---|
| `library-welcome-30` | ยินดีต้อนรับสำนักหอสมุด 30 วินาที | TTS ไทย + HAPPY + ไฟเขียวหายใจ + หันมองผู้ฟัง | B |
| `judge-greeting` | กล่าวทักทายกรรมการ | คำนับ/สีหน้าภูมิใจ + กล่าวต้อนรับแบบปรับชื่อได้ | B |
| `photo-invitation` | เชิญถ่ายภาพ | ขออนุญาตถ่ายรูป, นับถอยหลัง, ยิ้ม, ไฟสีชมพู | B |
| `photo-pose` | โพสท่าถ่ายภาพ | ยิ้ม/หันหน้า/ท่านิ่ง 5 วินาที; **ไม่ถ่ายภาพเอง** | A |
| `self-introduction` | แนะนำตัว Booky | ชื่อ, หน้าที่, ความสามารถ, ปรับชื่อหุ่นได้ | B |
| `library-orientation` | แนะนำบริการห้องสมุด | กล่าวถึงยืมคืน/ค้นหนังสือ/พื้นที่อ่าน พร้อมจอ map link | B |
| `route-guide` | พาไปจุดบริการ | เรียก route `:8032`, เปิดแผนที่และพูดทีละจุด | B |
| `route-announcement` | ประกาศเส้นทางโดยไม่เคลื่อนที่ | พูดเส้นทาง/ระยะเวลา โดยหุ่นอยู่กับที่ | A |
| `new-member-welcome` | ต้อนรับสมาชิกใหม่ | กล่าวต้อนรับแบบสั้น + ชวนสอบถามบริการ | B |
| `ask-me` | โหมดสื่อสาร/รับคำถาม | หน้า EXPECTING, ฟังเป็นข้อความจาก LIFF, ส่งคำตอบให้ TTS | G |
| `feedback-invitation` | เชิญให้ข้อเสนอแนะ | พูดเชิญสแกน QR/ส่ง feedback และขอบคุณ | B |
| `story-time` | เล่านิทาน | เลือกนิทาน 1–3 นาที, หน้า/ไฟเปลี่ยนตามบท, หยุดได้ | B |
| `quiz-host` | พิธีกรเกมตอบคำถาม | อ่านคำถาม, รอ operator กดเฉลย, ฉลองคำตอบ | B |
| `event-opening` | เปิดงาน | กล่าวเปิดงาน, นับถอยหลัง, ไฟ celebration, ท่าทักทาย | B |
| `celebration` | แสดงความยินดี | TTS สั้น + ไฟ marquee + canned action ที่สอบเทียบแล้ว | G |
| `music-dance` | เพลงและเต้น | Player ภายใน + action loop + ระยะเวลาชัดเจน | G |
| `children-greeting` | ทักทายเด็ก | เสียงเด็กชาย/หญิง, ภาษาง่าย, สีหน้าสดใส | B |
| `accessibility-help` | ช่วยเหลือผู้ใช้ | พูดช้า/ชัด, แสดงทางเลือกบนจอ, เรียกเจ้าหน้าที่ผ่าน LIFF | B |
| `staff-call` | เรียกเจ้าหน้าที่ | แจ้งข้อความ/พื้นที่ให้ operator; ไม่อ้างว่าโทรหรือส่ง LINE หากไม่เชื่อมบริการ | B |
| `checkpoint-mark` | mark ฐานกิจกรรม | บันทึก **virtual checkpoint** ใน history พร้อมชื่อฐาน/เวลา/ผู้ดูแล | B |
| `checkpoint-arrival` | ถึงฐานกิจกรรม | เลือก checkpoint, พูดว่าเข้าถึงฐานแล้ว, ไฟตามสีฐาน | B |
| `standby` | โหมดพักรอ | หน้านิ่ง, ไฟหายใจ, ลดเสียง/ยกเลิกคิวที่ไม่จำเป็น | A |

## ตัวอย่าง preset สำคัญ

### `library-welcome-30`

ข้อความเริ่มต้น: “สวัสดีครับ ผมบุ๊คกี้ ยินดีต้อนรับทุกท่านสู่สำนักหอสมุด มหาวิทยาลัยขอนแก่น ...” ความยาวไม่เกิน 30 วินาที

ลำดับที่เสนอ: `HAPPY` + ไฟเขียวแบบ breath → กล่าว 20–25 วินาที → หันมองซ้าย/ขวาแบบปลอดภัย → กล่าวเชิญใช้บริการ → `DEFAULT_STILL`

### `judge-greeting`

รับตัวแปร `judge_title` และ `event_name`; ไม่มีการเดินฐาน. ใช้ canned action **เฉพาะหลังยืนยัน action catalog บน Zenbo เครื่องจริง** มิฉะนั้นใช้การหันศีรษะและสีหน้าแทน

### `route-guide`

รับ `from_location` และ `to`; Core เรียก navigation service แล้วส่ง `display_url`, `speech_text`, `step_speeches` ให้ runner. Runner เปิดแผนที่และพูดคำแนะนำ แต่ไม่ใช้ `moveBody` อัตโนมัติ. Operator ใช้จอยสติ๊กเมื่อต้องเคลื่อนที่จริง

### `music-dance`

รับ YouTube HTTPS URL, action IDs ที่สอบเทียบแล้ว, `duration_seconds` (บังคับ 10–600 วินาที). ห้ามใช้ `null` duration หรือ playlist/radio ใน mode นี้. ถ้า player ส่ง `ERROR` ต้องหยุด dance loop และรายงานบน LIFF

## Contract ที่ควรเพิ่ม

Core เพิ่ม field `presentation` ใน `InteractCommand` หรือ endpoint `POST /api/v1/presentations/start` ที่ validate preset จาก server-side catalog เท่านั้น:

```json
{
  "robot_slug": "10-153-54-75",
  "source": "liff_present",
  "presentation": {
    "id": "library-welcome-30",
    "variables": {"visitor_group": "คณะกรรมการ"},
    "run_id": "uuid-generated-by-core"
  }
}
```

Core แปลง preset เป็น `steps` ที่เซ็น/validate แล้ว ไม่เปิดให้ browser ส่ง arbitrary `motion` หรือ action ID. APK รับ `run_id`, execute ทีละ step, publish:

```text
zenbo/<robot>/status/presentation
{ "run_id": "...", "state": "RUNNING|STEP_DONE|FAILED|STOPPED|COMPLETED", "step": 2, "message": "..." }
```

## Safety และความจริงที่ต้องสื่อใน UI

- ทุก preset ที่มี motion ต้องมี operator-confirmation, แสดงพื้นที่ปลอดภัย และ STOP ตลอดเวลา
- Route/Map เป็น “การนำทางบนจอและเสียง” จนกว่าจะมี obstacle/drop-sensor gating และการยืนยันเส้นทางจริง
- Follow, camera/photo, marker จริง และ YouTube sound เป็น gated features: card ต้องมีป้าย “ทดลอง” จนผ่าน acceptance test
- ห้ามประกาศ `COMPLETED` จาก HTTP 200/MQTT publish; ต้องรอ client status จาก APK
- ตัวอักษร/เสียงต้องตัดข้อความที่ยาวเกินกำหนด; story mode แบ่ง chunk เพื่อให้ STOP ตอบสนอง

## แผนพัฒนาเป็นลำดับ

1. สร้าง server-side preset catalog 8 รายการระดับ A/B ที่ไม่เคลื่อนฐาน
2. เพิ่ม Presentation Runner ใน APK และ MQTT status ต่อ run/step
3. สร้าง `/liff/present/` พร้อม target picker, preview, confirm, stop, status และ history
4. ทดสอบ TTS/face/light/action catalog บน Zenbo จริงทีละ preset
5. เปิด `route-guide`, `music-dance`, และ `celebration` หลัง player/action telemetry ผ่าน
6. เปิด follow, marker, photo capture หรือ autonomous navigation เฉพาะเมื่อมี implementation และ safety proof เพิ่ม

## ผลการพัฒนา Phase 1

- เพิ่ม `/liff/present/` พร้อม gallery 22 preset, category picker, Zenbo picker, preview ก่อนยืนยัน, และปุ่ม STOP
- เพิ่ม Core API `GET /api/v1/presentations`, `POST /api/v1/presentations/preview`, และ `POST /api/v1/presentations/start`
- catalog และข้อความ template อยู่ฝั่ง Core; browser ไม่สามารถส่ง action/motion เพิ่มเติมผ่าน preset ได้
- เปิดใช้เฉพาะ 15 preset ที่เป็น TTS/face/light/map display และไม่มีการเคลื่อนฐานอัตโนมัติ
- ล็อก 7 preset ที่ต้องมี Presentation Runner, checkpoint persistence, หรือผลทดสอบ hardware/YouTube ก่อน
- history ของคำสั่งที่ยืนยันแล้วใช้ `source=liff_present`; สถานะที่หน้า UI ระบุเฉพาะ gateway acceptance จนกว่า runner/callback จะเสร็จ

## เกณฑ์รับมอบ

- การกด preset ที่ไม่มี movement ต้องได้ `RECEIVED → RUNNING → COMPLETED` บน LIFF และได้ยินเสียงจริง
- STOP ระหว่าง story/TTS/dance หยุดเสียงและคิวภายในเวลาที่ยอมรับได้
- preset ที่เป็น gated แสดงเหตุผลและไม่ส่งคำสั่งเสี่ยง
- คำสั่งทุกครั้งบันทึก history ด้วย `run_id`, preset ID, robot, operator time และผลจาก client
- การทดสอบ physical แยกรายงานจาก build/API/broker อย่างชัดเจน
