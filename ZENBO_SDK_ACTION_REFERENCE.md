# Zenbo Junior SDK — Action & Control Reference

เอกสารนี้เป็นบัญชีฟังก์ชันควบคุม Zenbo ที่ถอดจาก `ZenboJuniorSDK.jar` ในชุด
`ZenboJuniorSDK_and_SampleCode_v2.1.22.2239` และเทียบกับ bridge ในโปรเจกต์นี้
ณ วันที่ 2026-08-30

## ขอบเขตและหลักฐาน

- Source of truth: `ZenboJuniorSDK_and_SampleCode_v2.1.22.2239/ZenboSDK/ZenboJuniorSDK.jar`
- SHA-256: `1f3315123a72f63f4d4b2621c8297c904a3249ecd12fc4bf0cafdc92ac93a955`
  (ตรงกับ `zenbo-client-android/app/libs/ZenboSDK.jar`)
- ตรวจ surface ด้วย `javap -public` ของ SDK ไม่ได้อ้างชื่อ action จากการคาดเดา
- `RobotAPI` เปิดโมดูล `robot`, `motion`, `utility`, `wheelLights`, `vision`,
  `lineFollower`, และ `iot`
- ทุกคำสั่งส่วนใหญ่คืนค่า `int` เป็น **command serial**; จบงานจริงต้องรอ
  `RobotCallback.onStateChange(..., state)` และตรวจ error ใน callback
- หน่วยมุมของ `motion.moveHead` ใน SDK เป็น radians; bridge ปัจจุบันรับองศา
  แล้วแปลงด้วย `Math.toRadians()`

## ลำดับการใช้งานที่ปลอดภัย

```java
RobotAPI api = new RobotAPI(context, new RobotCallback() {
    @Override public void initComplete() { /* พร้อมรับคำสั่ง */ }
    @Override public void onStateChange(
        int command, int serial, RobotErrorCode error, RobotCmdState state) {
        // SUCCESS / ACTIVE / FAILED/CANCELLED ต้องใช้ state จริงจาก SDK
    }
});
```

1. รอ `initComplete()` ก่อนสั่งงาน
2. เก็บ serial ที่คืนจากคำสั่ง หากต้องยกเลิกเฉพาะงานให้ใช้
   `cancelCommandBySerial(serial)`
3. อย่าสั่ง motion ซ้อนกัน; รอ callback ก่อนคำสั่งฐาน/คอถัดไป
4. ก่อนเคลื่อนที่จริงต้องมีกลไกป้องกันสิ่งกีดขวาง/ขอบตกและปุ่ม stop
5. เรียก `release()` เมื่อ service/activity ปิด

## 1. RobotAPI lifecycle และ command queue

| ฟังก์ชัน | หน้าที่ |
| --- | --- |
| `new RobotAPI(Context\|Service\|Activity[, RobotCallback])` | สร้าง session กับ RobotAPI |
| `setCallback(RobotCallback)` | เปลี่ยน callback หลังสร้าง |
| `release()` | ปล่อย resource ของ RobotAPI |
| `getVersion()` / `queryPluginVersion()` | อ่านเวอร์ชัน framework/plugin |
| `cancelCommand(int\|RobotCommand)` | ยกเลิก command ตามรหัส |
| `cancelCommandAll()` | ยกเลิกทุกคำสั่งที่ค้าง — ใช้เป็น emergency control |
| `cancelCommandBySerial(int)` | ยกเลิกเฉพาะคำสั่ง serial ที่ทราบ |
| `setLoggingEnabled`, `isLoggingEnabled`, `isLoggable` | ควบคุม log เพื่อ debug |

## 2. Dialog, หน้า และการพูด (`api.robot`)

### สีหน้า

ใช้ `setExpression(RobotFace)`, `setExpression(RobotFace, String)`, หรือ
`setExpression(RobotFace, String, ExpressionConfig)`

ค่า `RobotFace` ใน JAR:

