package com.hackathon.zenboclient.service;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.net.Uri;
import android.os.Binder;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.util.Log;
import android.util.Base64;
import android.net.wifi.WifiInfo;
import android.net.wifi.WifiManager;
import androidx.core.app.NotificationCompat;
import com.google.gson.Gson;
import com.hackathon.zenboclient.BuildConfig;
import com.hackathon.zenboclient.YouTubePlayerActivity;
import com.hackathon.zenboclient.audio.AudioPlaybackManager;
import com.hackathon.zenboclient.audio.TtsClient;
import com.hackathon.zenboclient.model.InteractCommand;
import com.hackathon.zenboclient.mqtt.MqttManager;
import com.hackathon.zenboclient.robot.ZenboSdkBridge;
import com.asus.robotframework.API.results.DetectFaceResult;
import com.asus.robotframework.API.results.DetectPersonResult;
import com.asus.robotframework.API.results.GesturePointResult;
import java.util.List;

public class ZenboClientService extends Service implements MqttManager.MessageListener {
    private static final String TAG = "ZenboService";
    private static final String CHANNEL_ID = "zenbo_service_channel";
    private static final String DEFAULT_BROKER = "10.101.118.149";
    private static final int DEFAULT_PORT = 1883;
    private static final String DEFAULT_TOPIC_PREFIX = "zenbo";
    private final IBinder mBinder = new LocalBinder();
    private final Gson mGson = new Gson();

    private MqttManager mMqttManager;
    private ZenboSdkBridge mSdkBridge;
    private AudioPlaybackManager mAudioPlayer;
    private ConnectionStatusListener mConnectionStatusListener;
    private SpeechStatusListener mSpeechStatusListener;
    private String mTopicPrefix = "zenbo";
    private final Handler mHeartbeatHandler = new Handler(Looper.getMainLooper());
    private final Handler mHeadSequenceHandler = new Handler(Looper.getMainLooper());
    private final Handler mDanceHandler = new Handler(Looper.getMainLooper());
    // A remote-control STOP from the browser can be lost when a phone changes
    // network or the tab is closed.  Commands from the LIFF joystick carry a
    // short keepalive; if it disappears, stop locally instead of continuing.
    private static final long REMOTE_CONTROL_DEADMAN_MS = 900L;
    private final Handler mRemoteControlSafetyHandler = new Handler(Looper.getMainLooper());
    private final Runnable mBodyRemoteStopRunnable = new Runnable() {
        @Override public void run() { sendRemoteBodyStop(); }
    };
    private final Runnable mHeadRemoteStopRunnable = new Runnable() {
        @Override public void run() { sendRemoteHeadStop(); }
    };
    private Runnable mDanceLoopRunnable;
    private boolean mYouTubeStatusReceiverRegistered;
    private final BroadcastReceiver mYouTubeStatusReceiver = new BroadcastReceiver() {
        @Override public void onReceive(Context context, Intent intent) {
            if (!YouTubePlayerActivity.ACTION_STATUS.equals(intent.getAction())) return;
            String state = intent.getStringExtra(YouTubePlayerActivity.EXTRA_STATE);
            String message = intent.getStringExtra(YouTubePlayerActivity.EXTRA_MESSAGE);
            publishStatus("youtube", "{\"state\":\"" + escapeJson(state)
                    + "\",\"message\":\"" + escapeJson(message) + "\"}");
        }
    };
    private boolean mHeartbeatRunning;
    // The core API publishes one composite command and matching legacy leaves.
    // Ignore the immediate duplicate leaves; emergency controls are never ignored.
    private volatile long mIgnoreLegacyLeafUntilMs;
    private final Runnable mHeartbeatRunnable = new Runnable() {
        @Override
        public void run() {
            publishHeartbeat();
            if (mHeartbeatRunning) mHeartbeatHandler.postDelayed(this, 5000L);
        }
    };

    public interface ConnectionStatusListener {
        void onConnectionStatusChanged(boolean isConnected, String statusMessage);
    }

    public interface SpeechStatusListener {
        void onSpeechStatusChanged(String text, String state);
    }

