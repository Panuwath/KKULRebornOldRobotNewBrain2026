package com.hackathon.zenboclient.model;

import com.google.gson.annotations.SerializedName;

public class InteractCommand {
    @SerializedName("command_id")
    public String commandId;

    @SerializedName("scenario_run_id")
    public String scenarioRunId;

    @SerializedName("source_session_id")
    public String sourceSessionId;

    @SerializedName("source_seq")
    public Long sourceSeq;

    @SerializedName("issued_at_ms")
    public Long issuedAtMs;

    @SerializedName("expires_at_ms")
    public Long expiresAtMs;

    @SerializedName("text")
    public String text;

    @SerializedName("audio_url")
    public String audioUrl;

    @SerializedName("audio_base64")
    public String audioBase64;

    @SerializedName("volume")
    public Integer volume;

    @SerializedName("voice")
    public String voice;

    @SerializedName("voice_profile")
    public String voiceProfile;

    @SerializedName("age")
    public Integer age;

    @SerializedName("speed")
    public Float speed;

    @SerializedName("face")
    public String face;

    @SerializedName("motion")
    public MotionData motion;

    @SerializedName("policy")
    public MotionPolicyData policy;

    @SerializedName("head")
    public HeadData head;

    @SerializedName("head_sequence")
    public HeadData[] headSequence;

    @SerializedName("after_speech")
    public AfterSpeechData afterSpeech;

    /** Bounded L1 stationary scene script, executed one step at a time. */
    @SerializedName("script")
    public ScenarioScriptData script;

    /** L2 anonymous vision gate with local detect/timeout response scripts. */
    @SerializedName("interactive")
    public InteractiveScenarioData interactive;

    @SerializedName("interactive_sequence")
    public InteractiveSequenceData interactiveSequence;

    @SerializedName("action")
    public ActionData action;

    @SerializedName("emotional_action")
    public EmotionalActionData emotionalAction;

    @SerializedName("remote_control")
    public RemoteControlData remoteControl;

    @SerializedName("behavior")
    public BehaviorData behavior;

    @SerializedName("wheel_lights")
    public WheelLightsData wheelLights;

    @SerializedName("vision")
    public VisionData vision;

    @SerializedName("youtube")
    public YouTubeData youtube;

    @SerializedName("camera")
    public CameraData camera;

    @SerializedName("safety")
    public SafetyData safety;

    @SerializedName("navigation")
    public NavigationData navigation;

    public static class MotionData {
        @SerializedName("control_mode")
        public String controlMode;
        @SerializedName(value = "x_m", alternate = {"x"})
        public float x;
        @SerializedName(value = "y_m", alternate = {"y"})
        public float y;
        @SerializedName(value = "theta_deg", alternate = {"theta"})
        public float theta;
        @SerializedName(value = "requested_speed_level", alternate = {"speed"})
        public int speed = 5;
    }

    public static class MotionPolicyData {
        @SerializedName("policy_version")
        public String policyVersion;
        @SerializedName("max_body_speed_level")
        public int maxBodySpeedLevel;
        @SerializedName("max_distance_m")
        public float maxDistanceM;
        @SerializedName("hard_stop_after_ms")
        public long hardStopAfterMs;
    }

    public static class HeadData {
        public float yaw;
        public float pitch;
        public int speed = 2;
        @SerializedName("delay_ms")
        public int delayMs = 0;
    }

    public static class ActionData {
        @SerializedName("action_id")
        public int actionId;
        public boolean stop;

        @SerializedName("action_type")
        public String actionType;
    }

    public static class WheelLightsData {
        public String mode;
        public String color;
        public int brightness = 10;
        public String side = "both";
        public String direction = "forward";
        public String speed = "DEFAULT";
    }

    public static class EmotionalActionData {
        @SerializedName("action_id")
        public int actionId;
        public FaceStep[] faces;
        public Float speed;
    }

    public static class FaceStep {
        public String face;
        /** Duration in the SDK's face-item units (normally tenths of a second). */
        public double duration = 10;
    }

    /** Stationary visual cue to run when the actual Thai-audio playback ends. */
    public static class AfterSpeechData {
        public String face;
        public HeadData head;
        @SerializedName("head_sequence")
        public HeadData[] headSequence;
        @SerializedName("wheel_lights")
        public WheelLightsData wheelLights;
    }

    public static class ScenarioScriptData {
        public ScenarioStepData[] steps;
    }

