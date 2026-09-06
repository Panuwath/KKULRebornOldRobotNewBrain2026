# ผลทบทวนแผน Zenbo: Speed control และ PostgreSQL

วันที่: 5 กันยายน 2026 (Asia/Bangkok)

สถานะ: ปรับเอกสารวางแผน ยังไม่มี implementation, database migration, deployment หรือคำสั่งควบคุมหุ่นในรอบนี้

เอกสารนี้กำหนดลำดับงานรวมและแทนข้อความที่ขัดกันใน [แผน Speed Control เดิม](./ZENBO_NEXT_DEVELOPMENT_STEP_SPEED_CONTROL_PLAN_2026-09-04.md) ส่วนหลักฐาน log/live browser วันที่ 4 กันยายนให้อ้างเป็น snapshot เดิม ไม่ใช่การตรวจ production ใหม่วันที่ 5 กันยายน

## 1. ผลตัดสินใจ

แผนพร้อมใช้เริ่มงานพัฒนาแบบจำลองหลังแก้ประเด็นด้านล่าง การย้าย production PostgreSQL และการทดสอบหุ่นจริงยังเป็น milestone ภายหลังที่ต้องผ่านหลักฐานของตัวเอง

- ทำ L1–L7 สำหรับ bounded relative motion ก่อน; แสดงครบทุกระดับแต่เปิดเลือกตาม policy
- Legacy remote รับเฉพาะทิศทาง ให้ UI อธิบายว่าเลือก speed ผ่าน API นี้ไม่ได้
- T1–T4 รุ่นแรกใช้ relative-motion contract เท่านั้น ยกเลิกการ freeze/implement draft drive_v2 START/direction/lease ในรอบนี้
- Continuous speed เป็นงานวิจัยแยก ไม่ขวางการส่งมอบ relative L1–L7 และไม่ใช้ private API
- ย้าย PostgreSQL เป็นงานแยกจาก speed rollout เพื่อวัดผลและ rollback แต่ละส่วนได้
- API/schema/command_id ต้องตกลงร่วมกันก่อน agent แก้ Core; ใช้ repository interface เดียวเพื่อไม่เขียน persistence ซ้ำ

## 2. ข้อแก้ไขจากการทบทวน

| ประเด็น | ผลตรวจ | ข้อกำหนดใหม่ |
| --- | --- | --- |
| ACK ขัดกับ rejection | ตัวอย่างเดิม requested 5/cap 4 แต่ SDK_APPLIED | REJECTED, effective=null, SPEED_EXCEEDS_POLICY; actuator calls=0 |
| Private SDK API | javap -private ยืนยัน setBodyVelocity(float) เป็น private | ตัดออกจาก candidate; ห้าม reflection |
| เริ่ม continuous ก่อน feasibility | T2 เดิมออกแบบ START/keepalive ทั้งที่ SDK รองรับเพียง relative levels | รุ่นแรกส่ง bounded step หนึ่งครั้งต่อ explicit action ไม่มี auto-repeat |
| Policy distance สับสน | คำว่า reject distance อาจรวมระยะที่ผู้ใช้ร้องขอ | รับ requested x/y/theta แล้ว validate; reject เฉพาะการยกระดับ policy cap/timeout จาก client |
| Feature flag OFF | คำว่า publish=0 เหมารวม legacy/STOP | ปิดเฉพาะคำสั่ง speed-selectable ใหม่; test แยก legacy และ STOP |
| STOP กับ auth/database | bypass ถูกเขียนกว้างเกินไป | bypass speed/queue ได้ แต่ต้องคง target authorization; ไม่รอ audit DB commit และไม่เปิด anonymous control |
| ACK หมายถึงล้อวิ่งจริง | SDK call/return ไม่ใช่ physical feedback | แสดง “APK รับคำสั่ง/SDK รับคำสั่ง” และใช้จริงเฉพาะค่าที่มีหลักฐาน; physical onset/stop วัดแยก |
| ตัวอย่างเวลาเป็น 0 | ถ้านำไปรันจริงคือ expired command | เป็น schema placeholder เท่านั้น; Core สร้าง deadline จาก server time/permit และ APK ใช้ monotonic elapsed time สำหรับ watchdog |
| Multi-instance | PostgreSQL ไม่ย้าย state ใน RAM | ยังไม่เปิดหลาย Core replica จนจัดการ robot registry, camera queues, MQTT ownership และ session/control ownership |