    public class LocalBinder extends Binder {
        public ZenboClientService getService() {
            return ZenboClientService.this;
        }
    }

    @Override
    public void onCreate() {
        super.onCreate();
        createNotificationChannel();
        Notification notification = new NotificationCompat.Builder(this, CHANNEL_ID)
                .setContentTitle("Zenbo Client Bridge")
                .setContentText("Connected to Zenbo AI Server via MQTT")
                .setSmallIcon(android.R.drawable.stat_notify_sync)
                .build();
        startForeground(1001, notification);

        mSdkBridge = new ZenboSdkBridge();
        try {
            mSdkBridge.init(getApplicationContext(), new ZenboSdkBridge.ActionCallback() {
                @Override
                public void onActionState(String status) {
                    publishStatus("robot_state", "{\"state\":\"" + status + "\"}");
                }

                @Override
                public void onVisionResult(String action, String payload) {
                    publishStatus("vision", payload);
                }

                @Override
                public void onError(String code, String message) {
                    publishStatus("error", "{\"code\":\"" + code + "\",\"message\":\"" + escapeJson(message) + "\"}");
                }
            });
        } catch (Exception e) {
            Log.e(TAG, "Failed to initialize ZenboSdkBridge: " + e.getMessage(), e);
        }

        mAudioPlayer = new AudioPlaybackManager(this);
        IntentFilter youtubeStatus = new IntentFilter(YouTubePlayerActivity.ACTION_STATUS);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            registerReceiver(mYouTubeStatusReceiver, youtubeStatus, Context.RECEIVER_NOT_EXPORTED);
        } else {
            registerReceiver(mYouTubeStatusReceiver, youtubeStatus);
        }
        mYouTubeStatusReceiverRegistered = true;

