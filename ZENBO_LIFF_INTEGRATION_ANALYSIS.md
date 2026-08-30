# LIFF Integration Analysis — Zenbo Control via LINE

วิเคราะห์การเชื่อม LIFF (LINE Front-end Framework) เข้ากับระบบ Zenbo ตาม reference จาก
https://linedevth.line.me/th/liff

---

## 1. สรุป LIFF คืออะไร (จาก reference)

LIFF คือ WebView ที่รันเว็บแอปภายใน LINE โดยตรง เพื่อยกระดับประสบการณ์ที่ Chatbot ทำได้จำกัด เช่น
ฟอร์มซับซ้อน, e-Commerce, แสดงผลจำนวนมาก

ความสามารถหลัก:

| Feature | รายละเอียด |
|---|---|
| Rich UX/UI | รันเว็บแอปเต็มรูปแบบ (e-Commerce, จองตั๋ว, เกม) |
| Access LINE User Profile | `userId`, `displayName`, `pictureUrl`, `statusMessage`, `email` |
| QR Code Reader | `scanCodeV2()` เปิดกล้องสแกน QR |
| ส่งข้อความกลับห้องแชท | `sendMessages()` interact กลับเข้าแชท |
| Share Target Picker | แชร์ข้อความไปเพื่อน/กลุ่ม |
| LINE Login | `isLoggedIn()` / `login()` / `getDecodedIDToken()` |

ข้อดีหลัก (Why LIFF):
1. ยกระดับ Chatbot ใน LINE Official Account
2. นำเว็บเดิมมาเป็น LIFF app ได้ง่าย (แค่เพิ่ม SDK) — time-to-market ต่ำ
3. ผู้ใช้ไม่ต้องโหลดแอปเพิ่ม เข้าลิงก์ได้เลย

---

## 2. สถานะปัจจุบัน — "liff-app" แค่ชื่อ ยังไม่ใช่ LIFF จริง

ตรวจ `services/liff-app/` (5 ไฟล์) พบว่า **ไม่มีการใช้ LIFF SDK เลย**:

| ไฟล์ | ขนาด | หมายเหตุ |
|---|---|---|
| `index.html` | 717 lines | controller หลัก |
| `control/index.html` | 368 lines | จอยสติ๊ก |
| `command/index.html` | 223 lines | สั่งด้วยคำพูด |
| `history/index.html` | 115 lines | ประวัติคำสั่ง |
| `navigation/index.html` | 8 lines | นำทาง Booky (minified) |

สิ่งที่ขาด (ตรวจด้วย grep `liff|init|getProfile|sendMessages|scanCode|...`):

- ไม่มี `liff.init()`, ไม่มี `liff.getProfile()`, ไม่มี `liff.sendMessages()`, ไม่มี `liff.closeWindow()`
- เป็น static HTML ธรรมดาที่ `fetch()` ตรงไป core-api (`API_BASE = window.location.origin`)
- `source` ที่ส่งไป core-api เป็น string hardcode (`liff_control`, `liff_command`, `liff_joystick`) — ไม่ใช่ LINE userId จริง
- Speech-to-text ใช้ **browser Web Speech API** (`window.SpeechRecognition` + `lang='th-TH'`) ไม่ใช่ LINE
- ไม่มีหน้าไหนเรียก `/api/v1/voice-profiles` — hardcode `<option>` เอง (dead code)

---

## 3. LIFF SDK features → จุดเชื่อมกับ Zenbo

| LIFF feature | ใช้กับอะไรใน Zenbo |
|---|---|
| `liff.init({ liffId })` | ตั้ง LIFF ID แยกต่อหน้า (4 หน้า = 4 LIFF app หรือ 1 app + query param) |
| `liff.isLoggedIn()` / `liff.login()` | บังคับ LINE login ก่อนใช้ controller — กันคนไม่ได้รับเชิญสั่งหุ่น |
| `liff.getProfile()` | แก้ปัญหา identity: ส่ง `userId` + `displayName` ไป core-api แทน `source='liff_control'` → ผูกสิทธิ์ robot ต่อผู้ใช้ |
| `liff.getDecodedIDToken()` | ยืนยันตัวตนฝั่ง server (ไม่เชื่อ client เปล่า) — core-api verify JWT |
| `liff.sendMessages()` | หลังสั่งสำเร็จ → ส่งผลลัพธ์/ลิงก์กลับห้องแชท LINE |
| `liff.scanCodeV2()` | **QR robot pairing** — สแกน QR บนตัว Zenbo เพื่อ bind `userId ↔ robot_slug` (แทนการเลือกจาก dropdown) |
| `liff.closeWindow()` | ปิดหน้า LIFF หลังคำสั่งเสร็จ |
| `liff.getContext()` | รู้ว่ามาจากห้อง/กลุ่ม LINE ไหน (utou/room/group) |
| `liff.isInClient()` | fallback: เปิดนอก LINE ใน browser ธรรมดาได้ (test mode) |

