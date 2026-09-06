# Zenbo Next Development Step: Speed-Level Control v2

- วันที่วิเคราะห์: 4 กันยายน 2026 (Asia/Bangkok)
- ทบทวนล่าสุด: 5 กันยายน 2026 — ใช้ [ผลทบทวนและลำดับงานรวม](./ZENBO_PLAN_REVIEW_2026-09-05.md) สำหรับลำดับ implementation รวม PostgreSQL และข้อแก้ไขที่แทนแผนเดิม
- Milestone ที่เสนอ: Speed-Level Control v2 — No-Motion First
- สถานะ: แผนพัฒนาเท่านั้น ยังไม่แก้โค้ด ไม่ build/deploy APK และไม่สั่ง Zenbo
- เอกสารตั้งต้น: [ZENBO_CONTROL_PERFORMANCE_UX_ANALYSIS_2026-09-04.md](./ZENBO_CONTROL_PERFORMANCE_UX_ANALYSIS_2026-09-04.md)
- ขอบเขต: Core API/MQTT, Android APK, Zenbo SDK, LIFF ทุกหน้าที่มี motion control และหลักฐาน log ย้อนหลัง

> เป้าหมายของเอกสารนี้คือทำให้ “แสดงทุก speed เพื่อให้เลือก” เป็นความสามารถจริงแบบตรวจสอบได้ ไม่ใช่เพียงเพิ่ม L1–L7 ในหน้าเว็บ ทั้งหมดในรอบนี้เป็นการอ่านและวางแผนเท่านั้น ไม่มี HTTP POST, MQTT publish, ADB, APK install หรือ RobotAPI call

## 1. ข้อสรุปสำหรับตัดสินใจ

ควรพัฒนาเป็น 2 โหมดที่ชื่อและพฤติกรรมไม่ปะปนกัน:

| โหมด | ความสามารถปัจจุบัน | UI ที่ต้องแสดง |
| --- | --- | --- |
| บังคับต่อเนื่อง (Legacy remote) | Zenbo SDK รับเฉพาะทิศทาง ไม่มีพารามิเตอร์ speed | แสดงว่า “SDK เป็นผู้กำหนดความเร็ว; หน้านี้เลือกระดับไม่ได้” และห้ามอ้างว่า L1–L7 มีผล |
| เคลื่อนที่แบบกำหนดระยะ (Relative/step motion) | Zenbo SDK รองรับ Body Speed L1–L7 จริง | แสดง L1–L7 พร้อมกันทั้งหมดและเลือกได้ตาม safety cap |

การเพิ่มปุ่ม L1–L7 ข้าง joystick เดิมอย่างเดียวจะเป็น UX ที่ไม่ตรงกับความจริง เพราะค่าที่เลือกในปัจจุบันเป็นเพียงเพดานนโยบายความปลอดภัย และไม่ได้ถูกส่งเป็นความเร็วให้ remote control

ข้อเสนอสำหรับรอบพัฒนาถัดไป:

1. Dispatch เฉพาะ T0–T4 เพื่อสร้าง contract, UI และ APK controller บน fake transport/fake actuator
2. ทุกระดับ L1–L7 ต้องมองเห็นพร้อมกัน แต่เปิดให้เลือกตาม capability และ safety cap ของหุ่นที่เลือก
3. เริ่มทุก control session ที่ L1 และไม่จำ L6/L7 ข้าม reload, reconnect หรือเปลี่ยนหุ่น
4. แยกค่าที่ผู้ใช้เลือก, เพดานที่ policy อนุญาต และค่าที่ APK ใช้จริง
5. STOP ต้องทำงานได้เสมอและไม่ขึ้นกับ speed, sequence หรือ normal queue
6. setBodyVelocity เป็น private API ให้ตัดออกจากแนวทางพัฒนาและห้าม reflection; repeated moveBody ยังต้องผ่าน feasibility ก่อนเสนอใช้งาน
7. ทดสอบ L1–L7 บนหุ่นจริงทีละระดับภายหลังเท่านั้น โดยต้องขออนุมัติแยกต่างหาก
8. แก้ความหมาย auto_stop_ms ให้เป็น hard upper bound และให้ heartbeat รายงาน effective limits ก่อน field test

## 2. Sub-agent ที่ใช้ในการวิเคราะห์

งานถูกแยกให้ sub-agent ตรวจแบบ read-only 3 สาย แล้วจึงรวมผลในเอกสารนี้:

| Sub-agent | หน้าที่ | ผลหลัก |
| --- | --- | --- |
| speed_domain_audit | ตรวจ speed ทุก domain ตั้งแต่ UI → Core → APK → SDK และ log | Body relative รองรับ L1–L7; Head relative รองรับ L1–L3; remote เป็น direction-only |
| speed_ux_design | ออกแบบ UI/state/accessibility และ browser acceptance | ต้องใช้ speed deck ที่เห็นครบ 7 ระดับ พร้อม requested/applied/cap และสถานะ disabled ที่บอกเหตุผล |
| next_step_architecture | จัด dependency, vertical tasks, safety checkpoints และขอบเขต agent | เริ่ม T0–T4 แบบ no-motion แล้วให้ independent verifier ตรวจ ก่อนแตะ SDK/หุ่นจริง |

Sub-agent รอบนี้ไม่ได้แก้ไฟล์หรือควบคุมหุ่น ส่วน work package สำหรับ sub-agent รอบพัฒนาจริงอยู่ในหัวข้อ 8 และพร้อม dispatch หลังเจ้าของระบบอนุมัติแผน

## 3. หลักฐานปัจจุบัน

### 3.1 สิ่งที่หน้า LIFF แสดง เทียบกับคำสั่งที่ส่งจริง

