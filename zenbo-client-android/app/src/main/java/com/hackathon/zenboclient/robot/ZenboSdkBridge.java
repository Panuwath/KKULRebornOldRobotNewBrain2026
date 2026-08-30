package com.hackathon.zenboclient.robot;

import android.content.Context;
import android.graphics.PointF;
import android.os.Bundle;
import android.util.Log;
import java.util.List;
import java.util.Map;
import com.asus.robotframework.API.MotionControl;
import com.asus.robotframework.API.RobotAPI;
import com.asus.robotframework.API.RobotCallback;
import com.asus.robotframework.API.RobotCmdState;
import com.asus.robotframework.API.RobotCommand;
import com.asus.robotframework.API.RobotErrorCode;
import com.asus.robotframework.API.RobotFace;
import com.asus.robotframework.API.RobotUtil;
import com.asus.robotframework.API.WheelLights;
import com.asus.robotframework.API.VisionConfig;
import com.hackathon.zenboclient.model.InteractCommand;
import java.util.ArrayList;

public class ZenboSdkBridge {
    private static final String TAG = "ZenboSdkBridge";
    private RobotAPI mRobotAPI;
    private boolean mIsInitialized = false;

    public interface ActionCallback {
        void onActionState(String status);
        void onVisionResult(String action, String payload);
        void onError(String code, String message);
    }

    private ActionCallback mActionCallback;

    public void init(Context context, ActionCallback callback) {
        this.mActionCallback = callback;
        mRobotAPI = new RobotAPI(context, new RobotCallback() {
            @Override
            public void initComplete() {
                super.initComplete();
                mIsInitialized = true;
                Log.d(TAG, "RobotAPI Init Complete!");
                if (mActionCallback != null) {
                    mActionCallback.onActionState("INIT_COMPLETE");
                }
            }

            @Override
            public void onStateChange(int cmd, int serial, RobotErrorCode err, RobotCmdState state) {
                super.onStateChange(cmd, serial, err, state);
                Log.d(TAG, "onStateChange: cmd=" + cmd + ", state=" + state + ", err=" + err);
                if (mActionCallback != null) {
                    mActionCallback.onActionState(state.name());
                }
            }

            @Override
            public void onResult(int cmd, int serial, RobotErrorCode err, Bundle data) {
                super.onResult(cmd, serial, err, data);
                if (err != null && err != RobotErrorCode.NO_ERROR && mActionCallback != null) {
                    mActionCallback.onError(err.name(), "cmd=" + cmd + " serial=" + serial);
                }
            }

            @Override
            public void onDetectFaceResult(List<com.asus.robotframework.API.results.DetectFaceResult> faces) {
                super.onDetectFaceResult(faces);
                if (mActionCallback != null) {
                    StringBuilder sb = new StringBuilder();
                    sb.append("{\"action\":\"detect_face\",\"faces\":[");
                    for (int i = 0; i < faces.size(); i++) {
                        com.asus.robotframework.API.results.DetectFaceResult f = faces.get(i);
                        if (i > 0) sb.append(",");
                        sb.append("{")
                          .append("\"uuid\":\"").append(f.getUuid()).append("\",")
                          .append("\"track_id\":").append(f.getTrackID()).append(",")
                          .append("\"confidence\":").append(f.getHeadPoseConfidence()).append(",")
                          .append("\"emotion\":").append(f.getFaceEmotion()).append(",")
                          .append("\"has_depth\":").append(f.hasValidDepth()).append(",")
                          .append("\"gaze\":\"").append(f.getHeadGazeDirection()).append("\"")
                          .append("}");
                    }
                    sb.append("]}");
                    mActionCallback.onVisionResult("detect_face", sb.toString());
                }
            }

            @Override
            public void onDetectPersonResult(List<com.asus.robotframework.API.results.DetectPersonResult> persons) {
                super.onDetectPersonResult(persons);
                if (mActionCallback != null) {
                    StringBuilder sb = new StringBuilder();
                    sb.append("{\"action\":\"detect_person\",\"persons\":[");
                    for (int i = 0; i < persons.size(); i++) {
                        com.asus.robotframework.API.results.DetectPersonResult p = persons.get(i);
                        if (i > 0) sb.append(",");
                        sb.append("{")
                          .append("\"track_id\":").append(p.getTrackID()).append(",")
                          .append("\"confidence\":").append(p.getTrackConf()).append(",")
                          .append("\"has_depth\":").append(p.hasValidDepth()).append(",")
                          .append("\"track_time\":").append(p.getTrackerTimeDelta())
                          .append("}");
                    }
                    sb.append("]}");
                    mActionCallback.onVisionResult("detect_person", sb.toString());
                }
            }

            @Override
            public void onGesturePoint(com.asus.robotframework.API.results.GesturePointResult result) {
                super.onGesturePoint(result);
                if (mActionCallback != null && result != null && result.getHasValue()) {
                    String payload = "{"
                        + "\"action\":\"gesture_point\","
                        + "\"track_id\":" + result.getTrackId() + ","
                        + "\"point3d\":{\"x\":" + result.getPoint3D().x + ",\"y\":" + result.getPoint3D().y + ",\"z\":" + result.getPoint3D().z + "},"
                        + "\"vector3d\":{\"x\":" + result.getVector3D().x + ",\"y\":" + result.getVector3D().y + ",\"z\":" + result.getVector3D().z + "}"
                        + "}";
                    mActionCallback.onVisionResult("gesture_point", payload);
                }
            }

            @Override
            public void onRecognizePersonResult(List<com.asus.robotframework.API.results.RecognizePersonResult> results) {
                super.onRecognizePersonResult(results);
                if (mActionCallback != null) {
                    StringBuilder sb = new StringBuilder();
                    sb.append("{\"action\":\"recognize_person\",\"results\":[");
                    for (int i = 0; i < results.size(); i++) {
                        com.asus.robotframework.API.results.RecognizePersonResult r = results.get(i);
                        if (i > 0) sb.append(",");
                        sb.append("{")
                          .append("\"uuid\":\"").append(r.getUuid()).append("\",")
                          .append("\"track_id\":").append(r.getTrackID()).append(",")
                          .append("\"confidence\":").append(r.getHeadPoseConfidence()).append(",")
                          .append("\"emotion\":").append(r.getFaceEmotion())
                          .append("}");
                    }
                    sb.append("]}");
                    mActionCallback.onVisionResult("recognize_person", sb.toString());
                }
            }
        });
    }

