# ADR-T5: Continuous-Speed Feasibility

## Status
**Accepted** — 2026-09-06

## Context
T5 ต้องตอบว่า Zenbo Junior SDK มี public API ที่ปลอดภัยสำหรับ continuous-speed control หรือไม่ โดยเฉพาะ:
1. มี public API สำหรับ continuous speed หรือไม่; `setBodyVelocity(float)` เป้น private API ต้องห้ามใช้/reflection
2. มี callback/telemetry พิสูจน์ applied velocity ได้หรือไม่
3. `moveBody` แบบ bounded เหมาะกับการกดค้างหรือต้องสร้าง queue/watchdog/stutter
4. ถ้าไม่ปลอดภัย ควรเก็บ remote แบบ SDK-managed/non-selectable และใช้ L1–L7 เฉพาะ relative mode หรือไม่

## Evidence
อ้างอิงจาก official sample code ใน `ZenboJuniorSDK_and_SampleCode_v2.1.22.2239/`:

1. **Bounded `moveBody` with speed level** — `RobotDevSample/MotionMoveBodyHead.java`
   - `robotAPI.motion.moveBody(x, y, theta)` — ไม่มี speed level
   - `robotAPI.motion.moveBody(x, y, theta, MotionControl.SpeedLevel.Body.getBody(selectedLevel))` — ใช้ `L1..L7` ได้
   - มี `L1..L7` สำหรับ body และ `L1..L3` สำหรับ head (spinner array)
   - `robotAPI.motion.stopMoving()` เป้น public API สำหรับหยุด

2. **Legacy remote control** — `RobotDevSample/MotionRemoteControlBodyHead.java`
   - `robotAPI.motion.remoteControlBody(Direction.Body.FORWARD)`
   - `remoteControlBody` ไม่มีพารามิเตอร์ speed level
   - การเคลื่อนที่จะดำเนินต่อไปจนกว่าจะเรียก `remoteControlBody(Direction.Body.STOP)`

3. **Project bridge implementation** — `zenbo-client-android/.../ZenboSdkBridge.java`
   - `mRobotAPI.motion.moveBody(x, y, theta, MotionControl.SpeedLevel.Body.getBody(speedLevel))` เป้นวิธีที implement อยู่แล้ว
   - `remoteControlBody` ยังไม่ถูก wrap ด้วย speed level

4. **Telemetry / callbacks**
   - `RobotCallback.onStateChange` และ `onResult` ส่ง `RobotCmdState` และ `RobotErrorCode`
   - ไม่มี callback สำหรับ velocity หรือ odometry ใน sample
   - ไม่มี `setBodyVelocity` หรือ API คล้ายกันใน sample หรือ bridge

## Decision
1. **ไม่พัฒนา continuous-speed selection สำหรับ legacy remote** — `remoteControlBody` ไม่รองรับ speed level และไม่มี telemetry สำหรับตรวจสอบความเร็วจริง การทำ loop ซ้ำ `moveBody` จะสร้าง queue/stutter และไม่มีหลักฐานว่าหุ่นจะหยุดตาม deadman ทันที
2. **เก็บ remote mode ไว้แบบ SDK-managed / non-selectable** — แสดงข้อความ "SDK จัดการทิศทางเอง ไม่สามารถเลือกความเร็วได้" ตามที่ `zenbo-drive-control.js` implement ไว้
3. **ใช้ L1–L7 เฉพาะ bounded relative `moveBody`** — ทางที่ `SdkDriveActuator` / `SpeedLevelDriveController` ทดสอบไว้แล้วด้วย `FakeDriveActuator`
4. **T6 SDK adapter จะยังคงใช้ `moveBody(x, y, theta, level)` ต่อไป** — ไม่ใช้ `setBodyVelocity` หรือ reflection
5. **การตรวจ physical L1–L7 (S5) จำเป้นต้องผ่านก่อนเปิด feature flag OFF → ON**

## Consequences
- **Pros**:
  - ไม่ใช้ private API, reflection, หรือ repeated `moveBody` loop
  - รักษา safety/deadman ของ `SpeedLevelDriveController` ไว้
  - legacy remote ไม่เปลี่ยนแปลงเมื่อ feature flag OFF
  - ใช้ public API ทีมีอยู่ (`moveBody` with `SpeedLevel.Body`)
- **Cons**:
  - ไม่สามารถเลือกระดับความเร็วระหว่าง remote continuous
  - continuous-jog ต้องพึ่งระบบกดค้าง + STOP ของ SDK (ไม่มี TTS / project evidence จนกว่าจะทดสอบฟิสิกส์)

## Rollback
หาก T8/T9 หรือ S5 พบว่า `moveBody(level)` ไม่ปลอดภัย:
- ปิด feature flag `RELATIVE_MOTION_ENABLED`
- คง `remoteControlBody` direction-only path
- ถอยกลับไป R0 baseline `a44b6ea` หรือ `docs/BASELINE_2026-09-05.json`

## References
- `ZenboJuniorSDK_and_SampleCode_v2.1.22.2239/RobotDevSample/src/main/java/com/asus/robotdevsample/MotionMoveBodyHead.java`
- `ZenboJuniorSDK_and_SampleCode_v2.1.22.2239/RobotDevSample/src/main/java/com/asus/robotdevsample/MotionRemoteControlBodyHead.java`
- `zenbo-client-android/app/src/main/java/com/hackathon/zenboclient/robot/ZenboSdkBridge.java`
- `zenbo-client-android/app/src/main/java/com/hackathon/zenboclient/drive/SdkDriveActuator.java`
- `docs/ZENBO_NEXT_DEVELOPMENT_STEP_SPEED_CONTROL_PLAN_2026-09-04.md` (T5)
