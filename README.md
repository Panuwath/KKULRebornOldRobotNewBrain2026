# KKUL Hackathon 2026 — Zenbo Control Bridge

ระบบควบคุม Zenbo สำหรับงานห้องสมุด มหาวิทยาลัยขอนแก่น โดยเชื่อมหน้า
LIFF, MQTT gateway, แอป Android บนหุ่นยนต์, Thai TTS และ KKU IntelSphere
command compiler เข้าด้วยกัน

## ส่วนประกอบ

- `zenbo-client-android/` — Android client ที่รับ MQTT command และเรียก
  Zenbo Robot SDK
- `services/core-api/` — API gateway, heartbeat และ command dispatch
- `services/liff-app/` — LIFF control, joystick, command studio และ
  presentation mode
- `services/tts-service/` — Thai text-to-speech service
- `services/compiler-service/` — แปลงคำสั่งภาษาธรรมชาติเป็น Zenbo actions
- `Map-Navigation/` — ส่วนเชื่อมการนำทางและแผนที่ห้องสมุด

## การทำงานหลัก

1. Zenbo Android client ส่ง heartbeat ไปยัง MQTT gateway
2. LIFF เลือก Zenbo ที่ออนไลน์และส่งคำสั่งผ่าน API
3. Gateway dispatch คำสั่งไปยัง topic ของหุ่นยนต์
4. Android client เรียก Robot SDK สำหรับเสียง การเคลื่อนไหว สีไฟล้อ และ
   action ที่รองรับ

## เริ่มต้นใช้งาน

กำหนดค่าจากตัวอย่างใน [SSH_DEPLOY_GUIDE.md](SSH_DEPLOY_GUIDE.md) ไว้ใน
`.env` ภายในเครื่องหรือ secret manager จากนั้นเริ่มบริการด้วย Docker
Compose ตาม deployment environment ของคุณ

ค่าลับ เช่น MQTT password, API key และ SSH credential ต้องไม่อยู่ใน Git
repository หรือไฟล์ workflow ที่เผยแพร่

## ขอบเขตการทดสอบ

การ build หรือ API health ผ่าน เป็นเพียงการยืนยันซอฟต์แวร์เท่านั้น การ
ยืนยันใช้งานจริงต้องทดสอบ heartbeat, คำสั่ง MQTT, เสียงจากลำโพง และการ
เคลื่อนไหวกับ Zenbo เครื่องเป้าหมายแยกต่างหาก