    private String normalizeFaceName(String faceName) {
        if (faceName == null) return "DEFAULT";
        String f = faceName.trim().toUpperCase();
        switch (f) {
            case "DOUBT": return "DOUBTING";
            case "EXPECT": return "EXPECTING";
            case "SHOCK": return "SHOCKED";
            case "INTEREST": return "INTERESTED";
            case "DEFAULT_STILL": return "DEFAULT_STILL";
            case "ACTIVE": return "ACTIVE";
            default: return f;
        }
    }

    public void setExpression(String faceName) {
        if (mRobotAPI == null) return;
        try {
            RobotFace face = RobotFace.valueOf(normalizeFaceName(faceName));
            mRobotAPI.robot.setExpression(face);
        } catch (Exception e) {
            Log.w(TAG, "Unknown RobotFace: " + faceName + ", using DEFAULT");
            mRobotAPI.robot.setExpression(RobotFace.DEFAULT);
        }
    }

    public void speak(String text) {
        if (mRobotAPI == null) return;
        try {
            mRobotAPI.robot.speak(text);
        } catch (Exception e) {
            Log.e(TAG, "speak failed: " + e.getMessage(), e);
        }
    }

    public void stopSpeak() {
        if (mRobotAPI == null) return;
        try {
            mRobotAPI.robot.stopSpeak();
        } catch (Exception e) {
            Log.e(TAG, "stopSpeak failed: " + e.getMessage(), e);
        }
    }

    public void moveBody(float x, float y, float theta, int speedLevel) {
        if (mRobotAPI == null) return;
        try {
            MotionControl.SpeedLevel.Body speed = MotionControl.SpeedLevel.Body.getBody(speedLevel);
            mRobotAPI.motion.moveBody(x, y, theta, speed);
        } catch (Exception e) {
            Log.e(TAG, "moveBody failed: " + e.getMessage(), e);
        }
    }

    public void moveHead(float yawDegrees, float pitchDegrees, int speedLevel) {
        if (mRobotAPI == null) return;
        try {
            float yawRad = (float) Math.toRadians(yawDegrees);
            float pitchRad = (float) Math.toRadians(pitchDegrees);
            MotionControl.SpeedLevel.Head speed = MotionControl.SpeedLevel.Head.getHead(speedLevel);
            mRobotAPI.motion.moveHead(yawRad, pitchRad, speed);
        } catch (Exception e) {
            Log.e(TAG, "moveHead failed: " + e.getMessage(), e);
        }
    }