| Surface | สิ่งที่ UI แสดง | สิ่งที่ส่งจริง | ปัญหา |
| --- | --- | --- | --- |
| /liff/control/ | L3, L5, L6, L7; default L6 | remote_control มีเฉพาะ body/head; ค่าเลือกไปอยู่ safety.max_speed | ผู้ใช้อาจเชื่อว่าความเร็ว joystick เปลี่ยนแล้ว |
| /liff/ hold-to-drive | L1–L7; default L7 | remote_control.body ไม่มี speed และ safety hardcode max L7 | เห็นครบแต่ไม่มีผลกับปุ่มกดค้าง |
| /liff/ precise motion | L1–L7 | motion.speed ถูกส่งถึง APK และ map เป็น SpeedLevel.Body | เป็นเส้นทางเดียวที่ speed มีผลจริงในปัจจุบัน |
| /liff/teleop/ | ไม่มี selector | remote_control.body ไม่มี speed; keepalive ทุก 150 ms | ไม่สอดคล้องกับอีกสองหน้าและเสี่ยง request overlap |

จุดอ้างอิงจาก source:

- services/liff-app/control/index.html:139-145 แสดงเพียง L3/L5/L6/L7 และเลือก L6
- services/liff-app/control/index.html:757-787 ส่งค่าดังกล่าวเป็น safety.max_speed แต่ remote_control ไม่มี speed
- services/liff-app/index.html:398-407 แสดง L1–L7 และเลือก L7
- services/liff-app/index.html:1206-1219 ใช้ speed กับ precise motion แต่ safety ยัง hardcode L7
- services/liff-app/index.html:1751-1771 ส่ง hold-to-drive แบบ direction-only ทุก 350 ms
- services/liff-app/teleop/index.html:352-371 ส่ง direction-only ทุก 150 ms

ยังพบ malformed DOM ใน services/liff-app/control/index.html:130-148 ซึ่งทำให้โซน control บนมือถือมีโอกาสถูกตัด จึงต้องแก้ก่อนถือว่า speed deck ใช้งานได้จริง

### 3.2 Contract และ APK ปัจจุบัน

| ชั้น | หลักฐาน | ผลต่อการออกแบบ |
| --- | --- | --- |
| Core MotionCommand | main.py:1361-1365 ระบุ speed 1–7 แต่ไม่มี ge/le validation | ค่า invalid อาจผ่าน Core |
| Core HeadCommand | main.py:1367-1370 ระบุผิดว่า 1–5 และไม่มี validation | SDK รองรับจริงเพียง L1–L3 |
| Core SafetyModeCommand | main.py:1411-1418 มี max_speed 1–7 | ค่านี้คือ policy cap ไม่ใช่ requested speed |
| Core RemoteControlCommand | main.py:1464-1466 มีเพียง body/head | continuous remote ยังไม่มี speed contract |
| APK discrete body | ZenboSdkBridge.java:229-234 เรียก moveBody พร้อม SpeedLevel.Body | รองรับระดับความเร็วจริง |
| APK discrete head | ZenboSdkBridge.java:239-245 เรียก moveHead พร้อม SpeedLevel.Head | ต้องจำกัด L1–L3 |
| APK remote | ZenboSdkBridge.java:296-305 เรียก remoteControlBody/Head ด้วย direction เท่านั้น | selector ใกล้ joystick ไม่มีทางมีผลจริง |
| APK safety | ZenboClientService.java:1583-1666 ใช้ max speed กับ safeMoveBody | remote path ไม่อ่าน mMaxMotionSpeed |
| Heartbeat | ZenboClientService.java:1873-1895 ส่ง capabilities แบบรายชื่อกว้าง ๆ | ยังบอกไม่ได้ว่า speed mode ใดรองรับ/เปิดใช้งาน |
| Field readiness | main.py:3581-3590 ตรวจ max distance/speed/auto-stop แต่ heartbeat ปัจจุบันรายงานเพียง guard booleans ที่ ZenboClientService.java:1890-1892 | ยังพิสูจน์ motion limits จาก heartbeat ไม่ได้ |
| Discrete watchdog | ZenboClientService.java:1661-1664 ใช้ Math.max(autoStop, เวลาคาดการณ์ + 4 วินาที) | auto_stop_ms ปัจจุบันไม่ใช่ hard upper bound; เป็น blocker ก่อน field calibration |
| APK build safety | app/build.gradle:107 ตั้ง SAFETY_MONITOR_ENABLED=false เป็นค่า default; stable/drive/installLite สืบทอดค่านี้ และมีเพียง legacy ที่ override เป็น true ที่บรรทัด 184 | ห้ามนำ build ปัจจุบันไป calibration จนมี safety-enabled artifact และ installed-build proof |

Zenbo SDK v2.1.22 และ official sample ยืนยัน:

- MotionControl.SpeedLevel.Body มี L1–L7
- MotionControl.SpeedLevel.Head มี L1–L3
- moveBody(..., SpeedLevel.Body) เลือกระดับได้
- moveHead(..., SpeedLevel.Head) เลือกระดับได้
- remoteControlBody(Direction.Body) และ remoteControlHead(Direction.Head) ไม่มี speed parameter
- setBodyVelocity(float) เป็น private method ตาม SDK JAR ที่ตรวจซ้ำวันที่ 5 กันยายน 2026 ไม่ใช่ public API ที่รองรับการเรียกจากแอป

### 3.3 Log ย้อนหลังที่เกี่ยวกับ speed

อ่าน data/command_history.sqlite3 ช่วง 30 สิงหาคม 2026 เวลา 11:56:50–13:42:55 BKK แบบ aggregate โดยไม่คัดลอก payload, user ID หรือข้อมูลส่วนบุคคล พบว่า:

| รายการ | จำนวน | ข้อสรุป |
| --- | ---: | --- |
| command history ทั้งหมด | 238 | snapshot เก่า ไม่ใช่หลักฐาน runtime ล่าสุด |
| motion object จริง | 4 | ทั้ง 4 รายการใช้ speed 2 |
| remote_control object จริง | 223 | body 217, head 6 |
| แถวที่ไม่ใช่ motion/remote object | 11 | แยกออกจาก remote; ไม่ใช่คำสั่ง remote ชนิด other |
| remote ที่มี speed field | 0 | ยืนยันว่าเส้นทาง remote ปัจจุบันไม่บันทึก/ส่ง speed |

