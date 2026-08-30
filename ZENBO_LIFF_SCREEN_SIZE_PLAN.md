# Zenbo LIFF — แผนพัฒนา (Screen Size & Registration)

> อ้างอิง: https://developers.line.biz/en/docs/liff/overview/#screen-size
> และ https://developers.line.biz/en/docs/liff/registering-liff-apps/

แผนนี้วิเคราะห์เรื่อง **ขนาดจอ LIFF (3 ขนาด)** และ **การลงทะเบียน LIFF app** เพื่อวางแผนพัฒนา
หน้า Zenbo controller ทั้ง 5-6 หน้าให้แสดงผลถูกต้องบน LIFF browser (WKWebView / Android WebView)

---

## 1. สรุปขนาดจอ LIFF (3 แบบ)

| Size | ความสูง (approx) | ลักษณะ | เหมาะกับ |
|---|---|---|---|
| `Compact` | ~50% | bottom sheet ครึ่งจอ | แบบฟอร์มสั้น, ยืนยัน, แชทด่วน |
| `Tall` | ~80% | เกือบเต็มจอ | ฟอร์มยาว, รายการ |
| `Full` | ~100% | เต็มจอ + แสดง action button ใน header | app ที่ต้องการพื้นที่เยอะ |

ข้อเท็จจริงสำคัญจาก doc:

1. **ตั้ง Size ตอนลงทะเบียน LIFF app** ใน LINE Developers Console (LIFF tab → Add → Size)
2. **`Full` เท่านั้น** ที่แสดง **action button** (ปุ่ม …) ใน header โดย default
3. **Module mode** (ซ่อน action button) ใช้ได้**เฉพาะเมื่อ Size = `Full`**
4. **Multi-tab view / Recently used services** (ฟีเจอร์ resume session) ใช้ได้เฉพาะเมื่อ
   Size = `Full` + module mode **off**
5. ตั้งได้ไม่เกิน **30 LIFF apps ต่อ channel**

---

## 2. วิเคราะห์หน้าของเรากับ Size ที่ควรใช้

เรามี 5 หน้า + 1 หน้าในอนาคต (`present/` จากแผน preset):

| หน้า | ปัจจุบัน (path) | เนื้อหา | Size แนะนำ | เหตุผล |
|---|---|---|---|---|
| หน้าหลัก | `/liff/index.html` | connect + motion D-pad + head slider + face/lights/vision + TTS | **Full** | เนื้อหาเยอะ มี D-pad + slider + ปุ่มละเอียด ต้องเต็มจอ |
| จอยสติ๊ก | `/liff/control/index.html` | 2 จอย (base/head) + natural command | **Full** | จอยสติ๊ก touch gesture ต้องพื้นที่ + `pagehide` handler กันคำสั่งค้าง |
| สั่งด้วยคำพูด | `/liff/command/index.html` | textarea + compile preview | **Tall** | ฟอร์มเดียว ไม่ต้องเต็มจอ แต่ preview JSON ยาว ต้องการ ~80% |
| ประวัติ | `/liff/history/index.html` | รายการ command history | **Tall** | รายการ scroll ได้ 80% พอ |
| นำทาง | `/liff/navigation/index.html` | เลือกจุด + preview เส้นทาง | **Tall** | ฟอร์ม + result 80% พอ |
| โหมดนำเสนอ *(ในอนาคต)* | `/liff/present/index.html` | กริด preset 24 การ์ด + progress + STOP | **Full** | ปุ่ม STOP ต้องใหญ่ + กริดการ์ดเยอะ + ใช้ระหว่างนำเสนอจริง |

> **สรุป**: หน้า controller หลัก (index, control, present) ใช้ **Full** — หน้า form/list (command,
> history, navigation) ใช้ **Tall**

### 2.1 ประเด็น action button (เฉพาะ Full)

- `Full` แสดงปุ่ม "…" ใน header → ผู้ใช้กดได้ dropdown (All tabs / Refresh / Minimize / Share / Permission)
- การ Refresh จาก dropdown = reload → **state หน้า เช่น selectedRobot ถูก reset** (ยกเว้น resume ภายใน 12 ชม.)
- แนะนำ: เปิด **Module mode** เพื่อซ่อน action button ในหน้า controller จริง (index/control/present)
  → กันผู้ใช้เผลอกด Refresh/Share ระหว่างควบคุมหุ่น
- ข้อแลก: เปิด Module mode แล้วจะ**ไม่**เข้า Multi-tab/recently-used (ยอมรับได้ เพราะเราไม่อยากให้ resume session กลางคัน)

### 2.2 ข้อควรระวัง `liff.sendMessages()` หลัง reload

- Doc ระบุชัด: ใช้ `sendMessages()` ใน LIFF app ที่ **reload จาก recently-used services** จะ error
- → workflow "สั่งหุ่นเสร็จแล้วส่ง Flex กลับแชท" ต้องเปิดจาก **LIFF URL ในห้องแชท** เสมอ ไม่ใช่ resume จาก recent
- → ในโค้ดเราใช้ `sendMessages()` แบบ best-effort (catch แล้ว ignore) แล้ว ถูกต้อง