    public void playAction(int actionId) {
        if (mRobotAPI == null) return;
        try {
            mRobotAPI.utility.playAction(actionId);
        } catch (Exception e) {
            Log.e(TAG, "playAction failed: " + e.getMessage(), e);
        }
    }

    public void playEmotionalAction(InteractCommand.EmotionalActionData action) {
        if (mRobotAPI == null || action == null || action.faces == null || action.faces.length == 0) return;
        try {
            List<RobotUtil.faceItem> faces = new ArrayList<>();
            for (InteractCommand.FaceStep step : action.faces) {
                if (step != null && step.face != null) {
                    faces.add(new RobotUtil.faceItem(RobotFace.valueOf(normalizeFaceName(step.face)), step.duration));
                }
            }
            if (faces.isEmpty()) return;
            if (action.speed != null) mRobotAPI.utility.playEmotionalAction(faces, action.actionId, action.speed);
            else mRobotAPI.utility.playEmotionalAction(faces, action.actionId);
        } catch (Exception e) {
            Log.e(TAG, "playEmotionalAction failed: " + e.getMessage(), e);
        }
    }

    public void remoteControl(InteractCommand.RemoteControlData remote) {
        if (mRobotAPI == null || remote == null) return;
        try {
            if (remote.body != null) {
                mRobotAPI.motion.remoteControlBody(
                        MotionControl.Direction.Body.valueOf(remote.body.trim().toUpperCase()));
            }
            if (remote.head != null) {
                mRobotAPI.motion.remoteControlHead(
                        MotionControl.Direction.Head.valueOf(remote.head.trim().toUpperCase()));
            }
        } catch (IllegalArgumentException e) {
            Log.w(TAG, "Unsupported remote-control direction", e);
        } catch (Exception e) {
            Log.e(TAG, "remoteControl failed: " + e.getMessage(), e);
        }
    }

    public void runBehavior(InteractCommand.BehaviorData behavior) {
        if (mRobotAPI == null || behavior == null || behavior.action == null) return;
        boolean enabled = behavior.enabled == null || behavior.enabled;
        try {
            switch (behavior.action.trim().toLowerCase()) {
                case "look_at_user":
                    mRobotAPI.utility.lookAtUser(behavior.distance == null ? 1.5f : behavior.distance);
                    break;
                case "track_face":
                    mRobotAPI.utility.trackFace(enabled, behavior.track == null || behavior.track);
                    break;
                case "follow_face":
                    mRobotAPI.utility.followFace(enabled, behavior.track == null || behavior.track);
                    break;
                case "follow_object":
                    if (enabled) mRobotAPI.utility.followObject();
                    break;
                default:
                    Log.w(TAG, "Unsupported behavior: " + behavior.action);
            }
        } catch (Exception e) {
            Log.e(TAG, "runBehavior failed: " + e.getMessage(), e);
        }
    }

    public void cancelCurrentAction() {
        if (mRobotAPI == null) return;
        try {
            mRobotAPI.cancelCommand(RobotCommand.MOTION_PLAY_ACTION);
        } catch (Exception e) {
            Log.e(TAG, "cancelCommand failed: " + e.getMessage(), e);
        }
    }

    public void runVision(String action, int intervalMs, Integer trackId, boolean debugPreview) {
        if (mRobotAPI == null || action == null) return;
        try {
            switch (action.toLowerCase()) {
                case "detect_face":
                    VisionConfig.FaceDetectConfig faceConfig = new VisionConfig.FaceDetectConfig();
                    faceConfig.intervalInMS = intervalMs;
                    faceConfig.enableDebugPreview = debugPreview;
                    faceConfig.enableDetectHead = true;
                    mRobotAPI.vision.requestDetectFace(faceConfig);
                    break;
                case "detect_person":
                    VisionConfig.PersonDetectConfig personConfig = new VisionConfig.PersonDetectConfig();
                    personConfig.intervalInMS = intervalMs;
                    personConfig.enableDebugPreview = debugPreview;
                    if (trackId != null) personConfig.trackId = trackId;
                    mRobotAPI.vision.requestDetectPerson(personConfig);
                    break;
                case "gesture_point":
                    if (trackId == null) mRobotAPI.vision.requestGesturePoint(intervalMs);
                    else mRobotAPI.vision.requestGesturePoint(intervalMs, trackId);
                    break;
                case "recognize_person":
                    mRobotAPI.vision.requestRecognizePerson(intervalMs);
                    break;
                case "measure_height":
                    mRobotAPI.vision.requestMeasureHeight(intervalMs);
                    break;
                case "cancel_face":
                    mRobotAPI.vision.cancelDetectFace();
                    break;
                case "cancel_person":
                    mRobotAPI.vision.cancelDetectPerson();
                    break;
                case "cancel_recognize":
                    mRobotAPI.vision.cancelRecognizePerson();
                    break;
                default:
                    Log.w(TAG, "Unsupported vision action: " + action);
            }
        } catch (Exception e) {
            Log.e(TAG, "Vision action failed: " + action, e);
        }
    }