ยังไม่มีหลักฐานย้อนหลังว่า:

- ได้ทดสอบ Body L1–L7 ครบทุกระดับบนหุ่นจริง
- ค่าระดับใดเท่ากับกี่ m/s หรือกี่ deg/s
- pointer-up ถึงล้อหยุดใช้เวลาจริงเท่าใดในแต่ละระดับ
- APK version/hash ที่ติดตั้งตรงกับ source revision ปัจจุบันแล้ว

ดังนั้นห้ามใช้คำว่า “เร็วขึ้นแล้ว”, “smooth แล้ว” หรือแสดงหน่วย m/s จากเพียง HTTP 200, MQTT publish หรือ action_done

### 3.4 Speed domain ที่ต้องแยกจากกัน

| Domain | ช่วง/ชนิด | ใช้ selector ร่วมกับ Body ไม่ได้ |
| --- | --- | --- |
| Body relative motion | SDK level L1–L7 | เป็นเป้าหมายของ speed deck นี้ |
| Head relative motion | SDK level L1–L3 | ต้องมี component/validation แยก |
| Body/Head remote | SDK-managed, direction-only | SDK ไม่เปิดให้ LIFF เลือกระดับ |
| Line follower | L1–L3 แต่ bridge ยังไม่เปิดใช้ | เป็น capability อีกชนิด |
| Speech speed | float ประมาณ 0.41–1.99 | เป็นอัตราการพูด |
| Wheel-light speed | enum ของไฟล้อ | ค่า FAST/SLOW ปัจจุบันยังไม่ตรง enum SDK ทุกค่า |
| Emotional-action speed | float และยังต้องเพิ่ม validation | ไม่ใช่ motion speed |
| Scenario risk L1–L8 | ระดับความเสี่ยง | ห้ามเรียก “L7” ลอย ๆ เพราะชนกับ Body Speed |

คำที่แนะนำใน UI และ log คือ “Body Speed 3/7” แทน “L3” เพียงอย่างเดียว

## 4. Product และ UX specification

ขอบเขตของ slice แรกต้องชัด:

- Relative/step motion: speed deck L1–L7 เป็น control ที่เลือกได้จริงตาม capability/cap
- Legacy remote/hold-to-drive: speed deck ยังมองเห็นเพื่อความสม่ำเสมอ แต่ disabled พร้อมข้อความว่า SDK ไม่เปิดให้เลือก speed
- T1–T4 ใช้ bounded relative motion กับ fake actuator เท่านั้น; continuous drive แยกเป็นงานวิจัย
- ห้ามเปิด speed-selectable continuous UI จาก mock test หรือ contract test เพียงอย่างเดียว

### 4.1 รูปแบบ speed deck

L1–L7 ต้องเห็นพร้อมกัน ไม่ซ่อนใน dropdown และไม่ต้อง scroll แนวนอน:

~~~text
┌────────────────────────────────────────┐
│ Booky-1  ● ออนไลน์                    │
│ Heartbeat 3 วินาที · RobotAPI พร้อม   │
│ Safety cap: Body Speed 5/7             │
├────────────────────────────────────────┤
│ ระดับการวิ่งของล้อ (SDK level)        │
│ [L1] [L2] [L3] [L4]                   │
│ [L5] [L6 ⚠] [L7 ⚠]                    │
│ เลือก: 3/7 · APK ใช้จริง: ยังไม่สั่ง   │
│ ไม่ใช่ค่าความเร็วอินเทอร์เน็ตหรือ m/s │
├────────────────────────────────────────┤
│ โหมด: เคลื่อนที่แบบกำหนดระยะ          │
│              Joystick/Pad              │
├────────────────────────────────────────┤
│       [ หยุดฉุกเฉิน Booky-1 ]          │
└────────────────────────────────────────┘
~~~

ป้ายก่อน calibration:

| ค่า | ป้ายที่แสดง |
| --- | --- |
| L1 | Body Speed 1/7 — ต่ำสุดใน SDK |
| L2 | Body Speed 2/7 |
| L3 | Body Speed 3/7 |
| L4 | Body Speed 4/7 |
| L5 | Body Speed 5/7 |
| L6 | Body Speed 6/7 — ระดับสูง ต้องยืนยัน |
| L7 | Body Speed 7/7 — สูงสุดใน SDK ต้องยืนยัน |

ชื่อ “ช้ามาก/ปกติ/เร็ว” และหน่วยจริงควรเพิ่มหลัง calibration เท่านั้น

Responsive/accessibility:

- 320–575 px: 4 ปุ่มแถวแรก + 3 ปุ่มแถวสอง
- ตั้งแต่ 576 px: แสดง 7 ปุ่มในแถวเดียวเมื่อพื้นที่พอ
- แต่ละระดับอย่างน้อย 44×44 px; แนะนำ 48×56 px
- STOP อย่างน้อย 56×56 px และ sticky โดยไม่บัง speed/joystick
- ใช้ radiogroup/radio semantics, roving tabindex, Arrow/Home/End/Space/Enter
- visible focus ชัด และบอก selected/disabled/high-speed ด้วยข้อความหรือไอคอน ไม่ใช้สีอย่างเดียว
- aria-live polite สำหรับ selection/ACK; assertive ใช้เฉพาะ STOP/fault

### 4.2 State model

| State | L1–L7 | Direction control | STOP | ข้อความ |
| --- | --- | --- | --- | --- |
| Loading | เห็นครบแต่ disabled | disabled | disabled | กำลังตรวจสถานะ |
| No target | เห็นครบแต่ disabled | disabled | disabled | เลือก Zenbo ก่อน |
| Offline/stale | เห็นครบแต่ disabled | disabled | เปิดเมื่อมี active lease/target | Heartbeat ขาด พร้อมอายุ |
| Capability missing | เห็นครบแต่ disabled | legacy remote ใช้ได้ตาม policy | enabled | APK นี้ยังไม่รองรับ speed-selectable mode |
| Safety not ready | เห็นครบ; ค่าเกิน cap disabled | disabled | enabled เมื่อมี target | แสดง blocker รายข้อ |
| Ready/disarmed | ระดับที่ policy อนุญาตเลือกได้; default L1 | disabled | enabled | เลือกระดับแล้วกด “พร้อมควบคุม” |
| Armed/idle | เลือกได้ | enabled | enabled | แสดง target และ lease |
| Moving | selector locked | active ได้หนึ่งทิศ | enabled/sticky | requested และ applied แยกกัน |
| Stopping | selector locked | disabled | สถานะกำลังหยุด | รอ APK/SDK ACK |
| ACK mismatch/fault | locked | disabled | enabled | requested ≠ applied พร้อมเหตุผล |