---

## 3. Scopes ที่ต้องเปิด (ตอนลงทะเบียน)

| Scope | ใช้กับ API ไหน | จำเป็น? |
|---|---|---|
| `profile` | `liff.getProfile()` → `userId`/`displayName` (identity binding) | **ต้อง** |
| `openid` | `liff.getIDToken()` / `getDecodedIDToken()` (verify ฝั่ง server) | แนะนำ (ความปลอดภัย) |
| `email` | `getIDToken()` แบบมี email | ไม่จำเป็น (skip) |
| `chat_message.write` | `liff.sendMessages()` (ส่งผลลัพธ์กลับแชท) | แนะนำ |

### 3.1 Options ที่ต้องเปิด

| Option | เมื่อไร | ใช้กับ Zenbo |
|---|---|---|
| **Scan QR** | ใช้ `liff.scanCodeV2()` | **ต้อง** — ใช้ QR pairing ผูก user↔robot (แทน dropdown) |
| **Module mode** | เฉพาะ Size = Full | เปิดที่ index/control/present (ซ่อน action button) |

---

## 4. กลยุทธ์ลงทะเบียน: 1 LIFF app ต่อหน้า vs 1 app หลายหน้า

### 4.1 ตัวเลือก

**A. หลาย LIFF app (1 app/หน้า)** — ตรงกับโครงสร้าง static path ปัจจุบัน
- 6 app: `index`, `control`, `command`, `history`, `navigation`, `present`
- Endpoint URL ชี้ path จริง เช่น `https://domain/liff/control/`
- ข้อดี: แยก liffId, แยก Scope/Size, ไม่ต้อง refactor
- ข้อเสีย: ต้อง config liffId หลายตัว

**B. 1 LIFF app + query param** — Endpoint URL = `https://domain/liff/`
- เปิดด้วย `?page=control` เลือกหน้าใน index
- ข้อดี: 1 liffId, 1 scope set
- ข้อเสีย: ต้อง refactor routing + Size เดียวทั้งแอป (จะใช้ Full/Tall ผสมไม่ได้)

### 4.2 ข้อแนะนำ

เลือก **A (หลาย app)** เพราะ:
1. แต่ละหน้ามี Size/Module mode ต่างกัน (Full สำหรับ controller, Tall สำหรับ form)
2. ไม่ต้อง refactor โครงสร้าง static ที่ทำงานอยู่แล้ว
3. รองรับหน้า `present/` ในอนาคตได้ทันที

### 4.3 วิธี map liffId → หน้า (ปรับ `liff-config.js`)

ปัจจุบัน `liff-config.js` มี `liffId` ตัวเดียว → ต้องเปลี่ยนเป็น **map ตาม pathname**:

```js
// liff-config.js (แผน)
window.ZENBO_LIFF_CONFIG = {
  liffIds: {
    "/liff/":            "1234567890-AbcdEfgh", // index
    "/liff/control/":    "1234567890-IjklMnop", // control
    "/liff/command/":    "1234567890-QrstUvwx", // command
    "/liff/history/":    "1234567890-YzabCdef", // history
    "/liff/navigation/": "1234567890-GhijKlmn", // navigation
    "/liff/present/":    "1234567890-OpqrStuv", // present (อนาคต)
  },
  get liffId() { /* match pathname */ }
};
```

และ `liff.js` อ่าน `config.liffId` ที่ resolve แล้ว (ตอนนี้โค้ดรองรับแล้ว แค่แก้ config)

---

## 5. ผลกระทบต่อโค้ดปัจจุบัน (ที่เพิ่ง implement)

| จุด | สถานะ | ต้องปรับเพิ่ม |
|---|---|---|
| `liff-config.js` (liffId ตัวเดียว) | ทำแล้ว | เปลี่ยนเป็น map pathname → หลาย liffId |
| `liff.js` (init + getProfile + identity) | ทำแล้ว | ไม่ต้องแก้ (อ่าน `config.liffId`) |
| viewport meta | ทำแล้วบางหน้า | ตรวจทุกหน้าให้ครบ (control มีแล้ว, command/history มี, navigation มี) |
| safe-area / header offset | ยังไม่ทำ | **ใหม่** — หน้า `Full` ต้องเว้นช่อง header ของ LINE |
| กัน Refresh reset state | ยังไม่ทำ | **ใหม่** — เปิด Module mode (console) + เก็บ selectedRobot ใน `sessionStorage` (control ทำแล้ว) |
| `sendMessages` best-effort | ทำแล้ว (liff.js catch) | ดีแล้ว |
| HTTPS + Endpoint URL | ยังไม่ทำ | ตั้งใน console (นอกโค้ด) |

---

## 6. ประเด็น CSS/UX ที่ต้องวางแผน (Full-size + WebView)