    public void controlWheelLights(InteractCommand.WheelLightsData settings) {
        if (mRobotAPI == null) return;
        try {
            int color = 0x00D031;
            try {
                String colorText = settings.color == null ? "" : settings.color.trim();
                if (colorText.startsWith("#")) colorText = "0x" + colorText.substring(1);
                color = Integer.decode(colorText);
            } catch (Exception ignored) {}

            WheelLights.Lights lights = WheelLights.Lights.SYNC_BOTH;
            if ("left".equalsIgnoreCase(settings.side)) lights = WheelLights.Lights.ASYNC_LEFT;
            else if ("right".equalsIgnoreCase(settings.side)) lights = WheelLights.Lights.ASYNC_RIGHT;
            WheelLights.Direction direction = "backward".equalsIgnoreCase(settings.direction)
                    ? WheelLights.Direction.DIRECTION_BACKWARD : WheelLights.Direction.DIRECTION_FORWARD;
            WheelLights.Speed speed;
            try { speed = WheelLights.Speed.valueOf(settings.speed.toUpperCase()); }
            catch (Exception ignored) { speed = WheelLights.Speed.DEFAULT; }

            mRobotAPI.wheelLights.turnOff(lights, 0xFF);
            mRobotAPI.wheelLights.setColor(lights, 0xFF, color);

            String mode = settings.mode == null ? "breathing" : settings.mode.toLowerCase();
            switch (mode) {
                case "off": mRobotAPI.wheelLights.turnOff(lights, 0xFF); break;
                case "blinking": case "strobing": mRobotAPI.wheelLights.startStrobing(lights, speed); break;
                case "breathing": case "breath": mRobotAPI.wheelLights.startBreath(lights, speed); break;
                case "breath_rainbow": mRobotAPI.wheelLights.startBreathRainbow(lights, speed); break;
                case "charging": case "color_cycle": mRobotAPI.wheelLights.startColorCycle(lights, speed); break;
                case "rainbow": mRobotAPI.wheelLights.startRainbow(lights, direction, speed); break;
                case "comet": mRobotAPI.wheelLights.startComet(lights, direction, speed); break;
                case "rainbow_comet": mRobotAPI.wheelLights.startRainbowComet(lights, direction, speed); break;
                // "marquee" is the LIFF label for a moving light chase. The
                // Zenbo SDK exposes it as MovingFlash rather than Marquee.
                case "marquee": mRobotAPI.wheelLights.startMovingFlash(lights, direction, speed); break;
                case "moving_flash": mRobotAPI.wheelLights.startMovingFlash(lights, direction, speed); break;
                case "flash_dash": mRobotAPI.wheelLights.startFlashDash(lights, direction, speed); break;
                case "rainbow_wave": mRobotAPI.wheelLights.startRainbowWave(lights, direction, speed); break;
                case "glowing_yoyo": mRobotAPI.wheelLights.startGlowingYoYo(lights, speed); break;
                case "wave": mRobotAPI.wheelLights.startWave(lights, speed); break;
                case "starry": mRobotAPI.wheelLights.startStarryNight(lights, speed); break;
                case "static": mRobotAPI.wheelLights.startStatic(lights); break;
                default: mRobotAPI.wheelLights.startBreath(lights, speed);
            }
        } catch (Exception e) {
            Log.e(TAG, "controlWheelLights failed: " + e.getMessage(), e);
        }
    }

    public void emergencyStop() {
        if (mRobotAPI != null) {
            try {
                mRobotAPI.motion.stopMoving();
                mRobotAPI.cancelCommandAll();
            } catch (Exception e) {
                Log.e(TAG, "emergencyStop failed: " + e.getMessage(), e);
            }
        }
    }

    public void release() {
        if (mRobotAPI != null) {
            try {
                mRobotAPI.release();
            } catch (Exception ignored) {}
            mRobotAPI = null;
        }
    }
}
