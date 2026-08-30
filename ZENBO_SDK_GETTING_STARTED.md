# Zenbo SDK Getting Started (v1.0.0)

> Source: [ASUS Zenbo Developer Documents](https://zenbo.asus.com/developer/documents/zenbo/Zenbo-SDK-Getting-Started/1.0.0/Getting-Started)

---

## 1. System Requirements & SDK Package

### System Requirements
* **OS**: Android M (API Level 23)
* **IDE**: Android Studio or any compatible Android IDE
* **Dependencies**: Google GSON library

### SDK Package Contents
1. **Java JAR file**: `ZenboSDK.jar`
2. **RobotActivityLibrary**: AAR module with extended activity and imported Zenbo SDK
3. **RobotDevSample**: Sample code demonstrating SDK features
4. **Javadoc**: API documentation for `ZenboSDK`

---

## 2. Core Concepts & Dialogue System Workflow

* **DS**: Dialogue System
* **CSR**: Continuous Speech Recognition
* **SLU**: Spoken Language Understanding

### Development & Execution Flow
1. **Developer Setup**:
   * Add cross-intents to the DS Editor (e.g., *"take a photo"*), configure package name and launch Activity.
   * Define App actions in DS Editor to support voice commands.
   * Integrate Zenbo SDK into the Android application (Motion, Vision, Robot, Utility, etc.).
2. **User Interaction**:
   * User says *"Hey Zenbo"* to activate CSR, followed by a voice intent.
   * DS sends voice commands to the Cloud and returns the SLU result.
   * Robot framework parses the SLU result and launches the target App.
   * App receives the SLU result defined in DS Editor via Zenbo SDK and executes the matching logic.

---

## 3. SDK Subclasses & Callbacks

### Subclasses
| Subclass | Capabilities |
| :--- | :--- |
| **Robot** | Dialog system, Facial Expressions, Speech |
| **Vision** | Face detection, Body tracing, Arm gestures, Height measurement |
| **Motion** | Move Body/Head, Remote control, Stop motion |
| **Utility** | Follow user, Go to location by gesture, Play emotional/canned actions |
| **WheelLights** | Wheel LED patterns: Blinking, Breathing, Charging, Marquee, Color & Brightness |
| **Contacts** | User profile, Room information |
| **Slam** | Localization & mapping |

### Callbacks
Every function call returns a command **serial number** to track command execution.

* **General Callback (`RobotCallback`)**:
  * `onStateChange(int cmd, int serial, RobotErrorCode err_code, RobotCmdState state)`: Returns status (`ACTIVE`, `PENDING`, `SUCCESS`, `FAIL`). If `FAIL`, error code is provided.
  * `onResult(int cmd, int serial, RobotErrorCode err_code, Bundle result)`: Returns parameters/results of the processed command.
  * `initComplete()`: Called when RobotAPI is initialized and ready.
* **DS (Dialogue System) Callback (`Listen` class)**:
  * `onResult(String slu_result)`: SLU recognition result.
  * `onRetry()`: Triggered when DS cannot recognize speech and asks the user again.
  * `onVoiceDetect(VoiceEvent event)`: Triggered on voice events (e.g., "Hey Zenbo", start/stop CSR).
* **Vision Callback**:
  * `onDetectFaceResult(List<DetectFaceResult> resultList)`: Returns face location and bounding box.
  * `onDetectPersonResult(List<DetectPersonResult> resultList)`: Returns person body location.
  * `onGesturePoint(List<GesturePointResult> resultList)`: Returns arm gesture point coordinates.

---

## 4. AndroidManifest.xml Configuration

```xml
<application
    android:allowBackup="true"
    android:icon="@mipmap/ic_launcher"
    android:label="@string/app_name"
    android:supportsRtl="true"
    android:theme="@style/AppTheme">

    <!-- DDE (Dialog Development Engine) Domain UUID and Table Version -->
    <meta-data
        android:name="zenbo_ds_domainuuid"
        android:value="82F199B9E7774C688114A72457E3C223" />
    <meta-data
        android:name="zenbo_ds_version_82F199B9E7774C688114A72457E3C223"
        android:value="0.0.1" />

    <activity android:name=".MainActivity">
        <intent-filter>
            <action android:name="android.intent.action.MAIN" />

            <!-- Optional: Remove LAUNCHER category if you only want voice command activation -->
            <category android:name="android.intent.category.LAUNCHER" />

            <!-- Declares compatibility with Zenbo SDK -->
            <category android:name="com.asus.intent.category.ZENBO" />

            <!-- Allows app to appear in Zenbo Launcher -->
            <category android:name="com.asus.intent.category.ZENBO_LAUNCHER" />

            <!-- Minimum Robot API Level required -->
            <data android:name="com.asus.intent.data.MIN_ROBOT_API_LEVEL.1" />
        </intent-filter>
    </activity>
</application>
```

---

## 5. Lifecycle & API Initialization

```java
public class MainActivity extends Activity {

    private RobotAPI mRobotAPI;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        // Initialize RobotAPI instance
        mRobotAPI = new RobotAPI(getApplicationContext(), robotCallback);
    }

    @Override
    protected void onResume() {
        super.onResume();
        // Register DS listener callback
        if (mRobotAPI != null) {
            mRobotAPI.robot.registerListenCallback(dsCallback);
        }
    }

    @Override
    protected void onPause() {
        super.onPause();
        // Unregister to block connection when app is paused
        if (mRobotAPI != null) {
            mRobotAPI.robot.unregisterListenCallback();
        }
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        if (mRobotAPI != null) {
            mRobotAPI.release();
        }
    }
}
```

> **Note**: Do not invoke robot motion/actions directly inside the function where `RobotAPI` is instantiated. Wait until `onResume()` or `RobotCallback.initComplete()`.

---

## 6. Code Examples

### 6.1 Parsing Cross-Intent SLU Data at Startup
```java
Intent intent = getIntent();
JSONObject slu_json;
try {
    String jsonStr = intent.getStringExtra("json");
    if (jsonStr != null) {
        slu_json = new JSONObject(jsonStr);
    }
} catch (NullPointerException | JSONException ex) {
    ex.printStackTrace();
}
```

#### Example SLU JSON:
```json
{
  "system_info": {
    "version_info": "ver1.0"
  },
  "event_slu_query": {
    "user_utterance": [
      {
        "CsrType": "Google",
        "result": ["show me a", "show me a call", "show me", "show me all", "show me a song"]
      },
      {
        "CsrType": "vocon",
        "result": "show me the photo"
      }
    ],
    "correctedSentence": "show me the photo",
    "error_code": "success",
    "app_semantic": {
      "IntentionId": "gallery.photo.request",
      "Domain": "49",
      "domain": "com.asus.robotgallery",
      "CrossIntent": true,
      "output_context": [
        "gallery_device_previous_state",
        "gallery_device_choose",
        "gallery_device_choose_number",
        "gallery_cancel",
        "gallery_quit",
        "gallery_show_tutorial",
        "gallery_repeat_tts"
      ],
      "Phrase": []
    },
    "speaker_id": "",
    "doa": 0
  }
}
```

---

### 6.2 Motion Control (Body & Head)

#### Move Body
```java
// Move relative (x meters, y meters, theta degrees/radians)
float x = 0.5f;
float y = 0.0f;
float theta = 90.0f;
mRobotAPI.motion.moveBody(x, y, theta);

// Move Body with Speed Level
MotionControl.SpeedLevel.Body bodySpeed = MotionControl.SpeedLevel.Body.L2;
mRobotAPI.motion.moveBody(x, y, theta, bodySpeed);
```

#### Move Head
```java
float pitch = (float) Math.toRadians(15);
float yaw = (float) Math.toRadians(30);
MotionControl.SpeedLevel.Head headSpeed = MotionControl.SpeedLevel.Head.L2;

mRobotAPI.motion.moveHead(yaw, pitch, headSpeed);
```

#### Stop Motion
```java
mRobotAPI.motion.stopMoving();
```

---

### 6.3 Text-to-Speech (TTS)
```java
// Speak text
mRobotAPI.robot.speak("Hello! Welcome to Zenbo Hackathon.");

// Stop speaking
mRobotAPI.robot.stopSpeak();
```

---

### 6.4 Facial Expressions
Zenbo supports 24 preset faces:
```java
// Change facial expression
mRobotAPI.robot.setExpression(RobotFace.HAPPY);
// Other expressions: RobotFace.INTEREST, RobotFace.DOUBT, RobotFace.PROUD, RobotFace.DEFAULT, etc.
```

---

### 6.5 Canned & Emotional Actions
```java
// Play canned action by ID (e.g., #22)
int actionId = 22;
mRobotAPI.utility.playAction(actionId);

// Cancel looping action
mRobotAPI.cancelCommand(RobotCommand.MOTION_PLAY_ACTION.getValue());

// Play Emotional Action with randomized faces
List<RobotUtil.faceItem> faceItemList = new ArrayList<>();
faceItemList.add(new RobotUtil.faceItem(RobotFace.DEFAULT, 10));
faceItemList.add(new RobotUtil.faceItem(RobotFace.HAPPY, 10));
faceItemList.add(new RobotUtil.faceItem(RobotFace.EXPECT, 10));
faceItemList.add(new RobotUtil.faceItem(RobotFace.SHOCK, 10));
faceItemList.add(new RobotUtil.faceItem(RobotFace.LAZY, 10));

int commandSerial = mRobotAPI.utility.playEmotionalAction(faceItemList, 5);
```

---

### 6.6 Vision & Person Detection
```java
// Request Person Detection
mRobotAPI.vision.requestDetectPerson(1);

// Callback implementation
@Override
public void onDetectPersonResult(List<DetectPersonResult> resultList) {
    super.onDetectPersonResult(resultList);
    if (resultList == null || resultList.isEmpty()) {
        Log.d("ZenboVision", "onDetectPersonResult: empty");
    } else {
        Log.d("ZenboVision", "Person location: " + resultList.get(0).getBodyLoc().toString());
    }
}
```

---

### 6.7 Wheel LED Control (`WheelLights`)
```java
// 1. Turn Off
mRobotAPI.wheelLights.turnOff(WheelLights.Lights.SYNC_BOTH, 0xFF);

// 2. Blinking (Color: Teal, Brightness: 10)
mRobotAPI.wheelLights.setColor(WheelLights.Lights.SYNC_BOTH, 0xFF, 0x007F7F);
mRobotAPI.wheelLights.setBrightness(WheelLights.Lights.SYNC_BOTH, 0xFF, 10);
mRobotAPI.wheelLights.startBlinking(WheelLights.Lights.SYNC_BOTH, 0xFF, 30, 10, 5);

// 3. Breathing (Color: Green)
mRobotAPI.wheelLights.setColor(WheelLights.Lights.SYNC_BOTH, 0xFF, 0x00D031);
mRobotAPI.wheelLights.setBrightness(WheelLights.Lights.SYNC_BOTH, 0xFF, 10);
mRobotAPI.wheelLights.startBreathing(WheelLights.Lights.SYNC_BOTH, 0xFF, 20, 10, 0);

// 4. Charging Animation (Color: Orange)
mRobotAPI.wheelLights.setColor(WheelLights.Lights.SYNC_BOTH, 0xFF, 0xFF9000);
mRobotAPI.wheelLights.setBrightness(WheelLights.Lights.SYNC_BOTH, 0xFF, 10);
mRobotAPI.wheelLights.startCharging(WheelLights.Lights.SYNC_BOTH, 0, 1, WheelLights.Direction.DIRECTION_FORWARD, 20);

// 5. Marquee Effect
mRobotAPI.wheelLights.setBrightness(WheelLights.Lights.SYNC_BOTH, 0xFF, 20);
mRobotAPI.wheelLights.startMarquee(WheelLights.Lights.SYNC_BOTH, WheelLights.Direction.DIRECTION_FORWARD, 40, 20, 14);
```

---

## 7. Robot Sensor System

Zenbo integrates hardware sensors into the Android `SensorManager`.

### Available Sensor Constants (`Utility.SensorType`)
```java
public static final int TYPE_CAPACITY_TOUCH               = Utility.SensorType.CAPACITY_TOUCH;
public static final int TYPE_DROP_LASER                   = Utility.SensorType.DROP_LASER;
public static final int TYPE_SONAR                        = Utility.SensorType.SONAR;
public static final int TYPE_ODOMETRY                     = Utility.SensorType.ODOMETRY;
public static final int TYPE_NECK_ENCODER                 = Utility.SensorType.NECK_ENCODER;
public static final int TYPE_WHEEL_ENCODER                = Utility.SensorType.WHEEL_ENCODER;
public static final int TYPE_ROBOT_BODY_ACCELEROMETER_RAW = Utility.SensorType.ROBOT_BODY_ACCELEROMETER_RAW;
public static final int TYPE_ROBOT_BODY_GYROSCOPE_RAW     = Utility.SensorType.ROBOT_BODY_GYROSCOPE_RAW;
public static final int TYPE_ROBOT_MOTOR                  = Utility.SensorType.ROBOT_MOTOR;
public static final int TYPE_ROBOT_DOCK_IR                = Utility.SensorType.ROBOT_DOCK_IR;
public static final int TYPE_ROBOT_NECK_TRAJECTORY        = Utility.SensorType.ROBOT_NECK_TRAJECTORY;
public static final int TYPE_ROBOT_WHEEL_TRAJECTORY       = Utility.SensorType.ROBOT_WHEEL_TRAJECTORY;
```

### Sensor Specifications Table
| Sensor Type | Value Index (`SensorEvent.values`) | Description | Unit |
| :--- | :--- | :--- | :--- |
| **TYPE_DROP_LASER** | `values[0]` - `values[4]`<br>`values[5]` - `values[9]` | Drop lasers #1 to #5 distance<br>Drop lasers #1 to #5 count | meters<br>mcps |
| **TYPE_CAPACITY_TOUCH** | `values[0]` | Touch duration level:<br>`1`: 0.005s <= T < 0.35s<br>`2`: 0.35s <= T < 1s<br>`3`: 1s <= T < 3s<br>`4`: T >= 3s | category |
| **TYPE_SONAR** | `values[0]`<br>`values[1]`<br>`values[2]`<br>`values[3]`<br>`values[4]`<br>`values[5]` | Right sonar<br>Left sonar<br>Back sonar<br>Front-right sonar<br>Front-left sonar<br>Front-center sonar | meters |
| **TYPE_ODOMETRY** | `values[0]`<br>`values[1]`<br>`values[2]` | Base position X<br>Base position Y<br>Heading direction | meters<br>meters<br>radians |
| **TYPE_NECK_ENCODER** | `values[0]`<br>`values[1]`<br>`values[2]` | Neck Yaw<br>Neck Pitch<br>Status bitmask (Busy, Over-stop, Brake, Driver) | radians<br>radians<br>bitmask |
| **TYPE_WHEEL_ENCODER** | `values[0]`<br>`values[1]` | Left wheel speed<br>Right wheel speed | m/s<br>m/s |
| **TYPE_ROBOT_BODY_ACCELEROMETER_RAW** | `values[0..2]` | Body acceleration (X, Y, Z) | m/s² |
| **TYPE_ROBOT_BODY_GYROSCOPE_RAW** | `values[0..2]` | Body angular rate (X, Y, Z) | rad/s |
| **TYPE_ROBOT_MOTOR** | `values[0..3]`<br>`values[4..7]` | Motor currents (Neck Yaw, Pitch, Left Wheel, Right Wheel)<br>Motor PWM counts | A<br>counts |
| **TYPE_ROBOT_DOCK_IR** | `values[0..2]` | Right, Center, Left dock IR | - |
| **TYPE_ROBOT_NECK_TRAJECTORY** | `values[0..1]` | Neck Yaw, Neck Pitch trajectory | radians |
| **TYPE_ROBOT_WHEEL_TRAJECTORY** | `values[0..1]` | Left wheel, Right wheel trajectory | m/s |

### Sensor Event Listener Example
```java
SensorEventListener listenerCapacityTouch = new SensorEventListener() {
    @Override
    public void onSensorChanged(SensorEvent event) {
        float touchDurationCategory = event.values[0];
        Log.d("ZenboSensor", "Touch level: " + touchDurationCategory);
    }

    @Override
    public void onAccuracyChanged(Sensor sensor, int accuracy) {}
};
```

---

## 8. Frequently Asked Questions (FAQ)

1. **Why does my App close and return to Zenbo's face automatically?**
   * Zenbo operates in two modes: **Android mode** and **Zenbo mode**.
   * Apps launched outside Zenbo mode will automatically time out after 1 minute. Adding `FLAG_KEEP_SCREEN_ON` prevents this timeout, but hearing *"Hey Zenbo"* will still bring Zenbo's face to the foreground.
2. **Why can't I find my new app in the Zenbo Store?**
   * Check `MIN_ROBOT_API_LEVEL` in `AndroidManifest.xml`. The Zenbo Store hides apps requiring an API level higher than the robot's current OS image.
3. **How do I handle Head Press events customly?**
   * Disable the default system head-press action: `RobotAPI.robot.setPressOnHeadAction(...)`.
   * Register an Android `SensorEventListener` for `Utility.SensorType.CAPACITY_TOUCH`.
4. **Can developers access 3D camera depth streams?**
   * No, raw 3D depth stream access is not opened in the standard SDK.
5. **Why do I get `SERVICE_FAIL` on API calls?**
   * Instantiate `RobotAPI` in `onCreate()` and execute commands only after `onResume()` or once `RobotCallback.initComplete()` is received. Do not execute commands immediately inside constructor callbacks.