### 6.1 Viewport & safe area
- ทุกหน้ามี `<meta name="viewport" content="width=device-width, initial-scale=1.0">` → OK
- หน้า `Full` ควรเพิ่ม `viewport-fit=cover` + `env(safe-area-inset-*)` สำหรับ notch iPhone
- กัน footer ถูก header ของ LINE ทับ → ใช้ `padding-bottom: env(safe-area-inset-bottom)`

### 6.2 กัน UI ถูก zoom / select
- `index.html` มี `user-scalable=no` + `-webkit-user-select:none` แล้ว
- `command`/`history` ยังไม่มี → textarea ต้องให้ select ได้ (เหมือน index ใช้ `.speech-input`)
- `control` มี `user-scalable=no` + `touch-action:none` บน joystick แล้ว

### 6.3 Touch (joystick ใช้ pointer events)
- `control/index.html` ใช้ `pointerdown/move/up` + `setPointerCapture` → ใช้ได้บน WKWebView/Android WebView
- ต้องกัน **pagehide** (สลับแอป) → ส่ง STOP (control ทำแล้ว, index ยังไม่มี pagehide handler เต็มรูปแบบ)

### 6.4 Cache (สำคัญมาก)
- Doc: **ลบ cache ใน LIFF browser ไม่ได้** ต้องคุมด้วย HTTP header
- → core-api ต้องส่ง `Cache-Control: no-store` (หรือ `no-cache`) ที่ static LIFF files
- ปัจจุบัน `StaticFiles` ของ FastAPI ไม่ได้ตั้ง cache header → **ต้องเพิ่ม middleware/custom StaticFiles**
- มิฉะนั้นแก้ HTML/JS แล้วผู้ใช้ใน LINE ยังเห็นเวอร์ชันเก่า

---

## 7. Phases การพัฒนา

| Phase | งาน | ไฟล์/สถานที่ | เสร็จเมื่อ |
|---|---|---|---|
| 0 | (ของเดิม) LIFF SDK + identity binding + core-api binding endpoints | liff.js, main.py | ✅ เสร็จ |
| 1 | เปลี่ยน `liff-config.js` → map pathname → หลาย liffId | liff-config.js | ก่อนขึ้น console |
| 2 | เพิ่ม cache-control header ที่ static files | core-api main.py | ก่อนทดสอบจริง |
| 3 | เติม safe-area + viewport-fit + pagehide STOP ให้ครบทุกหน้า | 6 html | หลังเลือก size |
| 4 | ตั้ง LIFF apps ใน Console (6 app, Size ตามตาราง 2.0, scope + Scan QR + Module mode) | Console (คุณทำเอง) | ก่อนเปิดใช้ |
| 5 | ขึ้น HTTPS (ngrok/cloudflared หรือ libn.kku.ac.th) + ตั้ง Endpoint URL | infra | ก่อนเปิดใช้ |
| 6 | (อนาคต) QR pairing ผ่าน `scanCodeV2()` → POST `/api/v1/user-robot-binding` | present/index.html + liff.js | หลัง Phase 4 |
| 7 | (อนาคต) verify ID Token ฝั่ง server (`openid`) | core-api | หลัง Phase 4 |

---

## 8. รายการตัดสินใจ (ถามก่อนลงมือ)

1. **Size ผสม** (Full/Tall ต่างหน้า) หรือ **Full ทั้งหมด**? → แนะนำผสมตามตาราง 2.0
2. **Module mode** เปิดที่หน้า controller (ซ่อน action button) หรือปล่อยไว้? → แนะนำเปิด (กัน Refresh กลางคัน)
3. **QR pairing** (`scanCodeV2`) เอาเลยไหม หรือค่อยทำ Phase 6? → แนะนำค่อยทำ หลัง core loop เสถียร
4. **HTTPS** ใช้ tunnel ชั่วคราว (ngrok/cloudflared) หรือ deploy จริงที่ `libn.kku.ac.th`?
5. **liffId** — ต้องได้จาก Console ก่อน ผมจะแก้ `liff-config.js` ให้เป็น template map รอค่าได้เลยไหม?

---

## 9. ข้อสังเกตเพิ่มเติมจาก doc (มีผลต่อสถาปัตยกรรม)

1. **LIFF กับ LINE MINI App กำลังรวมกัน** — LINE แนะนำสร้าง LIFF app ใหม่เป็น LINE MINI App (ข่าว Feb 2025)
   → ถ้าทำโปรเจกต์ระยะยาว อาจสร้างเป็น MINI App ตั้งแต่แรก (แต่ไม่บังคับสำหรับ hackathon)
2. **ไม่รองรับ OpenChat** — `getProfile()` จะล้มเหลวในกรณีส่วนใหญ่ถ้าเปิดใน OpenChat → ระบบต้อง fallback
   (โค้ด liff.js ทำ fallback แล้ว: ถ้าไม่มี profile → identity() คืน `{}`)
3. **Endpoint URL ห้ามมี fragment (#)** และต้อง **https** → ต้องแน่ใจว่า 5 path ตรงกับ console
4. **30 app ต่อ channel** — เราใช้ ~6 app ไม่มีปัญหา