Movement gate ต้องบังคับทั้ง UI, Core และ APK:

- operator authorization ผ่าน
- ผู้ใช้เลือก target อย่างชัดเจน
- heartbeat age ไม่เกิน 10 วินาทีสำหรับ motion
- robot_api_ready = true
- safety policy ได้ ACK
- requested speed ไม่เกิน policy cap
- ไม่มี emergency/fault state

Core ปัจจุบันถือ online ได้นานถึงประมาณ 90 วินาที ซึ่งยาวเกินไปสำหรับ motion gate จึงต้องมี freshness gate แยกสำหรับการเคลื่อนไหว

### 4.3 Interaction rules

1. เลือก L1–L7 เป็น local pending state และต้องสร้าง network request 0 รายการ
2. แสดง “เลือก Body Speed 3/7 แล้ว — ยังไม่สั่งเคลื่อนที่”
3. ส่ง requested speed เมื่อเริ่มคำสั่งที่รองรับ speed จริงเท่านั้น
4. ห้ามขึ้น “ใช้จริง” จน APK/RobotAPI ACK
5. ห้าม silent clamp; ค่าเกิน cap ต้อง disabled พร้อมเหตุผล หรือถูก reject ด้วย typed error
6. ขณะ moving ให้ lock selector และต้อง STOP สำเร็จก่อนเปลี่ยนระดับ
7. L6/L7 เห็นเสมอ แต่ปลดล็อกต่อ control lease พร้อม confirmation และไม่จำข้าม session
8. reload, reconnect, robot switch, page background หรือ stale heartbeat ให้กลับ L1
9. pointer release/cancel, lost capture, blur, pagehide หรือ stale heartbeat ต้องเข้า STOP flow เพียงหนึ่ง logical command
10. แยก “network latency 85 ms” ออกจาก “Body Speed 3/7” คนละแถวและคนละคำ
11. Legacy remote ต้องเขียนตรง ๆ ว่า “SDK เป็นผู้กำหนดความเร็ว; หน้านี้เลือกระดับไม่ได้”
12. ไม่ใช้ dropdown เป็น primary control เพราะผู้ใช้ต้องเห็นทุกระดับและสถานะทั้งหมดพร้อมกัน

## 5. Canonical capability และ command contract

### 5.1 Capability จาก APK

UI ต้องอ่าน capability จาก fresh heartbeat/robot status ไม่ hardcode ช่วง:

~~~json
{
  "schema_version": 1,
  "motion": {
    "body_relative": {
      "supported": true,
      "speed_levels": [1, 2, 3, 4, 5, 6, 7],
      "default_speed_level": 1,
      "policy_max_speed_level": 3
    },
    "body_remote": {
      "supported": true,
      "speed_selectable": false,
      "reason": "SDK_DIRECTION_ONLY"
    },
    "head_relative": {
      "supported": true,
      "speed_levels": [1, 2, 3],
      "default_speed_level": 1
    }
  },
  "robot_api_ready": true,
  "reported_at_ms": 0
}
~~~

Fallback ต้อง fail closed: หาก schema หาย, heartbeat stale หรือ APK เก่า ให้ speed deck ยังมองเห็นแต่ disabled พร้อมเหตุผล และห้ามสมมติว่า L1–L7 ใช้ได้

### 5.2 คำสั่งที่มี speed จริง

แยก trust boundary เป็น 2 schema อย่างชัดเจน LIFF ส่งได้เฉพาะ intent/request และห้ามเป็นผู้กำหนด safety policy:

~~~json
{
  "command_id": "uuid",
  "source_session_id": "uuid",
  "source_seq": 12,
  "issued_at_ms": 0,
  "expires_at_ms": 0,
  "motion_request": {
    "control_mode": "RELATIVE_BODY",
    "x_m": 0.10,
    "y_m": 0.0,
    "theta_deg": 0.0,
    "requested_speed_level": 3
  }
}
~~~

Core ต้องตรวจ role, fresh heartbeat และ permit แล้วจึงสร้าง authoritative envelope สำหรับ APK จาก server-side policy:

~~~json
{
  "command_id": "uuid",
  "source_session_id": "uuid",
  "source_seq": 12,
  "issued_at_ms": 0,
  "expires_at_ms": 0,
  "motion": {
    "control_mode": "RELATIVE_BODY",
    "x_m": 0.10,
    "y_m": 0.0,
    "theta_deg": 0.0,
    "requested_speed_level": 3
  },
  "policy": {
    "policy_version": "server-issued-version",
    "max_body_speed_level": 5,
    "max_distance_m": 0.15,
    "hard_stop_after_ms": 1500
  }
}
~~~

Core ต้อง ignore/reject ค่า policy, cap, distance หรือ auto-stop ที่ client พยายามส่ง และ APK ต้อง validate + enforce server-issued hard caps ซ้ำ ห้ามเชื่อ LIFF เป็น policy authority

Legacy remote ต้องไม่มี speed field ที่ระบบจะละเลย:

~~~json
{
  "command_id": "uuid",
  "remote_control": {
    "control_mode": "SDK_MANAGED",
    "body": "FORWARD"
  }
}
~~~

หาก feasibility test พิสูจน์ continuous speed-selectable ได้ จึงค่อยเพิ่ม contract รุ่นใหม่ เช่น BOUNDED_SPEED_LEVEL พร้อม sequence/TTL/lease โดยห้ามนำ field ไปใส่ใน legacy remote แล้วไม่ใช้จริง