Heartbeat ≤10 วินาทีเป็น proposed eligibility threshold ไม่ใช่เวลาหยุดที่ยอมรับได้ การหยุดเมื่อ connection ขาดต้องอาศัย local deadman/hard deadline ที่สั้นกว่าและผ่านการวัดจริง

## 3. PostgreSQL: สถานะที่ตรวจซ้ำ

แหล่งหลักฐานคือ working source ปัจจุบัน ไม่ใช่ deployed version:

- services/core-api/db.py:50 มี sqlite/pgsql adapter และ psycopg pool
- services/core-api/main.py:317 เขียน password session ลง SQLite แต่ main.py:242 อ่านผ่าน OIDC adapter จึงเสี่ยง login ข้าม store
- main.py ยังมี sqlite3.connect โดยตรง 50 จุด; scenario_builder.py อีก 4 จุดตาม audit ก่อนหน้า ซึ่งยังพบรูปแบบเดิมใน source รอบนี้
- main.py:1339 เริ่ม SQLite ก่อน adapter และจับ DB init error แล้วทำงานต่อ
- main.py:1923 health ตอบ ok โดยไม่ตรวจ DB
- migrations/0001_identity.sql ไม่มี web_users.provider แต่ oidc.py:418 เขียนคอลัมน์นี้
- speech_phrases.py:52 ยังมี AUTOINCREMENT ใน runtime DDL
- migrations 0000–0005 เป็นเพียง scaffold; ตาราง legacy ยังต้องย้ายครบ รวม scenario/governance

ไม่ควรตั้ง DB_CONNECTION=pgsql แล้วเปิด production ทันที ต้องรวม readers/writers ก่อน โดยเฉพาะ authentication

Local command_history.sqlite3 จำนวน 238 แถวเป็น snapshot เก่าที่ตรวจเมื่อวันที่ 4 กันยายน ไม่ใช้แทน production inventory หรือประมาณเวลาย้ายข้อมูลจริง

## 4. ลำดับพัฒนารวมที่แก้แล้ว

| งาน | ผลส่งมอบ / acceptance | Verification | Dependency / owner |
| --- | --- | --- | --- |
| R0 ล็อก baseline | ระบุ source revision พร้อม dirty diff fingerprint, version และไฟล์ที่แต่ละคนรับผิดชอบ | source inventory; ไม่ใช้ HEAD อย่างเดียวแทน working tree | เริ่มต้น / coordinator |
| R1 Contract ร่วม | relative motion, command_id, rejection และ history shape หนึ่งชุด; server เป็น policy authority | golden JSON สำหรับ valid, expired, over-cap, unauthorized STOP | R0 / Core contract |
| D1 Login/session | schema parity และ password/OIDC อ่านเขียน store เดียวผ่าน repository | SQLite และ PostgreSQL login→lookup→logout; DB unavailable | R0 / DB owner |
| D2 History | append/history pagination ผ่าน repository; รักษา IDs และ API contract | same fixtures ทั้งสอง backend; Thai/JSON/null/ordering | D1 + R1 / DB owner |
| S1 APK relative controller | หนึ่ง bounded move ต่อ action, command_id dedupe, STOP priority, hard deadline; fake actuator เท่านั้น | level 1–7, duplicate, stale, cancel, deadline; no real SDK calls | R1 / APK owner |
| S2 LIFF selector | L1–L7 เห็นครบ default L1; selection ไม่ส่ง network; remote speed disabled | mock browser ทุก viewport ตามแผนเดิม; keyboard; cap/stale states | R1 / LIFF owner |
| S3 Offline integration | UI→Core→fake actuator ใช้ contract เดียว; requested ตรง mapped level หรือ reject | golden fixtures + delayed ACK + stale command + DB failure | D2 + S1 + S2 / verifier |
| D3 Scenario/playlist | migration+repository+API parity ทีละกลุ่ม | idempotent run/create, definition CRUD, playlist ordering | D2 / DB owner |
| D4 Route/governance | transactions/constraints รักษา reservation และ permit invariants | concurrent reservation, conditional transitions, revoke/recovery | D3 / DB owner |
| D5 Migration rehearsal | snapshot→copy→verify→restore บน isolated PG; rerun ไม่ซ้ำ | PK/checksum/constraints/sequences; restore drill | D4 / migration owner |
| S4 SDK relative integration | public moveBody(level) + runtime safety coverage + hard stop; flag ปิดค่าเริ่มต้น | compile/mock adapter; readiness evidence | S3 / APK owner |
| D6 DB cutover | maintenance freeze, final copy, verify, switch, smoke, reopen | target fingerprint + backup + parity + rollback decision | D5 / deploy owner |
| S5 Physical calibration | exact installed APK, operator, sensor readiness; ทดสอบทีละระดับ | onset/stop distance/latency และ attestation | S4 และระบบ backend เสถียร / field operator |

