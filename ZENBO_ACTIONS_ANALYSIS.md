# การวิเคราะห์ระบบ Action และท่าทางของหุ่นยนต์ ASUS Zenbo (Zenbo SDK)

เอกสารนี้รวบรวมและวิเคราะห์โครงสร้าง ระบบการเคลื่อนไหว ท่าทางสำเร็จรูป (Canned Actions) การแสดงออกทางสีหน้า (Facial Expressions) และระบบไฟ LED ทั้งหมดของหุ่นยนต์ ASUS Zenbo สำหรับใช้อ้างอิงและพัฒนาในโปรเจกต์ Hackathon

---

## 1. ผังโครงสร้างท่าทางและระบบขับเคลื่อน (Action Architecture)

```
                       ┌──────────────────────────────────────────┐
                       │           Zenbo Action System            │
                       └────────────────────┬─────────────────────┘
                                            │
        ┌───────────────────┬───────────────┴───────────────┬───────────────────┐
        ▼                   ▼                               ▼                   ▼
┌───────────────┐   ┌───────────────┐               ┌───────────────┐   ┌───────────────┐
│ 1. Low-Level  │   │ 2. Canned     │               │ 3. Facial     │   │ 4. Light/LED  │
│    Motions    │   │    Actions    │               │  Expressions  │   │  Animations   │
└───────┬───────┘   └───────┬───────┘               └───────┬───────┘   └───────┬───────┘
        │                   │                               │                   │
        │                   └───────────────┬───────────────┘                   │
        │                                   ▼                                   │
        │                       ┌───────────────────────┐                       │
        │                       │ 5. Emotional Actions  │                       │
        │                       │ (Action + Expression) │                       │
        │                       └───────────────────────┘                       │
        └───────────────────────────────────┬───────────────────────────────────┘
                                            ▼
                                ┌───────────────────────┐
                                │   Robot Callback &    │
                                │    Command Serial     │
                                └───────────────────────┘
```

---

## 2. เจาะลึก Action แต่ละหมวดหมู่

### หมวดที่ 1: Low-Level Motions (การควบคุมพิกัดและมอเตอร์โดยตรง)

ใช้สำหรับการสั่งเคลื่อนที่แบบกำหนดระยะ ทิศทาง และมุมหันอย่างแม่นยำ

#### 1.1 การเคลื่อนที่ส่วนฐาน (`robotAPI.motion.moveBody`)
* **API Signature**: `robotAPI.motion.moveBody(float x, float y, float theta, SpeedLevel.Body level)`
* **พารามิเตอร์**:
  * `x`: เคลื่อนที่ไปข้างหน้า (+) หรือถอยหลัง (-) หน่วยเป็นเมตร (meters)
  * `y`: เคลื่อนที่ไปทางซ้าย (+) หรือทางขวา (-) หน่วยเป็นเมตร (meters)
  * `theta`: มุมหมุนตัวรอบแกนแนวตั้ง หน่วยเป็นองศาหรือเรเดียน (degrees/radians)
  * `level`: ระดับความเร็ว (`MotionControl.SpeedLevel.Body.L1` ถึง `L5`)
* **ตัวอย่างโค้ด**:
  ```java
  // เดินหน้า 0.5 เมตร พร้อมหมุนตัว 90 องศา ด้วยความเร็วระดับ 2
  robotAPI.motion.moveBody(0.5f, 0.0f, 90.0f, MotionControl.SpeedLevel.Body.L2);
  ```

#### 1.2 การเคลื่อนไหวส่วนศีรษะ/คอ (`robotAPI.motion.moveHead`)
* **API Signature**: `robotAPI.motion.moveHead(float yaw, float pitch, SpeedLevel.Head level)`
* **พารามิเตอร์**:
  * `yaw`: หันซ้าย (+) หรือขวา (-) ช่วงมุมประมาณ -45° ถึง +45° (แปลงเป็น radians)
  * `pitch`: ก้ม (-) หรือเงย (+) ช่วงมุมประมาณ -15° ถึง +55° (แปลงเป็น radians)
  * `level`: ระดับความเร็วการหัน (`MotionControl.SpeedLevel.Head.L1` ถึง `L5`)