ตัวอย่าง drive_v2 ด้านล่างถูกเลื่อนออกจาก T1–T4 ในการทบทวนวันที่ 5 กันยายน เก็บไว้เป็นแนวคิดวิจัยเท่านั้น ห้าม implement/freeze schema นี้ในรอบแรก ให้ใช้ RELATIVE_BODY ด้านบนแทน:

~~~json
{
  "command_id": "uuid",
  "source_session_id": "uuid",
  "source_seq": 12,
  "expires_at_ms": 0,
  "drive_v2": {
    "action": "START",
    "direction": "FORWARD",
    "requested_speed_level": 3,
    "lease_ms": 1200
  }
}
~~~

draft นี้ยังไม่ใช่สัญญาว่า Zenbo SDK ทำ continuous speed ได้จริง การเลือก adapter และการเปิด capability ต้องรอ T5/T6

### 5.3 ACK และ history

~~~json
{
  "command_id": "uuid",
  "control_mode": "RELATIVE_BODY",
  "state": "REJECTED",
  "requested_speed_level": 5,
  "policy_max_speed_level": 4,
  "effective_speed_level": null,
  "received_at_ms": 0,
  "sdk_applied_at_ms": null,
  "reject_reason": "SPEED_EXCEEDS_POLICY"
}
~~~

กติกา:

- Core validation: Body เป็น integer 1–7; Head เป็น integer 1–3
- invalid 0/8/float สำหรับ Body และ 0/4 สำหรับ Head ต้อง reject 422
- APK ตรวจซ้ำก่อนเรียก SDK
- หาก policy cap ต่ำกว่าค่าที่ขอ ต้อง reject แบบ SPEED_EXCEEDS_POLICY; effective เป็น null และห้ามเรียก actuator
- STOP bypass speed/sequence/normal queue และไม่รอ capability
- deadline/deadman ต้องเป็น hard upper bound ที่ตรวจด้วย deterministic clock ไม่ใช่ minimum watchdog
- history เก็บ command_id, source session/sequence, mode, requested/cap/effective, APK version, state และ timestamps
- HTTP accepted และ MQTT published ยังไม่ใช่ SDK_APPLIED หรือ physical success

## 6. Dependency plan

~~~mermaid
flowchart TD
    T0[T0 Freeze source + safety boundary] --> T1[T1 Contract + capability + validation]
    T1 --> T2[T2 APK controller + FakeDriveActuator]
    T1 --> T3[T3 Shared LIFF speed deck + mocked transport]
    T2 --> T4[T4 Offline vertical integration]
    T3 --> T4
    T4 --> G0{No-Motion Checkpoint}
    G0 --> T5[T5 SDK continuous-speed feasibility]
    T5 --> D{Decision}
    D -->|ไม่ผ่าน| A[คง Legacy remote แบบ SDK-managed + Relative L1-L7]
    D -->|ผ่าน safety proof| T6[T6 Speed-aware SDK adapter behind OFF flag]
    A --> T7[T7 Capability ACK history telemetry]
    T6 --> T7
    T7 --> G1{Human approval for field test}
    G1 --> T8[T8 Supervised L1 to L7 calibration]
    T8 --> T9[T9 Staged rollout + rollback drill]
~~~

หลักสำคัญ:

- รอบแรก dispatch เฉพาะ T0–T4
- T2 และ T3 ทำขนานกันได้หลัง T1 freeze
- T4 ต้องตรวจโดย agent ที่ไม่ได้ implement T1–T3
- ห้ามหลาย agent แก้ main.py หรือ ZenboClientService.java พร้อมกัน
- T5–T9 ต้องรอ checkpoint/authorization ตามลำดับ

## 7. Detailed task breakdown

### T0 — Freeze implementation base และ safety boundary (S)

รายละเอียด:

- ระบุ source SHA/base และรายการ dirty files ที่ต้องรักษา
- ใช้ branch/worktree แยกสำหรับรอบพัฒนา
- เพิ่มแผน feature flag SPEED_LEVEL_DRIVE_ENABLED=false ทุก environment
- ล็อก safety/deadman defaults ไม่ให้เปลี่ยนเป็นผลข้างเคียง
- embedded broker credential ต้องถูกถอน/rotate ก่อน build ที่ติดตั้งได้

Acceptance:

- มี SHA/base, owner และ file boundary ชัด
- feature flag เริ่มต้นเป็น OFF
- ไม่มีไฟล์เดิมของผู้ใช้ถูก stage/overwrite
- ไม่มีการเปลี่ยน collision/fall guard, base unlock หรือ deadman

Verification:

- git/status provenance snapshot
- config test ยืนยัน flag OFF
- review diff ต้องมีเฉพาะไฟล์ใน scope

Dependencies: ไม่มี

Checkpoint: เจ้าของระบบยืนยัน base ก่อนเริ่ม T1–T3

### T1 — Core contract, validation และ capability gate (M)

Likely files:

- services/core-api/main.py
- services/core-api/test_drive_control.py (ใหม่)
- services/core-api/test_robot_capabilities.py (ใหม่ ถ้าจำเป็น)

งาน:

- แยก requested_speed_level กับ max_body_speed_level
- แก้ Body validation เป็น 1–7 และ Head เป็น 1–3
- เพิ่ม command_id, source_session_id, source_seq และ expiry
- แยก LIFF request schema ออกจาก Core→APK envelope; Core สร้าง policy จาก authenticated role/permit/config เท่านั้น
- ignore/reject policy, cap, distance และ auto-stop ที่ client ส่งมาเอง
- เพิ่ม capability/fresh-heartbeat gate แบบ fail closed
- ตรวจว่า heartbeat รายงาน policy max distance/speed/auto-stop ที่ Core ใช้ตัดสินจริง
- STOP ใช้ route ที่ bypass gate ปกติและระบุ target ชัด
- feature flag OFF ต้องไม่ publish คำสั่ง speed-selectable รุ่นใหม่; legacy remote และ STOP คงเส้นทางเดิมตามสิทธิ์ที่มี