```text
HIDEFACE, PREVIOUS, OTHER_USE, INTERESTED, DOUBTING, PROUD, DEFAULT, HAPPY,
EXPECTING, SHOCKED, QUESTIONING, IMPATIENT, CONFIDENT, ACTIVE, PLEASED,
HELPLESS, SERIOUS, WORRIED, PRETENDING, LAZY, AWARE_RIGHT, TIRED, SHY,
INNOCENT, SINGING, AWARE_LEFT, DEFAULT_STILL,
EXPECTING_ADV, IMPATIENT_ADV, PLEASED_ADV, SHOCKED_ADV, TIRED_ADV,
DEFAULT_ADV, WORRIED_ADV, QUESTIONING_ADV, PRETENDING_ADV, INTERESTED_ADV,
SHY_ADV, CONFIDENT_ADV, HAPPY_ADV, LAZY_ADV, ACTIVE_ADV, SINGING_ADV,
DOUBTING_ADV, AWARE_RIGHT_ADV, AWARE_LEFT_ADV, HELPLESS_ADV, SERIOUS_ADV,
INNOCENT_ADV, PROUD_ADV
```

Bridge รับ alias เพิ่มเติม: `DOUBT→DOUBTING`, `EXPECT→EXPECTING`,
`SHOCK→SHOCKED`, `INTEREST→INTERESTED`.

### Speech / ASR / dialog plan

| ฟังก์ชัน | หน้าที่ |
| --- | --- |
| `speak(String)` / `speak(String, SpeakConfig)` / `speak(String, int)` | TTS ในตัว Zenbo |
| `stopSpeak()` | หยุด TTS ในตัว |
| `speakAndListen(String, SpeakConfig\|float\|float,int)` | พูดแล้วเข้าสู่การฟัง |
| `stopSpeakAndListen()` | หยุด flow พูด/ฟัง |
| `registerListenCallback` / `unregisterListenCallback` | รับผลการฟัง |
| `setListenContext`, `setBackgroundContext`, `clearAppContext`, `clearBackgroundContext` | กำหนด/ล้างบริบท dialog |
| `jumpToPlan(plan, state[, force])` | กระโดดไป dialog plan ของ Zenbo |
| `dynamicEditInstance(...)`, `updateDialogCorpusByServer(...)` | ปรับ dialog corpus/dynamic instance |
| `setVoiceTrigger`, `setKeyTrigger`, `setPressOnHeadAction`, `setTouchOnlySignal` | เปิด/ปิด trigger การโต้ตอบ |
| `resetVoiceTrigger`, `resetVoiceTriggerToDefault` | รีเซ็ต voice trigger |
| `resetListenTimeoutCounter`, `configNextCsr` | ควบคุม timeout/CSR รอบถัดไป |
| `startListenAnimation`, `stopListenAnimation`, `startFaceSpeakAnimation`, `stopFaceSpeakAnimation` | animation ระหว่างฟัง/พูด |
| `queryExpressionStatus()` | สอบถามสถานะ expression |
| `requestUtteranceCollisionCheck`, `queryWordSimilarity` | ตรวจข้อความชน/คล้ายกัน |
| `enToNumber`, `zhToNumber` | แปลงเลข EN/ZH (ไม่ใช่ Thai TTS) |
| `startVoiceEnrollProgress`, `deleteVoiceEnrollData`, `requestVoiceEnrollList` | ลงทะเบียน/จัดการเสียงผู้ใช้ |

> แอปนี้เล่น WAV จาก Thai TTS server เป็นเส้นทางหลัก; `robot.speak` เป็น
> fallback เฉพาะเมื่อระบบเลือกใช้ TTS ในตัว Zenbo เท่านั้น

## 3. Motion (`api.motion`)