* **ตัวอย่างโค้ด**:
  ```java
  float yaw = (float) Math.toRadians(30);   // หันขวา 30 องศา
  float pitch = (float) Math.toRadians(20); // เงยหน้า 20 องศา
  robotAPI.motion.moveHead(yaw, pitch, MotionControl.SpeedLevel.Head.L2);
  ```

#### 1.3 การหยุดการเคลื่อนที่ฉุกเฉิน (`robotAPI.motion.stopMoving`)
* **ตัวอย่างโค้ด**:
  ```java
  robotAPI.motion.stopMoving();
  ```

---

### หมวดที่ 2: Canned Actions (ท่าทางสำเร็จรูป Animation/Body Movement)

เป็นท่าทางคอมโบที่ Firmware โปรแกรมการขยับคอ ล้อ และการหมุนตัวไว้ล่วงหน้า

* **API Signature**: `robotAPI.utility.playAction(int actionId)`
* **การทำงาน**: ส่งรหัสตัวเลข (Integer ID) เช่น `#22` เพื่อสั่งให้หุ่นยนต์แสดงท่าทางเฉพาะ
* **ลักษณะของ Canned Actions**:
  * ท่าเต้น / โยกตัวตามจังหวะ (Dance / Wiggle)
  * ท่าแสดงความยินดี / ดีใจ (Celebrate / Happy spin)
  * ท่าปฏิเสธ / ส่ายหน้า (Say No / Head Shake)
  * ท่าก้มทักทาย / คำนับ (Bow / Greet)
  * ท่าตกใจ / ถอยหลังเล็กน้อย (Startled / Step back)
* **การหยุด Action แบบ Loop**:
  บาง Action มีลักษณะวนรอบไม่รู้จบ ต้องสั่งยกเลิกด้วยคำสั่ง:
  ```java
  robotAPI.cancelCommand(RobotCommand.MOTION_PLAY_ACTION.getValue());
  ```

---

### หมวดที่ 3: Facial Expressions (การแสดงออกทางสีหน้า 24 รูปแบบ)

* **API Signature**: `robotAPI.robot.setExpression(RobotFace.<FACE_NAME>)`

ตารางจำแนกสีหน้าตามบริบทการโต้ตอบ (Human-Robot Interaction):

| กลุ่มอารมณ์ | รายการ `RobotFace` Constant | บริบทและจังหวะการนำไปใช้ |
| :--- | :--- | :--- |
| **Normal / Standby** | `DEFAULT`<br>`DEFAULT_STILL`<br>`ACTIVE` | สีหน้าเริ่มต้น, สแตนด์บายพร้อมรับคำสั่ง, หน้าตื่นตัว |
| **Happiness & Pride** | `HAPPY`<br>`PLEASED`<br>`PROUD`<br>`CONFIDENT` | ภารกิจสำเร็จ, ผู้ใช้งานกล่าวชม, ตอบคำถามถูกต้อง |
| **Curiosity & Query** | `INTEREST`<br>`QUESTIONING`<br>`DOUBT`<br>`EXPECTING` | กำลังฟังเสียงผู้ใช้, รอรับอินพุต, สอบถามข้อมูลเพิ่มเติม |
| **Hesitation & Worry** | `SHY`<br>`WORRIED`<br>`HELPLESS`<br>`INNOCENT` | แบตเตอรี่ใกล้หมด, หาทางไปต่อไม่ได้, เขินอาย, ขอความช่วยเหลือ |
| **Surprise & Fatigue** | `SHOCK`<br>`TIRED`<br>`LAZY`<br>`IMPATIENT` | ตรวจพบสิ่งกีดขวางกะทันหัน, ใช้งานเป็นเวลานาน, รอผู้ใช้นานเกินไป |
| **Special Context** | `SINGING`<br>`PRETENDING`<br>`HIDEFACE` | จังหวะร้องเพลง, แกล้งทำเป็นไม่รู้, เล่นซ่อนหา/ปิดตา |
| **Advanced Versions** | `*_ADV` (เช่น `HAPPY_ADV`, `TIRED_ADV`) | แอนิเมชันกระพริบตาและการเคลื่อนไหวม่านตาที่มีระยะเวลาและลูกเล่นสมจริงขึ้น |

---

### หมวดที่ 4: WheelLights (แอนิเมชันไฟ LED ที่วงล้อ)

ไฟวงแหวน LED ที่ล้อทั้ง 2 ข้าง ช่วยสื่อสารสถานะและอารมณ์ร่วมกับท่าทาง