        // A service can be restarted by Android after memory pressure or after
        // boot.  In those paths MainActivity is not necessarily recreated, so
        // start the MQTT bridge here instead of waiting for the activity.
        startDefaultMqtt();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (mMqttManager == null) startDefaultMqtt();
        // Keep the command bridge alive even when the Zenbo launcher task is
        // removed; Android recreates the foreground service after termination.
        return START_STICKY;
    }

    private void startDefaultMqtt() {
        String ip = getClientIpAddress();
        String prefix = ip.matches("[0-9.]+")
                ? DEFAULT_TOPIC_PREFIX + "/" + ip.replace('.', '-')
                : DEFAULT_TOPIC_PREFIX;
        startMqtt(DEFAULT_BROKER, DEFAULT_PORT, prefix);
    }

    public void startMqtt(String brokerIp, int port, String topicPrefix) {
        if (mMqttManager != null) {
            mMqttManager.disconnect();
        }
        mTopicPrefix = topicPrefix;
        mMqttManager = new MqttManager(this, brokerIp, port, topicPrefix,
                BuildConfig.MQTT_USERNAME, BuildConfig.MQTT_TOKEN, this);
        mMqttManager.connect();
    }

    public void setConnectionStatusListener(ConnectionStatusListener listener) {
        mConnectionStatusListener = listener;
    }

    public void setSpeechStatusListener(SpeechStatusListener listener) {
        mSpeechStatusListener = listener;
    }

    @Override
    public void onMessageReceived(String topic, String message) {
        try {
            if (isTopic(topic, "cmd/interact")) {
                mIgnoreLegacyLeafUntilMs = System.currentTimeMillis() + 1500L;
                InteractCommand cmd = mGson.fromJson(message, InteractCommand.class);
                executeInteractCommand(cmd);
            } else if (isRedundantLegacyLeaf(topic)) {
                Log.d(TAG, "Ignoring legacy leaf already included in zenbo/cmd/interact: " + topic);
            } else if (isTopic(topic, "cmd/stop") || isTopic(topic, "stop")) {
                cancelRobotSequences();
                mAudioPlayer.stop();
                mSdkBridge.stopSpeak();
                mSdkBridge.emergencyStop();
                notifySpeechStatus("", "หยุดการพูดแล้ว");
            } else if (isTopic(topic, "cmd/expression")) {
                InteractCommand cmd = mGson.fromJson(message, InteractCommand.class);
                if (cmd != null && cmd.face != null) {
                    mSdkBridge.setExpression(cmd.face);
                }
            } else if (isTopic(topic, "cmd/cancel")) {
                mSdkBridge.cancelCurrentAction();
            } else if (isTopic(topic, "cmd/speak")) {
                handleGatewayAudioCommand(message);
            } else if (isTopic(topic, "cmd/motion")) {
                InteractCommand.MotionData motion = mGson.fromJson(message, InteractCommand.MotionData.class);
                if (motion != null) mSdkBridge.moveBody(motion.x, motion.y, motion.theta, motion.speed);
            } else if (isTopic(topic, "cmd/head")) {
                InteractCommand.HeadData head = mGson.fromJson(message, InteractCommand.HeadData.class);
                if (head != null) mSdkBridge.moveHead(head.yaw, head.pitch, head.speed);
            } else if (isTopic(topic, "cmd/head_sequence")) {
                InteractCommand.HeadData[] sequence = mGson.fromJson(message, InteractCommand.HeadData[].class);
                playHeadSequence(sequence);
            } else if (isTopic(topic, "cmd/action")) {
                InteractCommand.ActionData action = mGson.fromJson(message, InteractCommand.ActionData.class);
                if (action != null) {
                    if (action.stop) mSdkBridge.cancelCurrentAction();
                    else mSdkBridge.playAction(action.actionId);
                }
            } else if (isTopic(topic, "cmd/lights")) {
                InteractCommand.WheelLightsData lights = mGson.fromJson(message, InteractCommand.WheelLightsData.class);
                if (lights != null) mSdkBridge.controlWheelLights(lights);
            } else if (isTopic(topic, "cmd/emotional")) {
                InteractCommand.EmotionalActionData action = mGson.fromJson(message, InteractCommand.EmotionalActionData.class);
                if (action != null) mSdkBridge.playEmotionalAction(action);
            } else if (isTopic(topic, "cmd/remote")) {
                InteractCommand.RemoteControlData remote = mGson.fromJson(message, InteractCommand.RemoteControlData.class);
                handleRemoteControl(remote);
            } else if (isTopic(topic, "cmd/behavior")) {
                InteractCommand.BehaviorData behavior = mGson.fromJson(message, InteractCommand.BehaviorData.class);
                if (behavior != null) mSdkBridge.runBehavior(behavior);
            } else if (isTopic(topic, "cmd/vision") || isTopic(topic, "vision")) {
                InteractCommand cmd = mGson.fromJson(message, InteractCommand.class);
                if (cmd != null && cmd.vision != null) {
                    mSdkBridge.runVision(cmd.vision.action, cmd.vision.interval_ms,
                            cmd.vision.track_id, cmd.vision.debug_preview);
                } else if (isTopic(topic, "vision")) {
                    handleGatewayVisionCommand(message);
                }
            } else if (isTopic(topic, "cmd/youtube")) {
                InteractCommand.YouTubeData youtube = mGson.fromJson(message, InteractCommand.YouTubeData.class);
                playYoutubeAndDance(youtube);
            } else if (isTopic(topic, "audio")) {
                handleGatewayAudioCommand(message);
            } else if (isTopic(topic, "movement")) {
                handleGatewayMovementCommand(message);
            } else if (isTopic(topic, "ping")) {
                publishStatus("status", "{\"status\":\"ok\",\"version\":\"ZenboClient-" + BuildConfig.VERSION_NAME + "\",\"topic_prefix\":\"" + mTopicPrefix + "\"}");
            }
        } catch (Exception e) {
            Log.e(TAG, "Error handling MQTT message: " + e.getMessage(), e);
        }
    }

    private boolean isRedundantLegacyLeaf(String topic) {
        if (System.currentTimeMillis() > mIgnoreLegacyLeafUntilMs) return false;
        return isTopic(topic, "cmd/speak")
                || isTopic(topic, "cmd/expression")
                || isTopic(topic, "cmd/motion")
                || isTopic(topic, "cmd/head")
                || isTopic(topic, "cmd/head_sequence")
                || isTopic(topic, "cmd/action")
                || isTopic(topic, "cmd/lights")
                || isTopic(topic, "cmd/emotional")
                || isTopic(topic, "cmd/remote")
                || isTopic(topic, "cmd/behavior")
                || isTopic(topic, "cmd/vision")
                || isTopic(topic, "cmd/youtube");
    }

    private boolean isTopic(String actualTopic, String suffix) {
        return (mTopicPrefix + "/" + suffix).equals(actualTopic);
    }

    private void handleGatewayAudioCommand(String message) {
        try {
            InteractCommand cmd = mGson.fromJson(message, InteractCommand.class);
            if (cmd == null) return;

            if (cmd.audioBase64 != null && !cmd.audioBase64.isEmpty()) {
                mAudioPlayer.playBytes(Base64.decode(cmd.audioBase64, Base64.DEFAULT), actionDoneListener());
            } else if (cmd.text != null && !cmd.text.isEmpty()) {
                if (cmd.face != null && !cmd.face.isEmpty()) {
                    mSdkBridge.setExpression(cmd.face);
                }

                notifySpeechStatus(cmd.text, "กำลังเตรียมเสียงภาษาไทย...");
                TtsClient.synthesize(cmd.text, cmd.voiceProfile, cmd.voice, cmd.age, cmd.speed,
                        new TtsClient.OnTtsResult() {
                    @Override
                    public void onSuccess(byte[] wavBytes) {
                        notifySpeechStatus(cmd.text, "กำลังพูด");
                        mAudioPlayer.playBytes(wavBytes, actionDoneListener(cmd.text));
                    }

                    @Override
                    public void onError(String errMsg) {
                        // Do not silently switch to RobotAPI speech: it does not
                        // guarantee a Thai voice and hides a Thai TTS outage.
                        Log.e(TAG, "Thai TTS failed: " + errMsg);
                        notifySpeechStatus(cmd.text, "พูดไม่สำเร็จ");
                        publishStatus("tts", "{\"state\":\"ERROR\",\"message\":\""
                                + escapeJson(errMsg) + "\"}");
                    }
                });
            } else if (cmd.audioUrl != null && !cmd.audioUrl.isEmpty()) {
                mAudioPlayer.playStream(cmd.audioUrl, new AudioPlaybackManager.OnAudioFinishListener() {
                    @Override
                    public void onFinished() {
                        publishStatus("action_done", "{\"status\":\"SUCCESS\",\"type\":\"speak\"}");
                    }
                });
            }
        } catch (Exception e) {
            Log.e(TAG, "handleGatewayAudioCommand failed: " + e.getMessage(), e);
        }
    }

    private void handleGatewayMovementCommand(String message) {
        try {
            InteractCommand cmd = mGson.fromJson(message, InteractCommand.class);
            if (cmd == null) return;

            if (cmd.action != null && "dance".equals(cmd.action.actionType)) {
                if (cmd.action.actionId != 0) {
                    mSdkBridge.playAction(cmd.action.actionId);
                }
            } else if (cmd.motion != null) {
                mSdkBridge.moveBody(cmd.motion.x, cmd.motion.y, cmd.motion.theta, cmd.motion.speed);
            } else if (cmd.head != null) {
                mSdkBridge.moveHead(cmd.head.yaw, cmd.head.pitch, cmd.head.speed);
            } else if (cmd.face != null) {
                mSdkBridge.setExpression(cmd.face);
            } else if (cmd.wheelLights != null) {
                mSdkBridge.controlWheelLights(cmd.wheelLights);
            }
        } catch (Exception e) {
            Log.e(TAG, "handleGatewayMovementCommand failed: " + e.getMessage(), e);
        }
    }

    private AudioPlaybackManager.OnAudioFinishListener actionDoneListener() {
        return actionDoneListener("");
    }

    private AudioPlaybackManager.OnAudioFinishListener actionDoneListener(final String spokenText) {
        return new AudioPlaybackManager.OnAudioFinishListener() {
            @Override
            public void onFinished() {
                if (spokenText != null && !spokenText.isEmpty()) {
                    notifySpeechStatus(spokenText, "พูดจบแล้ว");
                }
                publishStatus("action_done", "{\"status\":\"SUCCESS\",\"type\":\"speak\"}");
            }
        };
    }

    private void handleGatewayVisionCommand(String message) {
        try {
            InteractCommand cmd = mGson.fromJson(message, InteractCommand.class);
            if (cmd == null) return;

            if (cmd.vision == null) {
                InteractCommand.VisionData vision = mGson.fromJson(message, InteractCommand.VisionData.class);
                if (vision != null && vision.action != null) {
                    mSdkBridge.runVision(vision.action, vision.interval_ms, vision.track_id, vision.debug_preview);
                }
                return;
            }

            if ("photo".equals(cmd.vision.action)) {
                // photo action not directly supported in SDK, skip
            } else if ("follow".equals(cmd.vision.action)) {
                // follow not in SDK
            } else if ("track".equals(cmd.vision.action)) {
                // track not in SDK
            } else if ("unfollow".equals(cmd.vision.action)) {
                // unfollow not in SDK
            } else if (cmd.vision.action != null) {
                mSdkBridge.runVision(cmd.vision.action, cmd.vision.interval_ms,
                        cmd.vision.track_id, cmd.vision.debug_preview);
            }
        } catch (Exception e) {
            Log.e(TAG, "handleGatewayVisionCommand failed: " + e.getMessage(), e);
        }
    }

    private void executeInteractCommand(final InteractCommand cmd) {
        if (cmd == null) return;
        publishStatus("command", "{\"state\":\"RECEIVED\",\"id\":\""
                + escapeJson(cmd.commandId) + "\"}");

        // 1. เปลี่ยนสีหน้า
        if (cmd.face != null && !cmd.face.isEmpty()) {
            mSdkBridge.setExpression(cmd.face);
        }

        // 2. สั่งไฟ LED ล้อ
        if (cmd.wheelLights != null) {
            publishStatus("wheel_lights", "{\"state\":\"REQUESTED\",\"mode\":\""
                    + escapeJson(cmd.wheelLights.mode) + "\"}");
            mSdkBridge.controlWheelLights(cmd.wheelLights);
        }

        // 3. สั่งเคลื่อนที่
        if (cmd.motion != null) {
            mSdkBridge.moveBody(cmd.motion.x, cmd.motion.y, cmd.motion.theta, cmd.motion.speed);
        }

        // 4. สั่งหันศีรษะ
        if (cmd.head != null) {
            mSdkBridge.moveHead(cmd.head.yaw, cmd.head.pitch, cmd.head.speed);
        }
        if (cmd.headSequence != null) {
            playHeadSequence(cmd.headSequence);
        }

        // 5. สั่ง Action ท่าทาง
        if (cmd.action != null) {
            if (cmd.action.stop) {
                mSdkBridge.cancelCurrentAction();
                publishStatus("action", "{\"state\":\"CANCEL_REQUESTED\"}");
            } else {
                publishStatus("action", "{\"state\":\"REQUESTED\",\"id\":"
                        + cmd.action.actionId + "}");
                mSdkBridge.playAction(cmd.action.actionId);
            }
        }

        if (cmd.emotionalAction != null) {
            mSdkBridge.playEmotionalAction(cmd.emotionalAction);
        }

        if (cmd.remoteControl != null) {
            handleRemoteControl(cmd.remoteControl);
        }

        if (cmd.behavior != null) {
            mSdkBridge.runBehavior(cmd.behavior);
        }

        if (cmd.vision != null) {
            mSdkBridge.runVision(cmd.vision.action, cmd.vision.interval_ms,
                    cmd.vision.track_id, cmd.vision.debug_preview);
        }

        if (cmd.youtube != null) {
            playYoutubeAndDance(cmd.youtube);
        }

        if (cmd.navigation != null) {
            openNavigationDisplay(cmd.navigation);
        }

        // 6. Text is authoritative: always synthesize it through the Thai TTS
        // service configured in TtsClient.  Core commands may also contain an
        // audio_url, but that URL is a convenience cache and can be unreachable
        // from the robot network.  Prefer the on-LAN service at :8025 so Thai
        // speech is deterministic.
        if (cmd.text != null && !cmd.text.isEmpty()) {
            notifySpeechStatus(cmd.text, "กำลังเตรียมเสียงภาษาไทย...");
            publishStatus("tts", "{\"state\":\"REQUESTED\",\"service\":\"10.101.118.149:8025\""
                    + ",\"voice_profile\":\"" + escapeJson(cmd.voiceProfile) + "\"}");
            TtsClient.synthesize(cmd.text, cmd.voiceProfile, cmd.voice, cmd.age, cmd.speed,
                    new TtsClient.OnTtsResult() {
                @Override
                public void onSuccess(byte[] wavBytes) {
                    publishStatus("tts", "{\"state\":\"RECEIVED\",\"bytes\":" + wavBytes.length + "}");
                    notifySpeechStatus(cmd.text, "กำลังพูด");
                    mAudioPlayer.playBytes(wavBytes, actionDoneListener(cmd.text));
                }

                @Override
                public void onError(String message) {
                    Log.e(TAG, "Thai TTS failed: " + message);
                    notifySpeechStatus(cmd.text, "พูดไม่สำเร็จ");
                    publishStatus("tts", "{\"state\":\"ERROR\",\"message\":\""
                            + escapeJson(message) + "\"}");
                }
            });
        } else if (cmd.audioUrl != null && !cmd.audioUrl.isEmpty()) {
            mAudioPlayer.playStream(cmd.audioUrl, new AudioPlaybackManager.OnAudioFinishListener() {
                @Override
                public void onFinished() {
                    if (mMqttManager != null) {
                        publishStatus("action_done", "{\"status\":\"SUCCESS\",\"type\":\"speak\"}");
                    }
                }
            });
        }
    }

    private void playHeadSequence(final InteractCommand.HeadData[] sequence) {
        mHeadSequenceHandler.removeCallbacksAndMessages(null);
        if (sequence == null || sequence.length == 0 || mSdkBridge == null) return;
        mHeadSequenceHandler.post(new Runnable() {
            private int index;

            @Override
            public void run() {
                if (index >= sequence.length) return;
                InteractCommand.HeadData step = sequence[index++];
                mSdkBridge.moveHead(step.yaw, step.pitch, step.speed);
                if (index < sequence.length) {
                    mHeadSequenceHandler.postDelayed(this, Math.max(0, step.delayMs));
                }
            }
        });
    }

    private void playYoutubeAndDance(final InteractCommand.YouTubeData youtube) {
        if (youtube == null || youtube.url == null || youtube.url.trim().isEmpty()) {
            publishStatus("youtube", "{\"state\":\"REJECTED\",\"message\":\"missing_url\"}");
            return;
        }
        cancelDanceLoop();
        try {
            Intent intent = new Intent(this, YouTubePlayerActivity.class);
            intent.putExtra(YouTubePlayerActivity.EXTRA_VIDEO_URL, youtube.url);
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
            publishStatus("youtube", "{\"state\":\"PLAYER_LAUNCH_REQUESTED\",\"url\":\"" + escapeJson(youtube.url) + "\"}");
            startActivity(intent);
            publishStatus("youtube", "{\"state\":\"PLAYER_ACTIVITY_STARTED\",\"url\":\"" + escapeJson(youtube.url) + "\"}");
        } catch (Exception exception) {
            Log.e(TAG, "Unable to open YouTube: " + exception.getMessage(), exception);
            publishStatus("youtube", "{\"state\":\"ERROR\",\"message\":\"" + escapeJson(exception.getMessage()) + "\"}");
            return;
        }
        if (!youtube.loopDance || youtube.danceActionIds == null || youtube.danceActionIds.length == 0) return;

        final int[] actionIds = youtube.danceActionIds;
        final long stopAtMs = youtube.durationSeconds == null ? 0L
                : System.currentTimeMillis() + youtube.durationSeconds * 1000L;
        mDanceLoopRunnable = new Runnable() {
            private int actionIndex;

            @Override
            public void run() {
                if (stopAtMs > 0L && System.currentTimeMillis() >= stopAtMs) {
                    publishStatus("youtube", "{\"state\":\"DANCE_DURATION_FINISHED\"}");
                    return;
                }
                if (mSdkBridge == null) return;
                int actionId = actionIds[actionIndex++ % actionIds.length];
                publishStatus("action", "{\"state\":\"DANCE_REQUESTED\",\"id\":" + actionId + "}");
                mSdkBridge.playAction(actionId);
                mDanceHandler.postDelayed(this, 5000L);
            }
        };
        mDanceHandler.post(mDanceLoopRunnable);
        publishStatus("youtube", "{\"state\":\"DANCE_LOOP_STARTED\"}");
    }

    private void openNavigationDisplay(final InteractCommand.NavigationData navigation) {
        if (navigation == null || navigation.displayUrl == null) return;
        String url = navigation.displayUrl.trim();
        if (!url.startsWith("http://10.101.118.149:8032/")) {
            publishStatus("navigation", "{\"state\":\"REJECTED\",\"reason\":\"untrusted_url\"}");
            return;
        }
        try {
            Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(intent);
            publishStatus("navigation", "{\"state\":\"OPENED\",\"url\":\"" + escapeJson(url) + "\"}");
        } catch (Exception exception) {
            Log.e(TAG, "Unable to open navigation display: " + exception.getMessage(), exception);
            publishStatus("navigation", "{\"state\":\"ERROR\"}");
        }
    }

    private void cancelDanceLoop() {
        if (mDanceLoopRunnable != null) {
            mDanceHandler.removeCallbacks(mDanceLoopRunnable);
            mDanceLoopRunnable = null;
        }
    }

    private void cancelRobotSequences() {
        mHeadSequenceHandler.removeCallbacksAndMessages(null);
        cancelDanceLoop();
        cancelRemoteControlSafety();
    }

    private void handleRemoteControl(InteractCommand.RemoteControlData remote) {
        if (remote == null || mSdkBridge == null) return;
        mSdkBridge.remoteControl(remote);

        if (remote.body != null) {
            mRemoteControlSafetyHandler.removeCallbacks(mBodyRemoteStopRunnable);
            if (!"STOP".equalsIgnoreCase(remote.body.trim())) {
                mRemoteControlSafetyHandler.postDelayed(mBodyRemoteStopRunnable, REMOTE_CONTROL_DEADMAN_MS);
            }
        }
        if (remote.head != null) {
            mRemoteControlSafetyHandler.removeCallbacks(mHeadRemoteStopRunnable);
            if (!"STOP".equalsIgnoreCase(remote.head.trim())) {
                mRemoteControlSafetyHandler.postDelayed(mHeadRemoteStopRunnable, REMOTE_CONTROL_DEADMAN_MS);
            }
        }
    }

    private void sendRemoteBodyStop() {
        InteractCommand.RemoteControlData stop = new InteractCommand.RemoteControlData();
        stop.body = "STOP";
        if (mSdkBridge != null) mSdkBridge.remoteControl(stop);
        publishStatus("remote", "{\"body\":\"STOP\",\"reason\":\"deadman_timeout\"}");
    }

    private void sendRemoteHeadStop() {
        InteractCommand.RemoteControlData stop = new InteractCommand.RemoteControlData();
        stop.head = "STOP";
        if (mSdkBridge != null) mSdkBridge.remoteControl(stop);
        publishStatus("remote", "{\"head\":\"STOP\",\"reason\":\"deadman_timeout\"}");
    }

    private void cancelRemoteControlSafety() {
        mRemoteControlSafetyHandler.removeCallbacks(mBodyRemoteStopRunnable);
        mRemoteControlSafetyHandler.removeCallbacks(mHeadRemoteStopRunnable);
    }

    @Override
    public void onConnectionStatusChanged(boolean isConnected, String statusMsg) {
        Log.d(TAG, "Status changed: " + statusMsg);
        String state = isConnected ? "connected" : "disconnected";
        publishStatus("connection", "{\"state\":\"" + state + "\",\"message\":\"" + escapeJson(statusMsg) + "\"}");
        if (isConnected) startHeartbeat();
        else stopHeartbeat();
        if (mConnectionStatusListener != null) {
            mConnectionStatusListener.onConnectionStatusChanged(isConnected, statusMsg);
        }
    }

    private void publishStatus(String topicSuffix, String payload) {
        if (mMqttManager != null) {
            if ("connection".equals(topicSuffix)) {
                payload = payload.substring(0, payload.length() - 1)
                        + ",\"robot_slug\":\"" + escapeJson(mTopicPrefix) + "\""
                        + ",\"client_id\":\"" + escapeJson(mMqttManager.getClientId()) + "\""
                        + ",\"client_ip\":\"" + escapeJson(getClientIpAddress()) + "\"}";
            }
            mMqttManager.publish(mTopicPrefix + "/status/" + topicSuffix, payload,
                    "connection".equals(topicSuffix) ? 1 : 1,
                    "connection".equals(topicSuffix));
        }
    }

    private void notifySpeechStatus(String text, String state) {
        if (mSpeechStatusListener != null) {
            mSpeechStatusListener.onSpeechStatusChanged(text == null ? "" : text, state);
        }
    }

    private void startHeartbeat() {
        stopHeartbeat();
        cancelRobotSequences();
        mHeartbeatRunning = true;
        mHeartbeatHandler.post(mHeartbeatRunnable);
    }

    private void stopHeartbeat() {
        mHeartbeatRunning = false;
        mHeartbeatHandler.removeCallbacks(mHeartbeatRunnable);
    }

    private void publishHeartbeat() {
        if (mMqttManager == null) return;
        String robotSlug = mTopicPrefix.startsWith("zenbo/")
                ? mTopicPrefix.substring("zenbo/".length()) : mTopicPrefix;
        String payload = "{\"state\":\"connected\",\"app\":\"Zenbo Client Bridge\""
                + ",\"version_name\":\"" + BuildConfig.VERSION_NAME + "\""
                + ",\"robot_slug\":\"" + escapeJson(robotSlug) + "\""
                + ",\"client_id\":\"" + escapeJson(mMqttManager.getClientId()) + "\""
                + ",\"client_ip\":\"" + escapeJson(getClientIpAddress()) + "\""
                + ",\"topic_prefix\":\"" + escapeJson(mTopicPrefix) + "\""
                + ",\"timestamp_ms\":" + System.currentTimeMillis() + "}";
        mMqttManager.publish(mTopicPrefix + "/status/heartbeat", payload, 1, true);
    }

    private String getClientIpAddress() {
        WifiManager wifi = (WifiManager) getApplicationContext().getSystemService(WIFI_SERVICE);
        if (wifi == null) return "unknown";
        WifiInfo info = wifi.getConnectionInfo();
        if (info == null || info.getIpAddress() == 0) return "unknown";
        int ip = info.getIpAddress();
        return (ip & 0xff) + "." + ((ip >> 8) & 0xff) + "."
                + ((ip >> 16) & 0xff) + "." + ((ip >> 24) & 0xff);
    }

    private String escapeJson(String value) {
        return value == null ? "" : value.replace("\\", "\\\\").replace("\"", "\\\"");
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationChannel channel = new NotificationChannel(
                    CHANNEL_ID,
                    "Zenbo Background Service",
                    NotificationManager.IMPORTANCE_LOW
            );
            NotificationManager manager = getSystemService(NotificationManager.class);
            if (manager != null) {
                manager.createNotificationChannel(channel);
            }
        }
    }

    @Override
    public IBinder onBind(Intent intent) {
        return mBinder;
    }

    @Override
    public void onDestroy() {
        stopHeartbeat();
        cancelRemoteControlSafety();
        if (mMqttManager != null) mMqttManager.disconnect();
        if (mSdkBridge != null) mSdkBridge.release();
        if (mAudioPlayer != null) mAudioPlayer.stop();
        if (mYouTubeStatusReceiverRegistered) {
            unregisterReceiver(mYouTubeStatusReceiver);
            mYouTubeStatusReceiverRegistered = false;
        }
        super.onDestroy();
        mConnectionStatusListener = null;
        mSpeechStatusListener = null;
    }
}