---

## 4. การเปลี่ยนแปลงที่ต้องทำ (เรียงตาม impact)

### ฝั่ง client (LIFF 4 หน้า)
1. เพิ่ม `<script src="https://static.line-scdn.net/liff/edge/2/sdk.js">` + `liff.init({ liffId: '...' })` ในทุกหน้า
2. แทนที่ `source: 'liff_control'` → `source: 'line', user_id: profile.userId, display_name: profile.displayName`
3. เพิ่ม robot pairing ผ่าน `scanCodeV2()` (สแกน QR = slug) → เก็บ map ใน core-api

### ฝั่ง server (core-api)
4. รับ `user_id` ใน `/api/v1/robot/interact` → เก็บลง SQLite command-history (ตอนนี้เก็บแค่ `source` string)
5. สร้าง table `user_robot_binding(user_id, robot_slug, permissions)` → `USER_ROBOT_MAP` ใน n8n workflow อ่านจากตรงนี้ (แทน hardcode `{}`)
6. เปิด endpoint verify LIFF ID Token (optional ถ้าไม่ต้องการความปลอดภัยสูง)

### ฝั่ง n8n
7. `zenbo_line_chat_orchestrator.json` + `voice` เปลี่ยน `USER_ROBOT_MAP` ที่ hardcode → query core-api binding

---

## 5. จุดที่ LIFF ช่วยแก้ปัญหาค้างเดิมได้ตรงจุด

| ปัญหาที่ flagged ไว้ก่อนหน้า | LIFF แก้อย่างไร |
|---|---|
| "ไม่มี LINE identity binding — SQLite เก็บแค่ชื่อหน้า" | `liff.getProfile()` → `user_id` จริง |
| "LINE user → robot_slug ต้อง hardcode `{}`" | `scanCodeV2()` QR pairing → binding แบบ runtime |
| "index.html emergencyStop broadcast หยุดทุกเครื่อง" | ตรวจ `permission` จาก binding ก่อนอนุญาต broadcast |
| "ไม่มีใคร validate ว่าใครกด" | `liff.isLoggedIn()` + ID Token verify ฝั่ง server |

---

## 6. ข้อควรระวัง

- **LIFF SDK ต้อง HTTPS** — ถ้า `core-api` serve LIFF ที่ `http://localhost` จะ init ไม่ได้ ต้อง tunnel (ngrok) หรือขึ้น `https://libn.kku.ac.th`
- **LIFF endpoint URL** ต้องตั้งใน LINE Developers Console ให้ตรงกับ path จริง (`/liff/`, `/liff/control/` …) — ปัจจุบันเป็น static path แยกหน้า
- **Web Speech API ใน LIFF** อาจมีข้อจำกัดใน WebView LINE (ไมโครโฟน) — ควรย้าย STT ไปฝั่ง LINE voice message (n8n voice orchestrator) แทน browser API
- `liff.sendMessages()` ต้องใช้ `flex`/`text` template ตาม LINE Messaging API format

---

## 7. สรุป

ระบบตอนนี้เป็น **web remote controller ธรรมดา** ที่ถูกวางไว้ใน path `/liff/` เท่านั้น ยังไม่ได้ใช้ความสามารถ
LIFF สักข้อเดียว

จุดเชื่อมที่มีค่าสูงสุด:
1. `getProfile` — identity binding (แก้ช่องโหว่เรื่องสิทธิ์)
2. `scanCodeV2` — QR robot pairing (แก้ `USER_ROBOT_MAP` ที่ค้าง hardcode อยู่)