D3 แยก scenario กับ playlist เป็นงานย่อย; D4 แยก route, reservation/permit และ recovery/attestation แต่ละงานควรแตะไม่เกินประมาณ 5 ไฟล์และมี migration+repository+test ของตัวเอง

S5 ไม่จำเป็นต้องรอ D6 หาก backend SQLite ที่ผ่าน regression ยังเป็น release target ที่ตกลงไว้ แต่ห้ามสลับ DB ระหว่างเก็บ baseline กับวัดหลังปรับ APK

## 5. ขอบเขตไฟล์และ agent รอบพัฒนา

| Owner | ไฟล์หลักที่คาดว่าจะรับผิดชอบ | การส่งต่องาน |
| --- | --- | --- |
| DB foundation | services/core-api/db.py, migrations/*.sql, tests และ repository ใหม่ | D1 แล้ว D2; ห้ามแก้ migration ที่เคย apply แล้ว ให้เพิ่มไฟล์ใหม่ |
| Core contract | services/core-api/main.py, contract tests | R1 ก่อน; DB owner แก้ main.py หลัง handoff เท่านั้น |
| APK | model/InteractCommand.java, controller ใหม่, robot/ZenboSdkBridge.java, service/ZenboClientService.java, tests | S1 fake ก่อน S4 SDK; แยก commit |
| LIFF | shared component/tests, index.html, control/index.html, teleop/index.html | S2 กับ mock transport |
| Migration/release | scripts migration ใหม่, docker-compose.yml, deploy.sh และ runbook | D5 ก่อน D6; ไม่ใช้ credentials ในเอกสาร |
| Verification | contract fixtures, backend integration tests, browser evidence | ตรวจหลังแต่ละ slice; ไม่อ้าง PASS ก่อนมีผลรันจริง |

ตารางนี้เป็นการแบ่งงานสำหรับรอบพัฒนา ไม่มีการเรียก sub-agent พัฒนาเพิ่มเติมในรอบทบทวนนี้

## 6. วิธีตรวจ PostgreSQL และการรักษาข้อมูล

1. Inventory source/target จริง: ตาราง, schema version, row counts, active writers และ target ที่มีข้อมูลเดิม หาก target ไม่ว่างต้องกำหนด conflict policy ก่อน copy
2. ใช้ schema migrations แบบเพิ่มต่อท้าย; INTEGER milliseconds → BIGINT, ID → identity/sequence, lastrowid → RETURNING, INSERT OR IGNORE → ON CONFLICT, NOCASE → ordering ที่กำหนดและทดสอบชัด
3. เปลี่ยน JSON text → JSONB เฉพาะเมื่อ serializer/reader รองรับ dict/list แล้ว; ห้าม json.loads ซ้ำกับค่าที่ driver decode ให้ ข้อมูล JSON เสียต้องรายงานและหยุด ไม่ทิ้งเงียบ
4. Normalize boolean และ null; preserve PK, foreign-key relationships และ reset sequence หลัง import IDs
5. Atomic upsert/unique constraints ป้องกัน duplicate idempotency และ lost updates; Python process lock ใช้แทน DB transaction ข้าม replica ไม่ได้
6. สำรอง SQLite ด้วย consistent snapshot รวมสถานะ WAL อย่างถูกต้อง และสำรอง target ก่อนเปลี่ยนข้อมูล ทดสอบ restore ก่อน cutover; source tar จาก deploy.sh ไม่ใช่ DB backup
7. Rehearsal ในฐานแยก: copy ด้วย explicit columns แล้วตรวจ count, PK set, canonical checksum, invalid JSON, unique/FK violations และ sequence next ID ทุกตาราง
8. Cutover: หยุด writers ทั้ง HTTP jobs และ MQTT telemetry persistence → snapshot สุดท้าย → copy/verify → เปลี่ยน backend → smoke แบบไม่มี motion → เปิด writes
9. ก่อนเปิด PG writes rollback กลับ SQLite snapshot ได้; หลังเปิด writes ต้อง freeze และ reconcile delta รวม update/delete กลับก่อน ห้ามสลับ env กลับแล้วสูญเสียข้อมูลใหม่

Session ที่ย้ายต้องรักษา expiry/role/disabled semantics; กำหนดว่าจะ invalidate sessions หรือย้าย valid sessions ใน cutover runbook และทดสอบผลของทางที่เลือก

ไม่รวม n8n_data/database.sqlite ใน Core migration; broker persistence และ SDK sample assets ไม่อยู่ในขอบเขตนี้

## 7. DB outage และคำสั่งหุ่น

แยก liveness ออกจาก readiness: process ยังมีชีวิตไม่แปลว่า database พร้อม การทำงานที่ต้องอ่าน auth/permit ต้อง fail closed เมื่อข้อมูลไม่พร้อม ห้าม fallback ไป SQLite อัตโนมัติจนเกิดสองแหล่งข้อมูลจริง

STOP ต้องมีเส้นทางที่รักษา authorization ของ target และไม่รอการบันทึก audit สำเร็จ ใช้ local deadman ของ APK เป็น backstop การออกแบบ degraded STOP ต้องทำและทดสอบก่อนเปิดใช้งาน; ห้ามปิด auth เพื่อให้ STOP ผ่าน

กรณี publish สำเร็จแต่ DB write ล้มเหลว ต้องรายงาน dispatch กับ audit แยกกันและ retry ด้วย command_id เดิม ห้าม UI retry ด้วย ID ใหม่จนหุ่น execute ซ้ำ หากเพิ่ม durable outbox ต้องมี TTL/dedupe และห้าม replay motion ที่หมดอายุหลัง reconnect

กำหนด pool limits, connection/query timeout และ shutdown ให้ชัด; synchronous PG query ใน async endpoint ยัง block event loop ได้ การย้าย engine อย่างเดียวไม่พิสูจน์ว่าระบบเร็วขึ้น

## 8. เกณฑ์วัดและสถานะหลักฐาน

- UI: ทุกระดับมองเห็น, tap target/focus/disabled reason ใช้ได้; เลือก speed แล้ว network writes=0
- Control: แยก tap→Core, Core→APK, SDK submission และ physical onset; เก็บ command_id เดียวกัน
- Database: query latency p50/p95/p99, pool wait, error rate และ history response ภายใต้ workload เดียวกันก่อน/หลัง
- STOP: วัด physical stop และระยะหยุดแยกตาม level/direction; ค่า p95 ≤300 ms จากแผนเดิมเป็นเป้าหมายเสนอ ยังไม่มีผลพิสูจน์
- การทดลอง 3 รอบต่อระดับใช้ smoke/feasibility ได้ แต่ยังน้อยเกินกว่าจะสรุป p95 ที่น่าเชื่อถือ; calibration ต้องออกแบบจำนวนตัวอย่างเพิ่มและรายงาน n, max, failures ทุกระดับ
- ระยะ 0.15 m อาจไม่พอให้ถึง steady speed โดยเฉพาะ L6/L7 จึงไม่แปลงเป็น rated m/s; กำหนดระยะหมุนและ timeout แยกจากระยะทางล้อก่อน field test

รอบนี้ตรวจ source และ SDK signatures พร้อมแก้ Markdown เท่านั้น ไม่มี PostgreSQL integration test หรือ physical test ใหม่ ผลทบทวนหมายถึงความครบถ้วนของแผน ไม่ใช่การรับรองว่าระบบพัฒนาหรือ deploy สำเร็จแล้ว