Acceptance:

- invalid, stale, out-of-order, unknown capability และ speed เกิน cap ถูก reject แบบ typed error
- ไม่มี silent clamp
- test พิสูจน์ว่า client-supplied policy ไม่สามารถเพิ่ม speed/distance/deadline ได้
- old APK ยังใช้ legacy remote ได้ แต่ response/UI ไม่อ้างว่าปรับ speed ได้
- production publish count ของคำสั่ง speed-selectable รุ่นใหม่ = 0 เมื่อ feature flag ปิดหรือ capability ไม่รองรับ

Verification:

- unit/API tests ด้วย fake publisher
- cases: Body 0/1/7/8/float, Head 0/1/3/4, expired TTL, duplicate sequence, missing capability
- STOP test ต้องผ่านแม้ speed payload เสีย

Dependencies: T0

Human review: freeze JSON schema/error codes ก่อน T2/T3

### T2 — APK priority controller ด้วย FakeDriveActuator (M)

Likely files:

- zenbo-client-android/app/src/main/java/com/hackathon/zenboclient/model/InteractCommand.java
- zenbo-client-android/app/src/main/java/com/hackathon/zenboclient/drive/DriveActuator.java (ใหม่)
- zenbo-client-android/app/src/main/java/com/hackathon/zenboclient/drive/SpeedLevelDriveController.java (ใหม่)
- zenbo-client-android/app/src/test/java/com/hackathon/zenboclient/drive/SpeedLevelDriveControllerTest.java (ใหม่)

งาน:

- parse/validate RELATIVE_BODY contract หลัง feature flag ที่ปิดอยู่ โดยไม่ผูกกับ RobotAPI
- priority STOP/safety > direction change > normal
- latest-wins queue depth ไม่เกิน 1
- dedupe command_id/sequence และ drop expired/out-of-order
- command_id ซ้ำไม่สร้าง actuator call ซ้ำ; หนึ่ง explicit action ต่อหนึ่ง bounded move และไม่มี keepalive ต่ออายุ relative move
- ทำ ACK state machine บน fake actuator

Acceptance:

- L1–L7 ถึง fake actuator ตรงค่า
- requested/cap/effective ถูกเก็บครบ
- direction/speed change ต้อง STOP state ก่อน action ใหม่
- STOP preempt และ deadman ไม่เกินค่าปัจจุบัน
- deadline/deadman เป็น hard upper bound และ test ไม่ยอมให้ dynamic watchdog ขยายเกิน policy
- test path ไม่มี import/call ZenboSdkBridge หรือ RobotAPI

Verification:

- local JVM unit tests
- deterministic clock tests สำหรับ TTL/deadman
- concurrency tests สำหรับ duplicate/latest-wins/STOP race

Dependencies: T1 contract freeze

Checkpoint: ยังห้าม instrumentation, ADB, APK install และ RobotAPI

### T3 — Shared LIFF speed deck และ truthful states (M)

Likely files:

- services/liff-app/shared/zenbo-drive-control.js (ใหม่)
- services/liff-app/shared/zenbo-drive-control.test.mjs (ใหม่)
- services/liff-app/index.html
- services/liff-app/control/index.html
- services/liff-app/teleop/index.html

งาน:

- component/config เดียวสำหรับ L1–L7 ทุก route
- แก้ malformed DOM ของ /control/
- แสดง capability, policy cap, requested และ applied
- default/reset L1 และ lock selector ขณะ moving
- legacy remote แสดง SDK-managed/non-selectable อย่างตรงไปตรงมา
- เปิดการเลือก L1–L7 เฉพาะ relative/step capability; legacy remote ต้องเห็นแต่ disabled
- STOP sticky และ target-specific
- selection-only ต้องไม่ส่ง network

Acceptance:

- L1–L7 เห็นพร้อมกันที่ viewport ทุกขนาด
- ค่าเกิน cap ยังเห็นแต่ disabled พร้อมเหตุผล
- no robot/offline/stale/capability missing แสดง state ถูกต้อง
- continuous remote ยัง disabled จนกว่าจะมี fresh speed-selectable capability หลัง T5/T6
- L6/L7 มี warning/confirmation ต่อ lease
- keyboard/screen reader ใช้ครบทั้ง 7 ระดับ
- ไม่มี fallback L7

Verification:

- component tests ด้วย mocked capability/ACK
- browser test 320×568, 360×800, 390×844, 768×1024, 1440×900
- console ไม่มี component error/warning
- selection response เป้าหมาย INP ต่ำกว่า 200 ms
- intercept network ยืนยันเลือก speed แล้วมี POST 0 รายการ

Dependencies: T1 contract freeze

Checkpoint: browser ใช้ mock origin เท่านั้น

### T4 — Offline vertical integration และ independent verification (M)

เส้นทางทดสอบ:

~~~text
Mock browser → fake Core → serialized JSON → APK controller → FakeDriveActuator
~~~

ใช้ golden JSON ชุดเดียวกันทั้ง Core, JS และ Android

Acceptance:

- L1–L7 ผ่านครบและ requested/effective ตรงกัน
- duplicate/reorder/expired/ACK mismatch ผ่าน
- pointer release/cancel/blur/pagehide/stale heartbeat สร้าง STOP หนึ่ง logical command
- STOP ไม่รอ speed selector หรือ normal queue
- ไม่มี production HTTP/MQTT, APK install, ADB หรือ RobotAPI call
- verifier ที่ไม่ได้ implement ยืนยัน actuator motion call จริง = 0

Verification:

- contract compatibility tests
- failure injection: timeout, delayed ACK, disconnect, reconnect, stale capability
- responsive/accessibility evidence pack
- independent diff/test review

Dependencies: T2 + T3

Checkpoint: ต้องผ่าน No-Motion Checkpoint ก่อน T5

### T5 — Continuous-speed feasibility และ ADR (S/M)

คำถามที่ต้องตอบ:

1. มี public API ที่รองรับ continuous speed หรือไม่; setBodyVelocity เป็น private และห้ามใช้ reflection เพื่อเข้าถึง
2. มี callback/telemetry ที่พิสูจน์ applied velocity ได้หรือไม่
3. bounded moveBody เหมาะกับการกดค้างหรือสร้าง queue/watchdog/stutter
4. ถ้าไม่มีทางที่ปลอดภัย ควรคง remote แบบ SDK-managed/non-selectable และใช้ L1–L7 เฉพาะ relative mode หรือไม่

Acceptance:

- มี ADR เลือกหนึ่งทางพร้อมหลักฐานและ rollback
- การตรวจ static/JAR/compile ไม่ถูกนับเป็น physical proof
- ไม่มี repeated moveBody production loop โดยยังไม่มี evidence

Dependencies: T4 ผ่าน

Checkpoint: ขออนุมัติก่อน bench/field action ใด ๆ

### T6 — SDK adapter หลัง decision gate (M)

งาน:

- ถ้า T5 ไม่ผ่าน: รักษา remote แบบ SDK-managed/non-selectable และ map L1–L7 เฉพาะ moveBody
- ถ้า T5 ผ่าน: เพิ่ม speed-aware adapter หลัง feature flag OFF พร้อม STOP/deadman/resource ownership
- emergency STOP เดิมต้องยังทำ stopMoving + cancelCommandAll

Acceptance:

- adapter map level ตรง capability
- invalid/null enum ไม่ถึง SDK
- STOP preempt ทุก state
- legacy behavior ไม่เปลี่ยนเมื่อ flag OFF

Dependencies: T5 + human approval

### T7 — Capability, ACK, history และ observability (M)

งาน:

- heartbeat รายงาน structured motion capability และ robot_api_ready
- heartbeat รายงาน effective max distance, max body speed และ hard auto-stop ที่ field gate ตรวจได้
- heartbeat รายงาน safety_monitor_enabled/active และ required sensor coverage จาก installed build/runtime
- ACK มี command_id, requested/cap/effective, state/reason และ timestamps
- history/API status แสดง APK version/hash และ SDK state
- UI แสดง Gateway accepted → APK received → SDK applied/rejected แยกกัน

Acceptance:

- ไม่มี UI ขึ้น “ใช้จริง” จาก HTTP/MQTT อย่างเดียว
- stale capability ปิด motion controls
- artifact ที่ safety monitor ปิดหรือ sensor coverage ไม่ครบถูก mark FIELD_NOT_READY
- trace command เดียวกันได้ตลอด LIFF → Core → MQTT → APK → SDK

Dependencies: T6 หรือ fallback decision จาก T5

### T8 — Supervised L1–L7 physical calibration (M)

ดำเนินการภายหลังและต้องมี field permit แยก:

- ล็อก exact source SHA, APK version/hash และ installed version
- installed artifact ต้องเป็น safety-enabled build; heartbeat ต้องยืนยัน safety_monitor_active=true และ required sensor coverage ครบ
- heartbeat ≤10 วินาที, MQTT client เดียว, RobotAPI ready
- collision/fall guards active และ safety policy ACK
- Core อ่าน effective motion limits จาก fresh heartbeat ได้ และ APK ใช้ auto-stop เป็น hard upper bound
- พื้นที่โล่ง มี operator อยู่ข้าง physical emergency STOP
- ทดสอบทีละระดับ L1 → L7; ห้าม automated sequence
- เริ่มทุกระดับด้วย bounded distance ไม่เกิน 0.15 m
- forward/backward/turn left/turn right อย่างน้อย 3 รอบต่อ level/direction เมื่อผ่าน gate
- วัด issued, APK received, SDK applied, physical onset, velocity, stop latency, stop distance และ overshoot
- failure ของ STOP, deadman, sensor หรือ telemetry ที่ระดับใดให้ยุติระดับถัดไปทันที
- L6/L7 ต้องมี permit ระบุระดับและหมดอายุได้

เป้าหมายเริ่มต้นที่ต้องวัด ไม่ใช่ข้ออ้างว่าผ่านแล้ว:

- pointer-up ถึง physical stop p95 ≤300 ms
- ไม่มี command overlap/queue growth
- requested = applied หรือมี rejection ที่ชัด
- ไม่มี unintended resume หลัง reconnect

Dependencies: T7 + human approval + field permit

### T9 — Staged rollout และ rollback drill (S/M)

- เปิดให้ internal operator ที่ L1–L3 ก่อน
- L4–L5 หลัง telemetry ผ่าน
- L6–L7 หลัง calibration/attestation รายระดับ
- monitor STOP latency, reject rate, ACK mismatch, stale heartbeat และ command queue depth
- rollback โดยปิด Core/APK flag, ถอน capability และกลับไป APK hash ที่ยืนยันไว้

Dependencies: T8 ผ่าน

## 8. Work packages สำหรับ sub-agent รอบพัฒนา

Dispatch ชุดแรกหลังอนุมัติ:

| Agent | รับงาน | Ownership | ห้ามทำ | Exit criteria |
| --- | --- | --- | --- | --- |
| speed_contract_core | T1 | main.py และ Core tests เท่านั้น | ห้ามแก้ APK/LIFF; ห้าม publish production | contract/validation/fail-closed tests ผ่าน |
| speed_apk_controller | T2 | model + drive controller + local JVM tests | ห้ามเรียก ZenboSdkBridge/RobotAPI | fake actuator ครบ L1–L7, STOP/dedupe/deadman ผ่าน |
| speed_selector_ui | T3 | shared component + 3 LIFF routes + mocked tests | ห้ามต่อ production API/MQTT | browser/accessibility matrix ผ่าน |
| speed_independent_qa | T4 หลัง T1–T3 | golden contract + offline E2E/evidence | ห้ามแก้ implementation หลักก่อนรายงาน finding | ยืนยัน motion call จริง = 0 และ checkpoint ผ่าน |

Dispatch ชุดหลัง:

| Agent | รับงาน | Gate |
| --- | --- | --- |
| speed_sdk_probe | T5 | T4 ผ่านและเจ้าของอนุมัติ |
| speed_sdk_adapter | T6 | ADR และ safety approach ได้รับอนุมัติ |
| speed_observability | T7 | contract/adapter freeze |
| speed_field_qa | T8 | exact safety-enabled APK installed + sensor coverage + field permit + operator พร้อม |
| speed_release | T9 | calibration/attestation ผ่าน |

ข้อกำหนดการทำงานร่วมกัน:

- Agent Core เป็น owner คนเดียวของ main.py ในช่วง T1
- Agent APK adapter เป็น owner คนเดียวของ ZenboClientService.java ในช่วง T6
- Agent UI ใช้ shared config เดียว ห้าม copy range/labels ไปสามหน้า
- Agent QA ต้องเป็นคนละ agent กับผู้ implement
- ทุก agent ส่ง diff, test evidence และรายการสิ่งที่ยังไม่ได้พิสูจน์

## 9. No-Motion Checkpoint

ก่อนจบ T4 ต้องผ่านทุกข้อ:

1. Core ใช้ fake publisher และ feature flag OFF; test พิสูจน์ publish count = 0
2. Browser intercept ทุก request และไม่เปิด production origin
3. Android ใช้ local JVM + FakeDriveActuator เท่านั้น
4. ไม่มี production broker host/token ใน test process
5. ไม่มี instrumentation, ADB, APK install หรือ RobotAPI
6. ไม่มีการแก้ collision/fall guard, deadman, base unlock หรือ field readiness
7. verifier ตรวจว่า test path ไม่มี moveBody, remoteControlBody หรือ stopMoving จริง
8. ผู้ใช้ตรวจเอกสาร/evidence และอนุมัติก่อน T5/T8

## 10. Browser test matrix

| Scenario | Viewport/state | Expected |
| --- | --- | --- |
| Offline initial | 390×844, no robots | L1–L7 visible disabled; movement disabled |
| Narrow layout | 320×568 | 4+3 grid, no clipping, STOP visible |
| Ready cap L3 | 390×844 | L1–L3 selectable; L4–L7 visible disabled with reason |
| Ready cap L7 | 768×1024 | all visible; default remains L1 |
| Selection only | ทุกขนาด | zero POST/MQTT; local status only |
| Missing operator role | 390×844 | read-only levels; no arm/drive |
| Moving at L3 | 390×844 | selector locked; requested/applied visible |
| Try L5 while moving | 390×844 | no speed change; instruct STOP first |
| Heartbeat stale | ทุกขนาด | lock drive, one STOP flow, stale age visible |
| ACK mismatch | ทุกขนาด | fault state; requested/applied both shown |
| Legacy APK | ทุกขนาด | all levels visible disabled; SDK-managed/non-selectable explanation |
| Keyboard/screen reader | desktop/mobile | complete navigation/names/reasons/ACK announcement |
| Route consistency | /, /control/, /teleop/ | same order, labels, default and cap semantics |

## 11. Definition of Done

ระบบยังไม่ถือว่า “เลือกทุก speed ได้จริง” จนกว่าจะครบ:

- L1–L7 มองเห็นพร้อมกันและใช้ shared source เดียวทุกหน้า
- UI เปิดเลือกเฉพาะ capability ที่ APK รายงานจาก fresh heartbeat
- Body 1–7 และ Head 1–3 ถูก validate ทั้ง Core และ APK
- requested, policy cap และ effective/applied แยกกันใน UI, ACK และ history
- ไม่มี silent clamp หรือ fallback L7
- STOP preempt, deadman, duplicate/TTL/sequence tests ผ่าน
- offline E2E ครบโดย motion call จริง = 0
- exact APK version/hash ที่ติดตั้งตรงกับ source
- installed build เปิด safety monitor และ heartbeat ยืนยัน sensor coverage จริง
- physical test ครบระดับ/ทิศทางตาม permit และมี operator attestation
- API/MQTT/SDK/physical evidence ถูกแยกชั้น
- มี staged rollout และ rollback ที่ทดสอบได้

## 12. สิ่งที่ไม่ควรทำ

- เพิ่ม L1–L7 ใน dropdown เดิมแล้วประกาศว่าความเร็ว joystick เปลี่ยนได้
- ใช้ safety.max_speed เป็น requested speed
- ส่ง speed field เข้า remote packet ทั้งที่ APK/SDK ไม่อ่าน
- hardcode L7 เมื่อ selector/capability หาย
- ปลด collision/fall guard หรือเพิ่ม L7 เพื่อแก้ network latency
- ใช้ repeated moveBody เป็น joystick loop โดยไม่มี queue/STOP proof
- ใช้ setBodyVelocity หรือ reflection เข้าถึง private SDK API
- จำ high speed ข้าม session/reconnect/robot switch
- แสดง m/s หรือคำรับรอง “smooth” โดยไม่มี physical calibration
- ถือ HTTP 200, MQTT publish หรือ SDK return code เป็น physical movement proof

## 13. ลำดับเริ่มงานที่แนะนำ

เมื่อผู้ใช้อนุมัติให้พัฒนา:

1. ยืนยัน source base/dirty-file boundary ตาม T0
2. Dispatch speed_contract_core, speed_apk_controller และ speed_selector_ui ตาม dependency
3. ให้ speed_independent_qa รวม T4 และหยุดที่ No-Motion Checkpoint
4. ส่งผล diff/tests/browser evidence ให้ผู้ใช้ตรวจ
5. ขออนุมัติแยกก่อน SDK feasibility หรือ field test

เอกสารนี้ไม่อนุญาตให้ส่งคำสั่งไปยังหุ่นโดยอัตโนมัติ และไม่ถือเป็น field permit

## 14. สถานะงานรอบนี้

- สร้างแผนพัฒนาจาก source, SDK sample/binary signature, log aggregate และผล audit จาก sub-agent แล้ว
- ไม่แก้ Core, LIFF หรือ Android source
- ไม่ build/deploy/install APK
- ไม่เรียก production API/MQTT
- ไม่ส่ง STOP หรือคำสั่ง motion ใด ๆ
- ไม่ควบคุม Zenbo จริง