    /** L1 only: the Core registry rejects movement, media, and canned actions. */
    public static class ScenarioStepData {
        public String text;
        @SerializedName("voice_profile")
        public String voiceProfile;
        public String voice;
        public Integer age;
        public Float speed;
        public String face;
        public HeadData head;
        @SerializedName("head_sequence")
        public HeadData[] headSequence;
        @SerializedName("after_speech")
        public AfterSpeechData afterSpeech;
        @SerializedName("wheel_lights")
        public WheelLightsData wheelLights;
    }

    public static class InteractiveScenarioData {
        @SerializedName("vision_gate")
        public VisionGateData visionGate;
        @SerializedName("on_detect")
        public ScenarioOutcomeData onDetect;
        @SerializedName("on_timeout")
        public ScenarioOutcomeData onTimeout;
    }

    /** L4: anonymous presence gate, spoken prompt, then anonymous gesture gate. */
    public static class InteractiveSequenceData {
        @SerializedName("first_gate")
        public VisionGateData firstGate;
        public ScenarioStepData prompt;
        @SerializedName("second_gate")
        public VisionGateData secondGate;
        @SerializedName("on_first_timeout")
        public ScenarioOutcomeData onFirstTimeout;
        @SerializedName("on_second_detect")
        public ScenarioOutcomeData onSecondDetect;
        @SerializedName("on_second_timeout")
        public ScenarioOutcomeData onSecondTimeout;
    }

    public static class VisionGateData {
        public String action;
        @SerializedName("interval_ms")
        public int intervalMs = 1000;
        @SerializedName("timeout_ms")
        public int timeoutMs = 8000;
        @SerializedName("debug_preview")
        public boolean debugPreview;
    }

    public static class ScenarioOutcomeData {
        public ScenarioStepData[] steps;
        /** Present only for L5 after the user completes the anonymous gesture gate. */
        public NavigationData navigation;
    }

    public static class RemoteControlData {
        /** Body: FORWARD, BACKWARD, TURN_LEFT, TURN_RIGHT, STOP. */
        public String body;
        /** Head: UP, DOWN, LEFT, RIGHT, STOP. */
        public String head;
    }

    public static class BehaviorData {
        /** look_at_user, track_face, follow_face, or follow_object. */
        public String action;
        public Boolean enabled;
        public Boolean track;
        public Float distance;
    }

    public static class VisionData {
        // Supported actions: detect_face, detect_person, gesture_point,
        // recognize_person, measure_height, cancel_face, cancel_person,
        // cancel_recognize.
        public String action;
        public int interval_ms = 1000;
        public Integer track_id;
        public boolean debug_preview = false;
    }

    public static class YouTubeData {
        public String url;
        /** play | pause | resume | stop */
        public String action;
        @SerializedName("dance_action_ids")
        public int[] danceActionIds;
        @SerializedName("loop_dance")
        public boolean loopDance;
        @SerializedName("duration_seconds")
        public Integer durationSeconds;
    }

    /** WebRTC teleop camera session request. */
    public static class CameraData {
        /** start | stop | offer | answer | candidate */
        public String action;
        public String sdp;
        @SerializedName("session_id")
        public String sessionId;
        @SerializedName("ice_candidate")
        public String iceCandidate;
        @SerializedName("ice_sdp_mid")
        public String iceSdpMid;
        @SerializedName("ice_sdp_mline_index")
        public Integer iceSdpMLineIndex;
    }

    /** Conservative base-motion policy. Hardware cliff/bumper coverage is not assumed. */
    public static class SafetyData {
        @SerializedName("base_motion_enabled")
        public boolean baseMotionEnabled = true;
        @SerializedName("collision_guard_enabled")
        public boolean collisionGuardEnabled = false;
        @SerializedName("fall_guard_enabled")
        public boolean fallGuardEnabled = false;
        @SerializedName("max_distance_m")
        public float maxDistanceM = 0.75f;
        @SerializedName("max_speed")
        public int maxSpeed = 3;
        @SerializedName("auto_stop_ms")
        public int autoStopMs = 3000;
        @SerializedName("collision_distance_m")
        public float collisionDistanceM = 0.35f;
        @SerializedName("drop_distance_m")
        public float dropDistanceM = 0.16f;
    }

    public static class NavigationData {
        @SerializedName("display_url")
        public String displayUrl;
        @SerializedName("speech_text")
        public String speechText;
        @SerializedName("step_speeches")
        public String[] stepSpeeches;
    }
}
