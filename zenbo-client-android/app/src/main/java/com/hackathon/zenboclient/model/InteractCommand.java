package com.hackathon.zenboclient.model;

import com.google.gson.annotations.SerializedName;

public class InteractCommand {
    @SerializedName("command_id")
    public String commandId;

    @SerializedName("text")
    public String text;

    @SerializedName("audio_url")
    public String audioUrl;

    @SerializedName("audio_base64")
    public String audioBase64;

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

    @SerializedName("head")
    public HeadData head;

    @SerializedName("head_sequence")
    public HeadData[] headSequence;

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

    @SerializedName("navigation")
    public NavigationData navigation;

    public static class MotionData {
        public float x;
        public float y;
        public float theta;
        public int speed = 2;
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
        @SerializedName("dance_action_ids")
        public int[] danceActionIds;
        @SerializedName("loop_dance")
        public boolean loopDance;
        @SerializedName("duration_seconds")
        public Integer durationSeconds;
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