| ฟังก์ชัน | พารามิเตอร์/ข้อควรระวัง |
| --- | --- |
| `moveBody(float x, float y, float theta)` | เคลื่อนฐาน; overload มี `int` หรือ `SpeedLevel.Body` |
| `moveHead(float yaw, float pitch, SpeedLevel.Head)` | คอเป็น radians; overload `int,int` มีใน SDK |
| `stopMoving()` | หยุด motion ของฐาน |
| `remoteControlBody(Direction.Body)` | ควบคุมฐานแบบต่อเนื่อง; ต้องส่ง `STOP` เสมอ |
| `remoteControlHead(Direction.Head)` | ควบคุมคอแบบต่อเนื่อง; ต้องส่ง `STOP` เสมอ |
| `setAvoidanceStatus(boolean)` / `getAvoidanceStatus()` | เปิด/อ่าน avoidance; ห้ามปิดในพื้นที่คนโดยไม่มี safety case |

Bridge ปัจจุบันเปิดใช้ `moveBody`, `moveHead`, `remoteControlBody`,
`remoteControlHead`, `stopMoving`/cancel ผ่าน MQTT แล้ว

## 4. Utility และ canned/emotional action (`api.utility`)

| ฟังก์ชัน | หน้าที่ |
| --- | --- |
| `playAction(int actionId)` | เล่น canned action ตามเลข action |
| `playEmotionalAction(RobotFace, int[, float])` | เล่น action พร้อมสีหน้าเดียว |
| `playEmotionalAction(List<RobotUtil.faceItem>, int[, float])` | sequence สีหน้าพร้อม action |
| `lookAtUser(float distance)` | หันหา user ในระยะที่ระบุ |
| `trackFace(boolean enable, boolean track)` | เริ่ม/หยุด tracking face |
| `followFace(boolean enable, boolean track)` | เริ่ม/หยุด follow face |
| `followObject()` | เริ่ม follow object ตาม SDK |
| `setScreenBlueLightFilterMode(String)` / `get...` / `get...Enable()` | ควบคุม blue-light filter ของจอ |
| `sendInfo(int, Bundle)` | ส่งข้อมูลไป utility/service ของระบบ |

### บัญชี Action ID ของ Zenbo SDK (Official Constant Pool)

ถอดรหัสจากคลาส `com.asus.robotframework.API.Utility$PlayAction` ใน `ZenboJuniorSDK.jar` (SHA-256: `1f3315123a72f63f4d4b2621c8297c904a3249ecd12fc4bf0cafdc92ac93a955`):