| รูปแบบไฟ (Light Pattern) | เมธอด SDK | การสื่อความหมาย / Use Case |
| :--- | :--- | :--- |
| **Blinking (กระพริบ)** | `startBlinking(...)` | แจ้งเตือนด่วน (Alert), จังหวะเต้นสนุกสนาน |
| **Breathing (วาบช้าๆ)** | `startBreathing(...)` | สแตนด์บาย (Idle), AI กำลังประมวลผล (Thinking) |
| **Charging (วิ่งวนชาร์จ)** | `startCharging(...)` | ชาร์จพลังงาน, กำลังโหลดข้อมูล / ส่ง API |
| **Marquee (ไฟวิ่งรอบวง)** | `startMarquee(...)` | ระหว่างเคลื่อนที่, แสดงความยินดี (Celebration) |

#### ตัวอย่างโค้ดไฟ LED:
```java
// ตั้งไฟล้อสีเขียวแบบ Breathing เพื่อแสดงสถานะ "กำลังคิด/ประมวลผล"
robotAPI.wheelLights.turnOff(WheelLights.Lights.SYNC_BOTH, 0xFF);
robotAPI.wheelLights.setColor(WheelLights.Lights.SYNC_BOTH, 0xFF, 0x00D031);
robotAPI.wheelLights.setBrightness(WheelLights.Lights.SYNC_BOTH, 0xFF, 10);
robotAPI.wheelLights.startBreathing(WheelLights.Lights.SYNC_BOTH, 0xFF, 20, 10, 0);
```

---

### หมวดที่ 5: Emotional Actions (ท่าทางผสมผสาน Multi-Modal)

การนำท่าทางของตัวหุ่น (Physical Canned Action) มารวมกับลำดับการเปลี่ยนสีหน้า (Facial Expression Sequence) แบบ Real-time

* **API Signature**: `robotAPI.utility.playEmotionalAction(List<RobotUtil.faceItem> list, int actionId)`
* **ตัวอย่างโค้ด**:
  ```java
  List<RobotUtil.faceItem> faceList = new ArrayList<>();
  faceList.add(new RobotUtil.faceItem(RobotFace.DEFAULT, 10)); // หน้าปกติ 1 วินาที
  faceList.add(new RobotUtil.faceItem(RobotFace.EXPECT, 15));  // เปลี่ยนเป็นหน้าคาดหวัง 1.5 วินาที
  faceList.add(new RobotUtil.faceItem(RobotFace.HAPPY, 20));   // จบด้วยหน้าดีใจ 2 วินาที

  // สั่งให้เล่น Action #5 พร้อมชุดสีหน้านี้
  int commandSerial = robotAPI.utility.playEmotionalAction(faceList, 5);
  ```

---

## 3. กลยุทธ์การประยุกต์ใช้ในการแข่งขัน Hackathon

1. **การควบคุมแบบ Async & Callback Synchronization**:
   * คำสั่ง Action ทุกตัวจะส่งกลับค่า `Command Serial Number`
   * ตรวจสอบผลลัพธ์ผ่าน `RobotCallback.onStateChange()` เพื่อให้แน่ใจว่า Action ปัจจุบันทำงานเสร็จสมบูรณ์ (`RobotCmdState.SUCCESS`) ก่อนสั่ง Action ถัดไป ป้องกันปัญหา Command Queue ซ้อนทับ
2. **ความปลอดภัยและระบบป้องกันการชน (Safety First)**:
   * ก่อนสั่ง `moveBody` ทุกครั้ง ควรตรวจสอบ Sensor:
     * `TYPE_DROP_LASER`: ป้องกันการตกจากที่สูง/บันได
     * `TYPE_SONAR`: ป้องกันการชนผนัง สิ่งกีดขวาง หรือผู้คน
3. **การออกแบบ Multi-Modal UX ที่สมบูรณ์แบบ**:
   * เพื่อสร้างความประทับใจแก่กรรมการและผู้ใช้งาน ให้ผสาน 4 องค์ประกอบพร้อมกันในแต่ละสถานการณ์:
     $$\text{Interaction} = \text{TTS (เสียง)} + \text{RobotFace (สีหน้า)} + \text{WheelLights (ไฟ)} + \text{Motion (ท่าทาง)}$$