| Action ID | Constant Name | หมวดหมู่ | คำอธิบายท่าทาง |
| :---: | :--- | :--- | :--- |
| **0** | `Default_1` | ท่าตั้งต้น | คืนท่าเริ่มต้น 1 |
| **1** | `Default_2` | ท่าตั้งต้น | คืนท่าเริ่มต้น 2 |
| **2** | `Nod_1` | พยักหน้า | พยักหน้าตอบรับ 1 ครั้ง |
| **3** | `Head_up_1` | เงยหน้า | เงยหน้ามองขึ้น 1 |
| **4** | `Head_up_2` | เงยหน้า | เงยหน้ามองขึ้น 2 |
| **5** | `Shake_head_1` | ส่ายหน้า | ส่ายหน้าปฏิเสธ 1 (เบา) |
| **6** | `Head_up_3` | เงยหน้า | เงยหน้ามองสูง 3 |
| **7** | `Head_up_4` | เงยหน้า | เงยหน้าเร็ว 4 |
| **8** | `Head_down_1` | ก้มหน้า | ก้มหน้าลง 1 (ต่ำ) |
| **9** | `Head_down_2` | ก้มหน้า | ก้มหน้าลง 2 |
| **10** | `Head_down_3` | ก้มหน้า | ก้มหน้าลง 3 |
| **11** | `Shake_head_2` | ส่ายหน้า | ส่ายหน้าปฏิเสธ 2 (ชัดเจน) |
| **12** | `Head_down_4` | ก้มหน้า | ก้มหน้าระดับ 4 |
| **13** | `Head_up_5` | เงยหน้า | เงยหน้าระดับ 5 |
| **14** | `Head_down_5` | ก้มหน้า | ก้มหน้าระดับ 5 |
| **15** | `Dance_b_1_loop` | เต้น/ดนตรี | เต้นเร็ว B1 วนลูป |
| **16** | `Head_up_7` | เงยหน้า | เงยหน้ามองฟ้า 7 |
| **17** | `Music_1_loop` | เต้น/ดนตรี | โยกตามดนตรี 1 วนลูป |
| **18** | `Turn_left_1` | หันตัว | หันฐานไปซ้าย 1 |
| **19** | `Turn_left_2` | หันตัว | หันฐานไปซ้าย 2 |
| **20** | `Shake_head_3` | ส่ายหน้า | ส่ายหน้า 3 |
| **21** | `Dance_s_1_loop` | เต้น/ดนตรี | เต้นช้า S1 วนลูป |
| **22** | `Body_twist_1` | เต้น/ดนตรี | บิดตัวส่ายเอว 1 |
| **23** | `Body_twist_2` | เต้น/ดนตรี | บิดตัวส่ายเอว 2 |
| **24** | `Dance_2_loop` | เต้น/ดนตรี | เต้นแบบ 2 วนลูป |
| **25** | `Shake_head_4_loop` | ส่ายหน้า | ส่ายหน้าต่อเนื่อง วนลูป |
| **26** | `Head_twist_1_loop` | เอียงคอ | เอียงคอสงสัย วนลูป |
| **27** | `Dance_3_loop` | เต้น/ดนตรี | เต้นแบบ 3 วนลูป |
| **28** | `Shake_head_5` | ส่ายหน้า | ส่ายหน้าเร็ว 5 |
| **42** | `Shake_head_6` | ส่ายหน้า | ส่ายหน้าช้า 6 |
| **43** | `Head_down_7` | ก้มหน้า | ก้มหน้ามองพื้น 7 |
| **44** | `Turn_right_1` | หันตัว | หันฐานไปขวา 1 |
| **45** | `Turn_right_2` | หันตัว | หันฐานไปขวา 2 |
| **46** | `Turn_left_reverse_1` | หันตัว | หันซ้ายคืนกลับ 1 |
| **47** | `Turn_right_reverse_1` | หันตัว | หันขวาคืนกลับ 1 |
| **48** | `Turn_left_reverse_2` | หันตัว | หันซ้ายคืนกลับ 2 |
| **49** | `Turn_right_reverse_2` | หันตัว | หันขวาคืนกลับ 2 |
| **54** | `Head_up_6` | เงยหน้า | เงยหน้าระดับ 6 |
| **1007** | `Find_face` | ตรวจจับ | หมุนหัวสแกนหาใบหน้าผู้ใช้ |

## 5. Wheel LEDs (`api.wheelLights`)

ทุก pattern เลือก `WheelLights.Lights`, และหลายรายการรับ `Speed`/`Direction`.
ตั้งสีก่อนด้วย `setColor(Lights, mask, rgb)` และปิดด้วย `turnOff(Lights, mask)`.

```text
startStatic                 startStrobing              startBreath
startColorCycle             startRainbow               startBreathRainbow
startComet                  startRainbowComet          startMovingFlash
startFlashDash              startRainbowWave           startGlowingYoYo
startStarryNight            startWave                  turnOff
```

Bridge MQTT รองรับ mode เหล่านี้: `static`, `strobing`, `breath`, `color_cycle`,
`rainbow`, `breath_rainbow`, `comet`, `rainbow_comet`, `moving_flash`,
`flash_dash`, `rainbow_wave`, `glowing_yoyo`, `starry_night`, `wave`, `off`.

## 6. Vision และ enrollment (`api.vision`)

| ฟังก์ชัน | ผลลัพธ์ callback / หมายเหตุ |
| --- | --- |
| `requestDetectFace(FaceDetectConfig)` | `onDetectFaceResult` |
| `cancelDetectFace()` | ยกเลิก face detection |
| `requestDetectPerson(float\|int\|PersonDetectConfig)` | `onDetectPersonResult` |
| `cancelDetectPerson()` | ยกเลิก person detection |
| `requestGesturePoint(float\|int[, trackId])` | `onGesturePoint` |
| `requestMeasureHeight(float\|int)` | ผลผ่าน `onResult` |
| `requestRecognizePerson(float\|int\|PersonRecognizeConfig)` | `onRecognizePersonResult` |
| `cancelRecognizePerson()` | ยกเลิก recognition |
| `setConfig(VisionControl.Config)` | ตั้งค่า vision control |
| `startFaceEnrollProgress`, `startPictureEnrollProgress` | ลงทะเบียน person/face |
| `deleteFaceEnrollData`, `requestFaceEnrollList` | จัดการข้อมูล enrollment |

Bridge ปัจจุบันเปิด MQTT สำหรับ detect face/person, gesture point, recognize
person, measure height และ cancel ของ face/person/recognize. ผล vision ส่งกลับ
topic `.../status/vision`.

## 7. Line follower (`api.lineFollower`)

```text
calibrate([boolean])                getColor()
lineFollower([SpeedLevel|String])   followLine([SpeedLevel|String])
updateConfig(int, String)           setBehavior(int, Behavior, Object...)
demo()
```

ยังไม่เปิดเป็น MQTT command ใน bridge. ต้อง calibrate และทดสอบเส้น/พื้นจริงก่อน
นำเข้าการควบคุมระยะไกล เพราะเป็น physical motion

## 8. IoT / Smart Bulb (`api.iot`)

```text
login, logout, initBindingProcess, bindDevice, stopBindDevice, queryBindState,
unbindDevice, renameDevice, getDeviceList, getDeviceInfo,
registerDeviceListener, unregisterDeviceListener,
setSmartBulbSwitch, setSmartBulbMode, setSmartBulbBrightness,
setSmartBulbColor, setSmartBulbColorTemperature
```

ยังไม่เปิดเป็น MQTT command ใน bridge เพราะต้องมีบัญชี/device binding และสิทธิ์
ของ IoT แยกต่างหาก

## 9. Callbacks ที่ต้องรองรับ

| Callback | ใช้กับ |
| --- | --- |
| `initComplete()` | พร้อมใช้งาน RobotAPI |
| `onStateChange(cmd, serial, error, state)` | lifecycle ของทุก command |
| `onResult(cmd, serial, error, Bundle)` | ผลแบบ Bundle/ข้อผิดพลาด |
| `onDetectFaceResult`, `onDetectPersonResult` | face/person detection |
| `onRecognizePersonResult` | person recognition |
| `onGesturePoint` | pointing vector/3D point |
| `onEnrollUpdate`, `onEnrollGetAllIDList` | enrollment |
| `onFaceResult`, `onTrackingResult` | ผล face/tracking ระดับ SDK |

## 10. สถานะของ bridge ปัจจุบัน

| หมวด | MQTT bridge รองรับแล้ว | ยังไม่เปิด |
| --- | --- | --- |
| Speech/audio | Thai TTS WAV, `robot.speak`, stop | dialog plan/ASR callback |
| Face | set expression, emotional sequence | expression config/status |
| Motion | body, head, remote body/head, halt | avoidance policy control |
| Utility | canned action, look/track/follow face/object | blue light, sendInfo |
| LEDs | 15 pattern + off | SDK-specific mask tuning |
| Vision | face/person/gesture/recognize/height + cancel | enrollment/config UI |
| Line/IoT | — | ทุกฟังก์ชัน ต้องมี safety/auth design ก่อน |

## 11. Test matrix ก่อนเปิด action เพิ่ม

1. ยืนยัน `initComplete` และ command serial จากเครื่องจริง
2. ทดสอบหนึ่ง action ต่อครั้งพร้อม callback `SUCCESS`/error
3. Motion: พื้นโล่ง, observer, HALT พร้อมใช้งาน, ระยะ/ความเร็วต่ำก่อน
4. Vision: ตรวจ permission กล้องและคืนผล callback จริง
5. LED/face: ยืนยันชื่อ enum และ pattern ตาม firmware เครื่องนั้น
6. บันทึก firmware, SDK version, action ID, payload, callback และผล physical
