package com.hackathon.zenboclient.service;

import com.hackathon.zenboclient.drive.SpeedLevelDriveController;
import com.hackathon.zenboclient.drive.SdkDriveActuator;
import com.hackathon.zenboclient.drive.RelativeMotionEnvelopeMapper;
import android.os.SystemClock;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

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
import android.os.BatteryManager;
import android.util.Log;
import android.util.Base64;
import android.net.wifi.WifiInfo;
import android.net.wifi.WifiManager;
import androidx.core.app.NotificationCompat;
import com.google.gson.Gson;
import com.hackathon.zenboclient.BuildConfig;
import com.hackathon.zenboclient.YouTubePlayerActivity;
import com.hackathon.zenboclient.robot.ZenboSafetyMonitor;
import com.hackathon.zenboclient.audio.AudioPlaybackManager;
import com.hackathon.zenboclient.audio.TtsClient;
import com.hackathon.zenboclient.camera.CameraSessionManager;
import com.hackathon.zenboclient.model.InteractCommand;
import com.hackathon.zenboclient.mqtt.MqttManager;
import com.hackathon.zenboclient.mqtt.MqttProvisioningClient;
import com.hackathon.zenboclient.robot.ZenboSdkBridge;
import com.hackathon.zenboclient.robot.SpeechGestureController;
import com.hackathon.zenboclient.ui.ScreenTickerOverlay;
import com.hackathon.zenboclient.update.SemiAutomaticUpdateManager;
import android.text.TextUtils;
import java.io.File;
import com.asus.robotframework.API.results.DetectFaceResult;
import com.asus.robotframework.API.results.DetectPersonResult;
import com.asus.robotframework.API.results.GesturePointResult;
import java.util.List;
import java.util.UUID;

public class ZenboClientService extends Service implements MqttManager.MessageListener {
    private static final String TAG = "ZenboService";
    private static final String CHANNEL_ID = "zenbo_service_channel";
    private static final String NAVIGATION_SERVICE_URL_PREFIX = "http://10.101.118.149:8032/";
private static final String LIBRARY_MAP_URL = "https://lib.kku.ac.th/map/";
private static final String LIBRARY_RAG_URL = "https://lib.kku.ac.th/rag/";
    private static final long SAFETY_SPEECH_COOLDOWN_MS = 8000L;
    private final IBinder mBinder = new LocalBinder();
    private final Gson mGson = new Gson();

    public static final int BROKER_MODE_AUTO = 0;
    public static final int BROKER_MODE_LAN_ONLY = 1;
    public static final int BROKER_MODE_DOMAIN_ONLY = 2;

    private int mBrokerMode = BROKER_MODE_AUTO;
    private String mActiveEndpointType = "LAN";
    private boolean mIsFallbackAttempt = false;
    private int mConnectionFailureCount = 0;
    private long mLegacyMotionUntilMs;
    private SpeedLevelDriveController mRelativeController;
    private final ScheduledExecutorService mRelativeDeadline = Executors.newSingleThreadScheduledExecutor();
    private final Handler mFallbackHandler = new Handler(Looper.getMainLooper());

    private MqttManager mMqttManager;
    private boolean mMqttProvisioningInFlight;
    private MqttProvisioningClient.Connection mProvisionedMqttConnection;
    private ZenboSdkBridge mSdkBridge;
    private ZenboSafetyMonitor mSafetyMonitor;
    private AudioPlaybackManager mAudioPlayer;
    private CameraSessionManager mCameraSessionManager;
    private SpeechGestureController mSpeechGestureController;
    private ScreenTickerOverlay mScreenTickerOverlay;
    private ConnectionStatusListener mConnectionStatusListener;
    private SpeechStatusListener mSpeechStatusListener;
    private SafetyStatusListener mSafetyStatusListener;
    private SemiAutomaticUpdateManager mUpdateManager;
    private String mTopicPrefix = "zenbo";
    private final Handler mHeartbeatHandler = new Handler(Looper.getMainLooper());
    private final Handler mCommandHandler = new Handler(Looper.getMainLooper());
    private final Handler mHeadSequenceHandler = new Handler(Looper.getMainLooper());
    private final Handler mScenarioScriptHandler = new Handler(Looper.getMainLooper());
    private final Handler mInteractiveVisionHandler = new Handler(Looper.getMainLooper());
    private final Handler mDanceHandler = new Handler(Looper.getMainLooper());
    private final Handler mMotionGuardHandler = new Handler(Looper.getMainLooper());
    // Operator request: Start with safety mode completely disabled by default (unlocked wheels, guards off)
    private boolean mBaseMotionEnabled = true;
    private boolean mCollisionGuardEnabled = false;
    private boolean mFallGuardEnabled = false;
    private int mSpeechVolumePercent = 50;
    // Operator-supervised field mode: bounded one-shot movements while an
    // attendant is beside the robot. Deadman, emergency stop, and watchdog
    // remain mandatory safeguards.
    private float mMaxMotionDistanceM = 3.0f;
    // Operator-supervised field mode: allow full SDK speed by default.  Individual
    // movements are still bounded by distance and the motion watchdog.
    private int mMaxMotionSpeed = 7;
    private int mAutoStopMs = 10000;
    private long mLastSafetySpeechAtMs;
    private String mSafetyScreenTitle = "Operator Drive พร้อมใช้งาน";
    private String mSafetyScreenDetail = "ควบคุมโดยผู้ดูแล — ตรวจพื้นที่ก่อนสั่งเคลื่อนที่";
    private boolean mSafetyScreenDanger;
    // Kept independently from speech so an L8 run can prove that the base
    // watchdog stopped even when Thai TTS finishes before or after movement.
    private String mActiveMotionScenarioRunId;
    private final Runnable mMotionGuardStopRunnable = new Runnable() {
        @Override public void run() {
            if (mSdkBridge != null) mSdkBridge.emergencyStop();
            publishStatus("safety", "{\"state\":\"WATCHDOG_STOP\"}");
            publishScenarioStatus(mActiveMotionScenarioRunId, "MOTION_COMPLETED");
            mActiveMotionScenarioRunId = null;
        }
    };
    // Keep the deadman at 2000ms so network jitter in Wi-Fi does not cut
    // continuous remoteControlBody mid-drive, while still stopping promptly on release.
    private static final long REMOTE_CONTROL_DEADMAN_MS = 2000L;
    // A discrete motion packet can arrive after a joystick packet. Keep the
    // joystick as the sole owner of the base until its deadman expires.
    private long mRemoteBodyControlActiveUntilMs;
    private String mLastRemoteBodyDirection;
    private String mLastRemoteHeadDirection;
    private final Handler mRemoteControlSafetyHandler = new Handler(Looper.getMainLooper());
    private final Runnable mBodyRemoteStopRunnable = new Runnable() {
        @Override public void run() { sendRemoteBodyStop(); }
    };
    private final Runnable mHeadRemoteStopRunnable = new Runnable() {
        @Override public void run() { sendRemoteHeadStop(); }
    };
    private Runnable mDanceLoopRunnable;
    private InteractCommand.InteractiveScenarioData mActiveInteractiveScenario;
    private String mInteractiveScenarioRunId;
    private Runnable mInteractiveVisionTimeout;
    private InteractCommand.InteractiveSequenceData mActiveInteractiveSequence;
    private String mInteractiveSequenceRunId;
    private int mInteractiveSequenceStage;
    private boolean mYouTubeStatusReceiverRegistered;
    private final BroadcastReceiver mYouTubeStatusReceiver = new BroadcastReceiver() {
        @Override public void onReceive(Context context, Intent intent) {
            if (!YouTubePlayerActivity.ACTION_STATUS.equals(intent.getAction())) return;
            String state = intent.getStringExtra(YouTubePlayerActivity.EXTRA_STATE);
            String message = intent.getStringExtra(YouTubePlayerActivity.EXTRA_MESSAGE);
            // Never leave an optional dance loop running when playback ends,
            // fails, or needs a human tap.  The player telemetry is the only
            // reliable lifecycle signal available across Zenbo firmware builds.
            if ("ENDED".equals(state) || "ERROR".equals(state)
                    || "REJECTED".equals(state) || "PLAYER_TIMEOUT".equals(state)) {
                cancelDanceLoop();
            }
            publishStatus("youtube", "{\"state\":\"" + escapeJson(state)
                    + "\",\"message\":\"" + escapeJson(message) + "\"}");
        }
    };
    private boolean mHeartbeatRunning;
    private final String mBootSessionId = UUID.randomUUID().toString();
    private long mHeartbeatSeq;
    private long mSafetyPolicyEpoch;
    private volatile String mInstalledApkDigestState = "PENDING";
    private volatile String mInstalledApkSha256 = "";
    private volatile String mInstalledApkDigestKey = "";
    // The core API publishes one composite command and matching legacy leaves.
    // Ignore the immediate duplicate leaves; emergency controls are never ignored.
    private volatile long mIgnoreLegacyLeafUntilMs;
    private volatile String mActiveScenarioRunId;
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

/** Result callback for a locally initiated, user-confirmed update notice. */
public interface UpdateAnnouncementListener {
void onCompleted();
void onFailed(String message);
}

    /** Separate persistent safety HUD from transient command/speech text. */
    public interface SafetyStatusListener {
        void onSafetyStatusChanged(String title, String detail, boolean danger);
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
        startInstalledApkDigest();

        mSdkBridge = new ZenboSdkBridge();
        mRelativeController = new SpeedLevelDriveController(new SdkDriveActuator(mSdkBridge),
                () -> SystemClock.elapsedRealtime(),
                (task, delay) -> mRelativeDeadline.schedule(task, Math.max(0, delay), TimeUnit.MILLISECONDS));
        mRelativeController.setStopListener((command, reason) -> {
            java.util.Map<String, Object> ack = new java.util.LinkedHashMap<>();
            ack.put("command_id", command.commandId);
            ack.put("control_mode", "RELATIVE_BODY");
            ack.put("state", "SDK_STOP_REQUESTED");
            ack.put("stop_reason", reason);
            ack.put("requested_speed_level", command.requestedSpeedLevel);
            ack.put("policy_max_speed_level", command.policyMaxSpeedLevel);
            ack.put("effective_speed_level", null);
            ack.put("received_at_ms", System.currentTimeMillis());
            ack.put("physical_stop_verified", false);
            publishStatus("motion_ack", new com.google.gson.GsonBuilder().serializeNulls().create().toJson(ack));
        });
        try {
            mSdkBridge.init(getApplicationContext(), new ZenboSdkBridge.ActionCallback() {
                @Override
                public void onActionState(String status) {
                    publishStatus("robot_state", "{\"state\":\"" + status + "\"}");
                    if ("INIT_COMPLETE".equals(status)) {
                        // Auto-enable operator drive so the robot is controllable
                        // from LIFF without a manual unlock step.  Guards stay off;
                        // motion is still bounded by distance/watchdog.
                        applyDefaultOperatorSafety();
                    }
                }

                @Override
                public void onVisionResult(String action, String payload) {
                    // L2/L3 use the raw SDK result only on-device to select a
                    // response.  Do not forward face IDs or gesture vectors
                    // while an interactive scenario is active.
                    if (isInteractiveVisionSignal(action)) {
                        publishStatus("vision", "{\"action\":\"" + escapeJson(action)
                                + "\",\"detected\":true}");
                    } else {
                        publishStatus("vision", payload);
                    }
                    handleInteractiveVisionResult(action, payload);
                    handleInteractiveSequenceVisionResult(action, payload);
                }

                @Override
                public void onError(String code, String message) {
                    publishStatus("error", "{\"code\":\"" + code + "\",\"message\":\"" + escapeJson(message) + "\"}");
                }
            });
        } catch (Exception e) {
            Log.e(TAG, "Failed to initialize ZenboSdkBridge: " + e.getMessage(), e);
        }

        // Create audio before subscribing to sensors: a first sensor event can
        // arrive immediately on some Zenbo firmware builds.
        mAudioPlayer = new AudioPlaybackManager(this);
        mCameraSessionManager = new CameraSessionManager(this);
        mSpeechGestureController = new SpeechGestureController(mSdkBridge);
        mScreenTickerOverlay = new ScreenTickerOverlay(this);
        mCameraSessionManager.setStatusPublisher(new CameraSessionManager.StatusPublisher() {
            @Override
            public void publishCameraStatus(String state, org.json.JSONObject detail) {
                try {
                    detail.put("state", state);
                    publishStatus("camera", detail.toString());
                } catch (org.json.JSONException e) {
                    Log.e(TAG, "Failed to publish camera status", e);
                }
            }
        });
        if (BuildConfig.SAFETY_MONITOR_ENABLED) {
            mSafetyMonitor = new ZenboSafetyMonitor(getApplicationContext(), new ZenboSafetyMonitor.Listener() {
            @Override public void onSafetyEvent(String state, String detail) {
                publishStatus("safety", "{\"state\":\"" + escapeJson(state) + "\",\"detail\":\"" + escapeJson(detail) + "\"}");
                if ("SENSORS_READY".equals(state)) {
                    notifySafetyStatus("Safety Guard พร้อม", detail, false);
                } else {
                    notifySafetyStatus("Safety Guard: " + state, detail, false);
                }
            }
            @Override public void onSafetyBreach(String reason, float meters) {
                // Sensor callbacks can repeat several times per second. Claim
                // the safety announcement slot before stopping audio, otherwise
                // a duplicate callback cuts the first syllable and is then
                // suppressed by the cooldown.
                boolean announceSafetySpeech = claimSafetySpeechSlot(reason);
                cancelRobotSequences();
                if (announceSafetySpeech && mAudioPlayer != null) mAudioPlayer.stop();
                if (mSdkBridge != null) mSdkBridge.emergencyStop();
                publishScenarioStatus(mActiveMotionScenarioRunId, "SAFETY_STOPPED");
                mActiveMotionScenarioRunId = null;
                publishStatus("safety", "{\"state\":\"SENSOR_STOP\",\"reason\":\"" + escapeJson(reason) + "\",\"meters\":" + meters + "}");
                notifySafetyStatus("หยุดฉุกเฉิน: " + reason,
                        "ตรวจพบที่ " + String.format(java.util.Locale.US, "%.3f", meters) + " เมตร", true);
                if (announceSafetySpeech) announceSafetyBreach(reason, meters);
            }
            @Override public void onSafetySample(String sensor, float meters) {
                publishStatus("safety", "{\"state\":\"SENSOR_SAMPLE\",\"sensor\":\"" + escapeJson(sensor) + "\",\"meters\":" + meters + "}");
                if (!mSafetyScreenDanger) {
                    notifySafetyStatus("Safety Guard พร้อม", sensor + ": "
                            + String.format(java.util.Locale.US, "%.3f", meters) + " เมตร", false);
                }
            }
            });
            mSafetyMonitor.start();
        } else {
            // Field builds without a safety monitor run in operator-supervised
            // mode so LIFF manual drive works on legacy Android images.
            mBaseMotionEnabled = true;
            mCollisionGuardEnabled = false;
            mFallGuardEnabled = false;
            mMaxMotionDistanceM = 0.75f;
            mMaxMotionSpeed = 7;
            notifySafetyStatus("Operator Drive", "ปลดล็อกล้อแล้ว — ควบคุมด้วย LIFF ได้", false);
            publishStatus("safety", "{\"state\":\"MONITOR_DISABLED\",\"base_motion_enabled\":true}");
        }
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
        if (mMqttProvisioningInFlight) return;

        if (mBrokerMode == BROKER_MODE_DOMAIN_ONLY) {
            Log.i(TAG, "Broker mode is DOMAIN_ONLY; connecting to Domain WSS");
            connectDomainWssMqtt("โหมดบังคับ Domain WSS");
            return;
        }

        if (mBrokerMode == BROKER_MODE_LAN_ONLY) {
            Log.i(TAG, "Broker mode is LAN_ONLY; connecting to Direct LAN :1884");
            connectDirectMqtt("โหมดบังคับ LAN :1884");
            return;
        }

        // AUTO Mode
        if (mIsFallbackAttempt) {
            Log.i(TAG, "AUTO mode: fallback in progress, connecting to Domain WSS");
            connectDomainWssMqtt("AUTO โหมด: สลับมายัง Domain WSS");
            return;
        }

        // Field deployments on the campus LAN prefer a direct TCP connection to
        // the private MQTT listener at 10.101.118.149:1884.  Skip the HTTPS
        // provisioning round-trip when the operator has supplied direct broker
        // credentials at build time.
        if (BuildConfig.SKIP_MQTT_PROVISIONING && directMqttCredentialsConfigured()) {
            Log.i(TAG, "AUTO mode: connecting to Direct LAN MQTT first");
            connectDirectMqtt("AUTO โหมด: เชื่อมต่อ LAN :1884");
            return;
        }

        mMqttProvisioningInFlight = true;
        // Legacy Zenbo Android images on the campus LAN should provision over
        // the local Core address directly.  This avoids two public TLS retries
        // before the already-authenticated LAN MQTT remap to :1884.
        String[] httpsEndpoints = BuildConfig.FORCE_LAN_MQTT ? new String[0] : new String[] {
                BuildConfig.MQTT_PROVISIONING_URL,
                BuildConfig.MQTT_LIBN_PROVISIONING_URL
        };
        MqttProvisioningClient.fetchWithFallbackChainAsync(httpsEndpoints,
                BuildConfig.MQTT_LAN_PROVISIONING_URL,
                BuildConfig.DEVICE_PROVISIONING_TOKEN, BuildConfig.ROBOT_SLUG,
                new MqttProvisioningClient.Callback() {
                    @Override public void onSuccess(MqttProvisioningClient.Connection connection) {
                        mMqttProvisioningInFlight = false;
                        MqttProvisioningClient.Connection runtime = remapConnectionForLanIfNeeded(connection);
                        mProvisionedMqttConnection = runtime;
                        connectProvisionedMqtt(runtime);
                    }

                    @Override public void onFailure(String safeMessage) {
                        mMqttProvisioningInFlight = false;
                        Log.w(TAG, safeMessage);
                        connectLanCompatibilityMqtt(safeMessage);
                    }
                });
    }

    /**
     * Core may return a public WSS contract even when provisioning happened over
     * campus HTTP.  Remap to the authenticated LAN TCP listener so legacy
     * Android images can connect without modern TLS.
     */
    private MqttProvisioningClient.Connection remapConnectionForLanIfNeeded(
            MqttProvisioningClient.Connection connection) {
        if ((!connection.usedLanFallback && !BuildConfig.FORCE_LAN_MQTT)
                || !needsLanBrokerRemap(connection)) return connection;
        String host = BuildConfig.DIRECT_MQTT_HOST.trim();
        if (host.isEmpty()) return connection;
        Log.i(TAG, "Remapping public broker contract to LAN TCP listener");
        return MqttProvisioningClient.Connection.remapped(host, BuildConfig.DIRECT_MQTT_PORT, "tcp",
                connection.username, connection.token, connection.topicPrefix);
    }

    private boolean needsLanBrokerRemap(MqttProvisioningClient.Connection connection) {
        String host = connection.host == null ? "" : connection.host.trim().toLowerCase();
        String transport = connection.transport == null ? "" : connection.transport.trim().toLowerCase();
        return host.contains("libgate") || host.contains("libn.")
                || "wss".equals(transport) || "ws".equals(transport) || "ssl".equals(transport);
    }

    /**
     * Some Zenbo Android 7 images reject modern public TLS certificates.  Keep
     * the public WSS route as the primary path, then use this authenticated
     * private-LAN listener only when HTTPS provisioning itself is unavailable.
     */
    private void connectLanCompatibilityMqtt(String provisioningFailure) {
        if (!directMqttCredentialsConfigured()) {
            if (mConnectionStatusListener != null) {
                mConnectionStatusListener.onConnectionStatusChanged(false, provisioningFailure);
            }
            return;
        }
        if (mConnectionStatusListener != null) {
            mConnectionStatusListener.onConnectionStatusChanged(false,
                    "HTTPS provisioning ใช้ไม่ได้ — กำลังเชื่อมต่อ LAN compatibility");
        }
        connectDirectMqtt("HTTPS provisioning ใช้ไม่ได้ — กำลังเชื่อมต่อ LAN compatibility");
    }

    private boolean directMqttCredentialsConfigured() {
        return !BuildConfig.DIRECT_MQTT_HOST.trim().isEmpty()
                && !BuildConfig.DIRECT_MQTT_USERNAME.trim().isEmpty()
                && !BuildConfig.DIRECT_MQTT_TOKEN.isEmpty();
    }

    private String buildTopicPrefix() {
        String topicPrefix = BuildConfig.DIRECT_MQTT_TOPIC_PREFIX.trim();
        if (topicPrefix.isEmpty()) {
            topicPrefix = "zenbo/" + BuildConfig.ROBOT_SLUG;
        } else if (!topicPrefix.endsWith("/")) {
            topicPrefix = topicPrefix + "/" + BuildConfig.ROBOT_SLUG;
        } else {
            topicPrefix = topicPrefix + BuildConfig.ROBOT_SLUG;
        }
        return topicPrefix;
    }

    private void connectDirectMqtt(String reason) {
        mActiveEndpointType = "LAN";
        mTopicPrefix = buildTopicPrefix();
        if (mMqttManager != null) mMqttManager.disconnect();
        Log.i(TAG, "Connecting to Direct LAN MQTT at " + BuildConfig.DIRECT_MQTT_HOST
                + ":" + BuildConfig.DIRECT_MQTT_PORT + " (" + reason + ")");
        if (mConnectionStatusListener != null) {
            mConnectionStatusListener.onConnectionStatusChanged(false,
                    "กำลังเชื่อมต่อ LAN :1884 (" + BuildConfig.DIRECT_MQTT_HOST + ")...");
        }
        mMqttManager = new MqttManager(this, BuildConfig.DIRECT_MQTT_HOST,
                BuildConfig.DIRECT_MQTT_PORT, "tcp", mTopicPrefix,
                BuildConfig.DIRECT_MQTT_USERNAME, BuildConfig.DIRECT_MQTT_TOKEN, this);
        mMqttManager.connect();
    }

    private void connectDomainWssMqtt(String reason) {
        mActiveEndpointType = "DOMAIN";
        mTopicPrefix = buildTopicPrefix();
        if (mMqttManager != null) mMqttManager.disconnect();
        Log.i(TAG, "Connecting to Domain WSS MQTT at " + BuildConfig.DOMAIN_MQTT_HOST
                + ":" + BuildConfig.DOMAIN_MQTT_PORT + BuildConfig.DOMAIN_MQTT_PATH + " (" + reason + ")");
        if (mConnectionStatusListener != null) {
            mConnectionStatusListener.onConnectionStatusChanged(false,
                    "กำลังเชื่อมต่อ Domain WSS (" + BuildConfig.DOMAIN_MQTT_HOST + BuildConfig.DOMAIN_MQTT_PATH + ")...");
        }
        mMqttManager = new MqttManager(this, BuildConfig.DOMAIN_MQTT_HOST,
                BuildConfig.DOMAIN_MQTT_PORT, BuildConfig.DOMAIN_MQTT_TRANSPORT, BuildConfig.DOMAIN_MQTT_PATH,
                mTopicPrefix, BuildConfig.DIRECT_MQTT_USERNAME, BuildConfig.DIRECT_MQTT_TOKEN, this);
        mMqttManager.connect();
    }

    /** Refresh from Core; callers cannot redirect the runtime MQTT token. */
    public void reconnectMqtt() {
        mIsFallbackAttempt = false;
        mConnectionFailureCount = 0;
        startDefaultMqtt();
    }

    public int toggleBrokerMode() {
        mBrokerMode = (mBrokerMode + 1) % 3;
        mIsFallbackAttempt = false;
        mConnectionFailureCount = 0;
        Log.i(TAG, "Broker mode toggled to: " + getBrokerModeName());
        startDefaultMqtt();
        return mBrokerMode;
    }

    public int getBrokerMode() {
        return mBrokerMode;
    }

    public String getBrokerModeName() {
        switch (mBrokerMode) {
            case BROKER_MODE_LAN_ONLY: return "LAN ONLY (:1884)";
            case BROKER_MODE_DOMAIN_ONLY: return "DOMAIN ONLY (WSS)";
            case BROKER_MODE_AUTO:
            default:
                return "AUTO (LAN ➜ WSS)";
        }
    }

    public String getActiveEndpointType() {
        return mActiveEndpointType;
    }

    public String getActiveBrokerSummary() {
        String modeName = getBrokerModeName();
        String active = "LAN".equals(mActiveEndpointType)
                ? "LAN :1884 (" + BuildConfig.DIRECT_MQTT_HOST + ")"
                : "Domain WSS (" + BuildConfig.DOMAIN_MQTT_HOST + BuildConfig.DOMAIN_MQTT_PATH + ")";
        return "โหมด: " + modeName + "\nเส้นทาง: " + active;
    }

    private void connectProvisionedMqtt(MqttProvisioningClient.Connection connection) {
        if (mMqttManager != null) {
            mMqttManager.disconnect();
        }
        mTopicPrefix = connection.topicPrefix;
        mActiveEndpointType = "tcp".equalsIgnoreCase(connection.transport) ? "LAN" : "DOMAIN";
        mMqttManager = new MqttManager(this, connection.host, connection.port, connection.transport,
                connection.topicPrefix, connection.username, connection.token, this);
        mMqttManager.connect();
    }

    public void setConnectionStatusListener(ConnectionStatusListener listener) {
        mConnectionStatusListener = listener;
    }

    public void setSpeechStatusListener(SpeechStatusListener listener) {
        mSpeechStatusListener = listener;
    }

    public void setSafetyStatusListener(SafetyStatusListener listener) {
        mSafetyStatusListener = listener;
        if (listener != null) listener.onSafetyStatusChanged(mSafetyScreenTitle, mSafetyScreenDetail, mSafetyScreenDanger);
    }

    public interface FaceStatusListener {
        void onFaceStatusChanged(String faceName);
    }
    private FaceStatusListener mFaceStatusListener;

    public void setFaceStatusListener(FaceStatusListener listener) {
        mFaceStatusListener = listener;
    }

    private void notifyFaceStatus(String faceName) {
        if (mFaceStatusListener != null && faceName != null) {
            mFaceStatusListener.onFaceStatusChanged(faceName);
        }
    }

    /** Announce the first foreground launch after a newly installed APK. */
    public void announceUpdateCompleted(final UpdateAnnouncementListener listener) {
        final String phrase = "ติดตั้งสำเร็จ";
        if (mAudioPlayer == null) {
            if (listener != null) listener.onFailed("ระบบเสียงยังไม่พร้อม");
            return;
        }
        if (mSdkBridge != null) mSdkBridge.setExpression("PLEASED");
        notifySpeechStatus(phrase, "กำลังเตรียมประกาศการอัปเดต");
        TtsClient.synthesize(phrase, "male_child", null, null, null, new TtsClient.OnTtsResult() {
            @Override public void onSuccess(byte[] wavBytes) {
                notifySpeechStatus(phrase, "กำลังพูด");
                mAudioPlayer.playBytes(wavBytes, new AudioPlaybackManager.OnAudioFinishListener() {
                    @Override public void onFinished() {
                        notifySpeechStatus(phrase, "แจ้งอัปเดตเรียบร้อยแล้ว");
                        publishStatus("update", "{\"state\":\"INSTALL_CONFIRMED\",\"version\":\"" + escapeJson(BuildConfig.VERSION_NAME) + "\"}");
                        if (listener != null) listener.onCompleted();
                    }
                });
            }

            @Override public void onError(String message) {
                notifySpeechStatus(phrase, "พูดไม่สำเร็จ");
                if (listener != null) listener.onFailed(message);
            }
        });
    }

    @Override
    public void onMessageReceived(final String topic, final String message) {
        if (Looper.myLooper() != Looper.getMainLooper()) {
            mCommandHandler.post(new Runnable() {
                @Override public void run() { onMessageReceived(topic, message); }
            });
            return;
        }
        try {
            if (isRedundantLegacyLeaf(topic)) {
                Log.d(TAG, "Ignoring legacy leaf already included in zenbo/cmd/interact: " + topic);
                return;
            }
            announceIncomingCommand(topic, message);
            if (isTopic(topic, "cmd/interact")) {
                mIgnoreLegacyLeafUntilMs = System.currentTimeMillis() + 1500L;
                InteractCommand cmd = mGson.fromJson(message, InteractCommand.class);
                executeInteractCommand(cmd);
            } else if (isTopic(topic, "cmd/safety")) {
                InteractCommand.SafetyData safety = mGson.fromJson(message, InteractCommand.SafetyData.class);
                applySafetyPolicy(safety);
            } else if (isTopic(topic, "cmd/stop") || isTopic(topic, "stop")) {
                cancelRobotSequences();
                mAudioPlayer.stop();
                mSdkBridge.stopSpeak();
                mSdkBridge.emergencyStop();
                publishScenarioStatus(mActiveScenarioRunId, "SAFETY_STOPPED");
                publishScenarioStatus(mActiveMotionScenarioRunId, "SAFETY_STOPPED");
                mActiveScenarioRunId = null;
                mActiveMotionScenarioRunId = null;
                notifySpeechStatus("", "หยุดการพูดแล้ว");
            } else if (isTopic(topic, "cmd/expression")) {
                InteractCommand cmd = mGson.fromJson(message, InteractCommand.class);
                if (cmd != null && cmd.face != null) {
                    notifyFaceStatus(cmd.face);
                    mSdkBridge.setExpression(cmd.face);
                }
            } else if (isTopic(topic, "cmd/cancel")) {
                mSdkBridge.cancelCurrentAction();
            } else if (isTopic(topic, "cmd/speak")) {
                handleGatewayAudioCommand(message);
            } else if (isTopic(topic, "cmd/volume")) {
                InteractCommand cmd = mGson.fromJson(message, InteractCommand.class);
                applyAudioVolume(cmd == null ? null : cmd.volume);
            } else if (isTopic(topic, "cmd/motion")) {
                InteractCommand.MotionData motion = mGson.fromJson(message, InteractCommand.MotionData.class);
                safeMoveBody(motion);
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
                runBehaviorSafely(behavior);
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
            } else if (isTopic(topic, "cmd/camera")) {
                InteractCommand.CameraData camera = mGson.fromJson(message, InteractCommand.CameraData.class);
                if (mCameraSessionManager != null) mCameraSessionManager.handleCameraCommand(camera);
            } else if (isTopic(topic, "cmd/ticker") || isTopic(topic, "cmd/announce")) {
                handleTickerCommand(message);
            } else if (isTopic(topic, "cmd/update")) {
                handleRemoteUpdateCommand(message);
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
                if (cmd.face != null && !cmd.face.isEmpty()) mSdkBridge.setExpression(cmd.face);
                if (mSdkBridge != null && cmd.text != null && !cmd.text.isEmpty()) {
                    mSdkBridge.startThaiSpeechFaceAnimation(cmd.text);
                }
                if (mSpeechGestureController != null) {
                    boolean allowHead = (cmd.head == null && cmd.headSequence == null);
                    mSpeechGestureController.start(cmd.text, allowHead, true);
                }
                mAudioPlayer.playBytes(Base64.decode(cmd.audioBase64, Base64.DEFAULT), actionDoneListener(cmd.text, cmd.afterSpeech, cmd.scenarioRunId));
            } else if (cmd.text != null && !cmd.text.isEmpty()) {
                if (cmd.face != null && !cmd.face.isEmpty()) {
                    mSdkBridge.setExpression(cmd.face);
                }

                if (speakThroughLegacyZenboSpeaker(cmd.text, cmd.afterSpeech, cmd.scenarioRunId)) {
                    return;
                }

                notifySpeechStatus(cmd.text, "กำลังเตรียมเสียงภาษาไทย...");
                TtsClient.synthesize(cmd.text, cmd.voiceProfile, cmd.voice, cmd.age, cmd.speed,
                        new TtsClient.OnTtsResult() {
                    @Override
                    public void onSuccess(byte[] wavBytes) {
                        notifySpeechStatus(cmd.text, "กำลังพูด");
                        if (wavBytes.length < 256) {
                            notifySpeechStatus(cmd.text, "พูดไม่สำเร็จ");
                            publishStatus("tts", "{\"state\":\"ERROR\",\"message\":\"TTS audio too small\"}");
                            return;
                        }
                        if (mSdkBridge != null) mSdkBridge.startThaiSpeechFaceAnimation(cmd.text);
                        if (mSpeechGestureController != null) {
                            boolean allowHead = (cmd.head == null && cmd.headSequence == null);
                            mSpeechGestureController.start(cmd.text, allowHead, true);
                        }
                        mAudioPlayer.playBytes(wavBytes, actionDoneListener(cmd.text, cmd.afterSpeech, cmd.scenarioRunId));
                    }

                    @Override
                    public void onError(String errMsg) {
                        // Do not silently switch to RobotAPI speech: it does not
                        // guarantee a Thai voice and hides a Thai TTS outage.
                        Log.e(TAG, "Thai TTS failed: " + errMsg);
                        notifySpeechStatus(cmd.text, "พูดไม่สำเร็จ");
                        publishScenarioStatus(cmd.scenarioRunId, "FAILED");
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

    /**
     * Legacy Zenbo firmware can complete MediaPlayer playback without routing
     * its audio to the chassis speaker. RobotAPI speech uses the robot's own
     * audio path, so prefer it on the dedicated legacy build. Newer builds keep
     * the externally synthesized Thai WAV path below.
     */
    private boolean speakThroughLegacyZenboSpeaker(final String text,
                                                    final InteractCommand.AfterSpeechData afterSpeech,
                                                    final String scenarioRunId) {
        if (!BuildConfig.LEGACY_NATIVE_TTS || mSdkBridge == null || !mSdkBridge.isReady()) return false;
        final String phrase = text == null ? "" : text.trim();
        if (phrase.isEmpty()) return false;
        notifySpeechStatus(phrase, "กำลังพูดผ่านลำโพง Zenbo");
        publishStatus("tts", "{\"state\":\"NATIVE_SPEAKER_REQUESTED\",\"volume\":" + mSpeechVolumePercent + "}");
        mSdkBridge.speak(phrase, mSpeechVolumePercent);
        if (mSpeechGestureController != null) {
            mSpeechGestureController.start(phrase, true, true);
        }
        // The legacy RobotAPI exposes no per-utterance completion callback.
        // Keep UI/scenario state coherent using a conservative text-duration
        // estimate, without starting a second MediaPlayer utterance.
        long delayMs = Math.max(1800L, Math.min(15000L, 900L + phrase.length() * 230L));
        mHeadSequenceHandler.postDelayed(new Runnable() {
            @Override public void run() {
                actionDoneListener(phrase, afterSpeech, scenarioRunId).onFinished();
            }
        }, delayMs);
        return true;
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
        return actionDoneListener(spokenText, null);
    }

    private AudioPlaybackManager.OnAudioFinishListener actionDoneListener(final String spokenText,
                                                                           final InteractCommand.AfterSpeechData afterSpeech) {
        return actionDoneListener(spokenText, afterSpeech, null);
    }

    private AudioPlaybackManager.OnAudioFinishListener actionDoneListener(final String spokenText,
                                                                           final InteractCommand.AfterSpeechData afterSpeech,
                                                                           final String scenarioRunId) {
        return new AudioPlaybackManager.OnAudioFinishListener() {
            @Override
            public void onFinished() {
                if (mSpeechGestureController != null) mSpeechGestureController.stop();
                if (mSdkBridge != null) mSdkBridge.stopThaiSpeechFaceAnimation();
                if (spokenText != null && !spokenText.isEmpty()) {
                    notifySpeechStatus(spokenText, "พูดจบแล้ว");
                }
                runAfterSpeechCue(afterSpeech);
                publishScenarioStatus(scenarioRunId, "SPEECH_COMPLETED");
                if (scenarioRunId != null && scenarioRunId.equals(mActiveScenarioRunId)) {
                    mActiveScenarioRunId = null;
                }
                publishStatus("action_done", "{\"status\":\"SUCCESS\",\"type\":\"speak\"}");
            }
        };
    }

    private void applyAudioVolume(Integer requestedPercent) {
        if (requestedPercent == null || mAudioPlayer == null) return;
        int percent = Math.max(0, Math.min(100, requestedPercent));
        mSpeechVolumePercent = percent;
        mAudioPlayer.setVolumePercent(percent);
        publishStatus("audio", "{\"state\":\"VOLUME_APPLIED\",\"percent\":" + percent + "}");
    }

    private void publishScenarioStatus(String runId, String state) {
        if (runId == null || runId.trim().isEmpty()) return;
        publishStatus("scenario", "{\"run_id\":\"" + escapeJson(runId)
                + "\",\"state\":\"" + escapeJson(state) + "\"}");
    }

    private void runAfterSpeechCue(InteractCommand.AfterSpeechData cue) {
        if (cue == null || mSdkBridge == null) return;
        if (cue.face != null && !cue.face.isEmpty()) mSdkBridge.setExpression(cue.face);
        if (cue.wheelLights != null) mSdkBridge.controlWheelLights(cue.wheelLights);
        if (cue.head != null) mSdkBridge.moveHead(cue.head.yaw, cue.head.pitch, cue.head.speed);
        if (cue.headSequence != null) playHeadSequence(cue.headSequence);
        publishStatus("presentation", "{\"state\":\"AFTER_SPEECH_CUE_APPLIED\"}");
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

    /**
     * A composite command already carries the speech the operator requested.
     * Do not add a second acknowledgement utterance: it makes short prompts
     * sound duplicated and creates an avoidable race with the Thai TTS audio.
     */
    private void executeInteractCommand(final InteractCommand cmd) {
        if (cmd != null && cmd.motion != null && "RELATIVE_BODY".equals(cmd.motion.controlMode)) {
            executeRelativeMotion(cmd);
            return;
        }
        if (cmd == null) return;
        if (mRelativeController != null && mRelativeController.isActive()) mRelativeController.cancel("OTHER_COMMAND");
        executeAcceptedInteractCommand(cmd);
    }

    private void executeAcceptedInteractCommand(final InteractCommand cmd) {
        if (cmd == null) return;
        publishStatus("command", "{\"state\":\"RECEIVED\",\"id\":\""
                + escapeJson(cmd.commandId) + "\"}");
        mActiveScenarioRunId = cmd.scenarioRunId;
        publishScenarioStatus(cmd.scenarioRunId, "CLIENT_RECEIVED");

        if (cmd.script != null && cmd.script.steps != null && cmd.script.steps.length > 0) {
            executeScenarioScript(cmd.script.steps, cmd.scenarioRunId);
            return;
        }
        if (cmd.interactive != null && cmd.interactive.visionGate != null) {
            executeInteractiveScenario(cmd.interactive, cmd.scenarioRunId);
            return;
        }
        if (cmd.interactiveSequence != null && cmd.interactiveSequence.firstGate != null) {
            executeInteractiveSequence(cmd.interactiveSequence, cmd.scenarioRunId);
            return;
        }

        // 1. ตรวจสอบเงื่อนไขสีหน้าและท่าทาง
        final boolean driveOnly = (cmd.remoteControl != null || cmd.motion != null)
                && cmd.text == null && cmd.action == null && cmd.emotionalAction == null
                && cmd.script == null && cmd.interactive == null && cmd.interactiveSequence == null;
        final boolean hasFace = !driveOnly && cmd.face != null && !cmd.face.isEmpty();
        final boolean hasAction = cmd.action != null && !cmd.action.stop;

        if (hasFace) {
            notifyFaceStatus(cmd.face);
        }

        // 2. สั่งระดับเสียงและไฟ LED ล้อ
        if (cmd.volume != null) applyAudioVolume(cmd.volume);
        if (cmd.wheelLights != null) {
            publishStatus("wheel_lights", "{\"state\":\"REQUESTED\",\"mode\":\""
                    + escapeJson(cmd.wheelLights.mode) + "\"}");
            mSdkBridge.controlWheelLights(cmd.wheelLights);
        }

        // 3. สั่งเคลื่อนที่ — remote joystick ต้องไม่คู่กับ moveBody ในคำสั่งเดียว
        // เพราะ watchdog ของ motion จะ emergencyStop และทำให้ขับกระตุก
        if (cmd.safety != null) applySafetyPolicy(cmd.safety);
        final boolean hasRemoteBody = cmd.remoteControl != null && cmd.remoteControl.body != null
                && !cmd.remoteControl.body.trim().isEmpty();
        if (cmd.motion != null && !hasRemoteBody) {
            if ("RELATIVE_BODY".equals(cmd.motion.controlMode)) {
                executeRelativeMotion(cmd);
            } else {
                safeMoveBody(cmd.motion);
            }
        }

        // 4. สั่งหันศีรษะ
        if (cmd.head != null) {
            mSdkBridge.moveHead(cmd.head.yaw, cmd.head.pitch, cmd.head.speed);
        }
        if (cmd.headSequence != null) {
            playHeadSequence(cmd.headSequence);
        }

        // 5. สั่งสีหน้าและท่าทาง (Action)
        if (hasFace && hasAction) {
            publishStatus("action", "{\"state\":\"REQUESTED\",\"id\":"
                    + cmd.action.actionId + ",\"face\":\"" + escapeJson(cmd.face) + "\"}");
            mSdkBridge.playEmotionalAction(cmd.face, cmd.action.actionId);
        } else {
            if (hasFace) {
                mSdkBridge.setExpression(cmd.face);
            }
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
        }

        if (cmd.emotionalAction != null) {
            mSdkBridge.playEmotionalAction(cmd.emotionalAction);
        }

        if (cmd.remoteControl != null) handleRemoteControl(cmd.remoteControl);

        if (cmd.behavior != null) runBehaviorSafely(cmd.behavior);

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

        // 6. Core can attach a short, LAN-synthesized WAV.  This avoids a
        // second network hop on legacy Android and keeps face timing aligned.
        if (cmd.audioBase64 != null && !cmd.audioBase64.isEmpty()) {
            try {
                byte[] audioBytes = Base64.decode(cmd.audioBase64, Base64.DEFAULT);
                if (audioBytes.length < 256) {
                    publishStatus("tts", "{\"state\":\"ERROR\",\"message\":\"Inline TTS audio too small\"}");
                    notifySpeechStatus(cmd.text, "พูดไม่สำเร็จ");
                    return;
                }
                publishStatus("tts", "{\"state\":\"RECEIVED\",\"source\":\"inline\",\"bytes\":" + audioBytes.length + "}");
                notifySpeechStatus(cmd.text, "กำลังพูด");
                if (mSdkBridge != null && cmd.text != null && !cmd.text.isEmpty()) {
                    mSdkBridge.startThaiSpeechFaceAnimation(cmd.text);
                }
                if (mSpeechGestureController != null && cmd.text != null && !cmd.text.isEmpty()) {
                    boolean allowHead = (cmd.head == null && cmd.headSequence == null);
                    mSpeechGestureController.start(cmd.text, allowHead, true);
                }
                mAudioPlayer.playBytes(audioBytes, actionDoneListener(cmd.text, cmd.afterSpeech, cmd.scenarioRunId));
            } catch (IllegalArgumentException error) {
                Log.e(TAG, "Inline Thai TTS decode failed: " + error.getMessage(), error);
                publishStatus("tts", "{\"state\":\"ERROR\",\"message\":\"Inline TTS decode failed\"}");
                notifySpeechStatus(cmd.text, "พูดไม่สำเร็จ");
            }
            return;
        }

        // 7. Text is authoritative: synthesize it through the Thai TTS
        // service configured in TtsClient.  Core commands may also contain an
        // audio_url, but that URL is a convenience cache and can be unreachable
        // from the robot network.  Prefer the on-LAN service at :8025 so Thai
        // speech is deterministic.
        if (cmd.text != null && !cmd.text.isEmpty()) {
            if (speakThroughLegacyZenboSpeaker(cmd.text, cmd.afterSpeech, cmd.scenarioRunId)) {
                return;
            }
            notifySpeechStatus(cmd.text, "กำลังเตรียมเสียงภาษาไทย...");
            publishStatus("tts", "{\"state\":\"REQUESTED\",\"service\":\"10.101.118.149:8025\""
                    + ",\"voice_profile\":\"" + escapeJson(cmd.voiceProfile) + "\"}");
            TtsClient.synthesize(cmd.text, cmd.voiceProfile, cmd.voice, cmd.age, cmd.speed,
                    new TtsClient.OnTtsResult() {
                @Override
                public void onSuccess(byte[] wavBytes) {
                    publishStatus("tts", "{\"state\":\"RECEIVED\",\"bytes\":" + wavBytes.length + "}");
                    notifySpeechStatus(cmd.text, "กำลังพูด");
                    if (wavBytes.length < 256) {
                        publishStatus("tts", "{\"state\":\"ERROR\",\"message\":\"TTS audio too small\"}");
                        notifySpeechStatus(cmd.text, "พูดไม่สำเร็จ");
                        return;
                    }
                    if (mSdkBridge != null) mSdkBridge.startThaiSpeechFaceAnimation(cmd.text);
                    if (mSpeechGestureController != null) {
                        boolean allowHead = (cmd.head == null && cmd.headSequence == null);
                        if (cmd.face != null && !cmd.face.isEmpty() && mSdkBridge != null) {
                            mSdkBridge.setExpression(cmd.face);
                        }
                        mSpeechGestureController.start(cmd.text, allowHead, true);
                    }
                    mAudioPlayer.playBytes(wavBytes, actionDoneListener(cmd.text, cmd.afterSpeech, cmd.scenarioRunId));
                }

                @Override
                public void onError(String message) {
                    Log.e(TAG, "Thai TTS failed: " + message);
                    notifySpeechStatus(cmd.text, "พูดไม่สำเร็จ");
                    publishScenarioStatus(cmd.scenarioRunId, "FAILED");
                    if (cmd.scenarioRunId != null && cmd.scenarioRunId.equals(mActiveScenarioRunId)) {
                        mActiveScenarioRunId = null;
                    }
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
                    // delay_ms belongs to the step about to begin.  The old
                    // implementation used the previous step's delay, making
                    // a sequence whose first step had delay 0 collapse into
                    // an immediate second movement.
                    mHeadSequenceHandler.postDelayed(this, Math.max(0, sequence[index].delayMs));
                }
            }
        });
    }

    /** Runs a Core-validated, stationary L1 script one scene at a time. */
    private void executeScenarioScript(final InteractCommand.ScenarioStepData[] steps,
                                       final String scenarioRunId) {
        mScenarioScriptHandler.removeCallbacksAndMessages(null);
        executeScenarioScriptStep(steps, 0, scenarioRunId);
    }

    private void executeScenarioScriptStep(final InteractCommand.ScenarioStepData[] steps,
                                           final int index,
                                           final String scenarioRunId) {
        if (steps == null || index >= steps.length) {
            publishScenarioStatus(scenarioRunId, "SPEECH_COMPLETED");
            if (scenarioRunId != null && scenarioRunId.equals(mActiveScenarioRunId)) {
                mActiveScenarioRunId = null;
            }
            publishStatus("scenario", "{\"state\":\"SCRIPT_COMPLETED\",\"steps\":" + index + "}");
            return;
        }

        final InteractCommand.ScenarioStepData step = steps[index];
        if (step == null) {
            executeScenarioScriptStep(steps, index + 1, scenarioRunId);
            return;
        }
        if (mSdkBridge != null) {
            if (step.face != null && !step.face.isEmpty()) mSdkBridge.setExpression(step.face);
            if (step.wheelLights != null) mSdkBridge.controlWheelLights(step.wheelLights);
            if (step.head != null) mSdkBridge.moveHead(step.head.yaw, step.head.pitch, step.head.speed);
            if (step.headSequence != null) playHeadSequence(step.headSequence);
        }

        final Runnable nextStep = new Runnable() {
            @Override public void run() {
                mScenarioScriptHandler.post(new Runnable() {
                    @Override public void run() {
                        executeScenarioScriptStep(steps, index + 1, scenarioRunId);
                    }
                });
            }
        };
        if (step.text == null || step.text.trim().isEmpty() || mAudioPlayer == null) {
            runAfterSpeechCue(step.afterSpeech);
            nextStep.run();
            return;
        }

        notifySpeechStatus(step.text, "กำลังเตรียมเสียงภาษาไทย...");
        publishStatus("scenario", "{\"state\":\"SCRIPT_STEP_REQUESTED\",\"step\":"
                + (index + 1) + "}");
        TtsClient.synthesize(step.text, step.voiceProfile, step.voice, step.age, step.speed,
                new TtsClient.OnTtsResult() {
                    @Override public void onSuccess(byte[] wavBytes) {
                        notifySpeechStatus(step.text, "กำลังพูด");
                        mAudioPlayer.playBytes(wavBytes, new AudioPlaybackManager.OnAudioFinishListener() {
                            @Override public void onFinished() {
                                runAfterSpeechCue(step.afterSpeech);
                                nextStep.run();
                            }
                        });
                    }

                    @Override public void onError(String message) {
                        Log.e(TAG, "L1 scenario TTS failed: " + message);
                        notifySpeechStatus(step.text, "พูดไม่สำเร็จ");
                        publishScenarioStatus(scenarioRunId, "FAILED");
                        if (scenarioRunId != null && scenarioRunId.equals(mActiveScenarioRunId)) {
                            mActiveScenarioRunId = null;
                        }
                        publishStatus("scenario", "{\"state\":\"SCRIPT_FAILED\",\"step\":"
                                + (index + 1) + ",\"message\":\"" + escapeJson(message) + "\"}");
                    }
                });
    }

    /** L2 waits for anonymous face/person detection locally, then plays one safe branch. */
    private void executeInteractiveScenario(final InteractCommand.InteractiveScenarioData interactive,
                                            final String scenarioRunId) {
        cancelInteractiveVisionGate();
        if (interactive == null || interactive.visionGate == null || mSdkBridge == null) {
            publishScenarioStatus(scenarioRunId, "FAILED");
            publishStatus("scenario", "{\"state\":\"INTERACTIVE_UNAVAILABLE\"}");
            return;
        }
        mActiveInteractiveScenario = interactive;
        mInteractiveScenarioRunId = scenarioRunId;
        publishStatus("scenario", "{\"state\":\"VISION_WAITING\",\"action\":\""
                + escapeJson(interactive.visionGate.action) + "\"}");
        mSdkBridge.runVision(interactive.visionGate.action, interactive.visionGate.intervalMs,
                null, false);
        mInteractiveVisionTimeout = new Runnable() {
            @Override public void run() {
                if (interactive != mActiveInteractiveScenario) return;
                finishInteractiveVisionGate(interactive.onTimeout, "VISION_TIMEOUT");
            }
        };
        mInteractiveVisionHandler.postDelayed(mInteractiveVisionTimeout,
                Math.max(3000, interactive.visionGate.timeoutMs));
    }

    private void handleInteractiveVisionResult(String action, String payload) {
        InteractCommand.InteractiveScenarioData interactive = mActiveInteractiveScenario;
        if (interactive == null || interactive.visionGate == null || action == null || payload == null) return;
        if (!action.equalsIgnoreCase(interactive.visionGate.action) || !hasInteractiveVisionTarget(action, payload)) return;
        finishInteractiveVisionGate(interactive.onDetect, "VISION_DETECTED");
    }

    private boolean isInteractiveVisionSignal(String action) {
        if (action == null) return false;
        if (mActiveInteractiveScenario != null && mActiveInteractiveScenario.visionGate != null
                && action.equalsIgnoreCase(mActiveInteractiveScenario.visionGate.action)) return true;
        InteractCommand.VisionGateData sequenceGate = activeSequenceGate();
        return sequenceGate != null && action.equalsIgnoreCase(sequenceGate.action);
    }

    private boolean hasInteractiveVisionTarget(String action, String payload) {
        if ("detect_face".equalsIgnoreCase(action)) return payload.contains("\"faces\":[{");
        if ("detect_person".equalsIgnoreCase(action)) return payload.contains("\"persons\":[{");
        if ("gesture_point".equalsIgnoreCase(action)) return payload.contains("\"action\":\"gesture_point\"");
        return false;
    }

    private void finishInteractiveVisionGate(InteractCommand.ScenarioOutcomeData outcome, String state) {
        final String scenarioRunId = mInteractiveScenarioRunId;
        cancelInteractiveVisionGate();
        publishStatus("scenario", "{\"state\":\"" + state + "\"}");
        if (outcome == null || outcome.steps == null || outcome.steps.length == 0) {
            publishScenarioStatus(scenarioRunId, "FAILED");
            return;
        }
        executeScenarioScript(outcome.steps, scenarioRunId);
    }

    private void cancelInteractiveVisionGate() {
        mInteractiveVisionHandler.removeCallbacksAndMessages(null);
        if (mActiveInteractiveScenario != null && mActiveInteractiveScenario.visionGate != null && mSdkBridge != null) {
            String action = mActiveInteractiveScenario.visionGate.action;
            if ("detect_face".equalsIgnoreCase(action)) {
                mSdkBridge.runVision("cancel_face", 1000, null, false);
            } else if ("detect_person".equalsIgnoreCase(action)) {
                mSdkBridge.runVision("cancel_person", 1000, null, false);
            }
        }
        mActiveInteractiveScenario = null;
        mInteractiveScenarioRunId = null;
        mInteractiveVisionTimeout = null;
    }

    /** L4 starts a bounded, stationary presence-then-gesture interaction. */
    private void executeInteractiveSequence(final InteractCommand.InteractiveSequenceData sequence,
                                            final String scenarioRunId) {
        cancelInteractiveVisionGate();
        cancelInteractiveSequenceGate();
        if (sequence == null || sequence.firstGate == null || sequence.secondGate == null || mSdkBridge == null) {
            publishScenarioStatus(scenarioRunId, "FAILED");
            publishStatus("scenario", "{\"state\":\"INTERACTIVE_SEQUENCE_UNAVAILABLE\"}");
            return;
        }
        mActiveInteractiveSequence = sequence;
        mInteractiveSequenceRunId = scenarioRunId;
        startInteractiveSequenceGate(1);
    }

    private InteractCommand.VisionGateData activeSequenceGate() {
        if (mActiveInteractiveSequence == null) return null;
        return mInteractiveSequenceStage == 2 ? mActiveInteractiveSequence.secondGate : mActiveInteractiveSequence.firstGate;
    }

    private void startInteractiveSequenceGate(final int stage) {
        if (mActiveInteractiveSequence == null) return;
        final InteractCommand.VisionGateData gate = stage == 2
                ? mActiveInteractiveSequence.secondGate : mActiveInteractiveSequence.firstGate;
        if (gate == null || mSdkBridge == null) {
            finishInteractiveSequence(null, "SEQUENCE_GATE_UNAVAILABLE");
            return;
        }
        mInteractiveSequenceStage = stage;
        publishStatus("scenario", "{\"state\":\"L4_GATE_WAITING\",\"stage\":" + stage
                + ",\"action\":\"" + escapeJson(gate.action) + "\"}");
        mSdkBridge.runVision(gate.action, gate.intervalMs, null, false);
        mInteractiveVisionHandler.removeCallbacksAndMessages(null);
        mInteractiveVisionTimeout = new Runnable() {
            @Override public void run() {
                if (mActiveInteractiveSequence == null || mInteractiveSequenceStage != stage) return;
                finishInteractiveSequence(stage == 1 ? mActiveInteractiveSequence.onFirstTimeout
                        : mActiveInteractiveSequence.onSecondTimeout,
                        stage == 1 ? "L4_FIRST_TIMEOUT" : "L4_SECOND_TIMEOUT");
            }
        };
        mInteractiveVisionHandler.postDelayed(mInteractiveVisionTimeout, Math.max(3000, gate.timeoutMs));
    }

    private void handleInteractiveSequenceVisionResult(String action, String payload) {
        InteractCommand.VisionGateData gate = activeSequenceGate();
        if (gate == null || action == null || payload == null || !action.equalsIgnoreCase(gate.action)
                || !hasInteractiveVisionTarget(action, payload)) return;
        if (mInteractiveSequenceStage == 1) {
            cancelActiveSequenceVisionOnly();
            speakSequencePrompt(mActiveInteractiveSequence.prompt);
            return;
        }
        finishInteractiveSequence(mActiveInteractiveSequence.onSecondDetect, "L4_SECOND_DETECTED");
    }

    private void speakSequencePrompt(final InteractCommand.ScenarioStepData prompt) {
        if (prompt == null) {
            startInteractiveSequenceGate(2);
            return;
        }
        if (mSdkBridge != null) {
            if (prompt.face != null && !prompt.face.isEmpty()) mSdkBridge.setExpression(prompt.face);
            if (prompt.wheelLights != null) mSdkBridge.controlWheelLights(prompt.wheelLights);
            if (prompt.head != null) mSdkBridge.moveHead(prompt.head.yaw, prompt.head.pitch, prompt.head.speed);
            if (prompt.headSequence != null) playHeadSequence(prompt.headSequence);
        }
        if (prompt.text == null || prompt.text.trim().isEmpty() || mAudioPlayer == null) {
            runAfterSpeechCue(prompt.afterSpeech);
            startInteractiveSequenceGate(2);
            return;
        }
        notifySpeechStatus(prompt.text, "กำลังเตรียมเสียงภาษาไทย...");
        TtsClient.synthesize(prompt.text, prompt.voiceProfile, prompt.voice, prompt.age, prompt.speed,
                new TtsClient.OnTtsResult() {
                    @Override public void onSuccess(byte[] wavBytes) {
                        mAudioPlayer.playBytes(wavBytes, new AudioPlaybackManager.OnAudioFinishListener() {
                            @Override public void onFinished() {
                                runAfterSpeechCue(prompt.afterSpeech);
                                startInteractiveSequenceGate(2);
                            }
                        });
                    }
                    @Override public void onError(String message) {
                        Log.e(TAG, "L4 prompt TTS failed: " + message);
                        finishInteractiveSequence(null, "L4_PROMPT_FAILED");
                    }
                });
    }

    private void finishInteractiveSequence(InteractCommand.ScenarioOutcomeData outcome, String state) {
        final String scenarioRunId = mInteractiveSequenceRunId;
        cancelInteractiveSequenceGate();
        publishStatus("scenario", "{\"state\":\"" + state + "\"}");
        if (outcome == null || outcome.steps == null || outcome.steps.length == 0) {
            publishScenarioStatus(scenarioRunId, "FAILED");
            return;
        }
        if (outcome.navigation != null) openNavigationDisplay(outcome.navigation);
        executeScenarioScript(outcome.steps, scenarioRunId);
    }

    private void cancelActiveSequenceVisionOnly() {
        mInteractiveVisionHandler.removeCallbacksAndMessages(null);
        InteractCommand.VisionGateData gate = activeSequenceGate();
        if (gate != null && mSdkBridge != null) {
            if ("detect_face".equalsIgnoreCase(gate.action)) mSdkBridge.runVision("cancel_face", 1000, null, false);
            else if ("detect_person".equalsIgnoreCase(gate.action)) mSdkBridge.runVision("cancel_person", 1000, null, false);
        }
    }

    private void cancelInteractiveSequenceGate() {
        cancelActiveSequenceVisionOnly();
        mActiveInteractiveSequence = null;
        mInteractiveSequenceRunId = null;
        mInteractiveSequenceStage = 0;
    }

    private void playYoutubeAndDance(final InteractCommand.YouTubeData youtube) {
        if (youtube == null) {
            publishStatus("youtube", "{\"state\":\"REJECTED\",\"message\":\"missing_command\"}");
            return;
        }
        String action = youtube.action == null ? "play" : youtube.action.toLowerCase();
        if (!"play".equals(action)) {
            Intent control = new Intent(YouTubePlayerActivity.ACTION_CONTROL);
            control.setPackage(getPackageName());
            control.putExtra(YouTubePlayerActivity.EXTRA_CONTROL_ACTION, action);
            sendBroadcast(control);
            publishStatus("youtube", "{\"state\":\"CONTROL_SENT\",\"action\":\"" + escapeJson(action) + "\"}");
            if ("stop".equals(action)) cancelDanceLoop();
            return;
        }
        if (youtube.url == null || youtube.url.trim().isEmpty()) {
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
        if (!url.startsWith(NAVIGATION_SERVICE_URL_PREFIX)
                && !LIBRARY_MAP_URL.equals(url)
                && !LIBRARY_RAG_URL.equals(url)) {
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
        if (SystemClock.elapsedRealtime() < mLegacyMotionUntilMs && mSdkBridge != null) {
            mSdkBridge.emergencyStop();
        }
        mLegacyMotionUntilMs = 0;
        if (mRelativeController != null && mRelativeController.isActive()) mRelativeController.cancel();
        if (mSpeechGestureController != null) mSpeechGestureController.stop();
        mHeadSequenceHandler.removeCallbacksAndMessages(null);
        mScenarioScriptHandler.removeCallbacksAndMessages(null);
        cancelInteractiveVisionGate();
        cancelInteractiveSequenceGate();
        cancelDanceLoop();
        cancelRemoteControlSafety();
        mMotionGuardHandler.removeCallbacks(mMotionGuardStopRunnable);
        if (mSdkBridge != null) mSdkBridge.cancelActiveVision();
    }

    private void handleRemoteControl(InteractCommand.RemoteControlData remote) {
        if (remote == null || mSdkBridge == null) return;
        if (mRelativeController != null && mRelativeController.isActive()) mRelativeController.cancel();
        if (!mSdkBridge.isReady()) {
            publishStatus("remote", "{\"state\":\"SDK_NOT_READY\"}");
            return;
        }
        if (remote.body != null && !"STOP".equalsIgnoreCase(remote.body.trim()) && isMotionInterlocked()) {
            publishSafetyBlocked("REMOTE_BODY_BLOCKED");
            sendRemoteBodyStop();
            return;
        }

        // Cancel any discrete moveBody watchdog so it cannot interrupt continuous drive.
        if (remote.body != null) {
            mMotionGuardHandler.removeCallbacks(mMotionGuardStopRunnable);
            mActiveMotionScenarioRunId = null;
        }

        boolean bodyChanged = remote.body != null
                && !remote.body.trim().equalsIgnoreCase(String.valueOf(mLastRemoteBodyDirection));
        boolean headChanged = remote.head != null
                && !remote.head.trim().equalsIgnoreCase(String.valueOf(mLastRemoteHeadDirection));

        // Keepalive packets only refresh the deadman.  Re-issuing the same
        // remoteControlBody direction every 450ms makes Zenbo stutter.
        if (bodyChanged || headChanged) {
            InteractCommand.RemoteControlData delta = new InteractCommand.RemoteControlData();
            if (bodyChanged) delta.body = remote.body;
            if (headChanged) delta.head = remote.head;
            mSdkBridge.remoteControl(delta);
            if (bodyChanged) {
                mLastRemoteBodyDirection = remote.body.trim().toUpperCase();
                if ("STOP".equalsIgnoreCase(mLastRemoteBodyDirection)) mLastRemoteBodyDirection = null;
            }
            if (headChanged) {
                mLastRemoteHeadDirection = remote.head.trim().toUpperCase();
                if ("STOP".equalsIgnoreCase(mLastRemoteHeadDirection)) mLastRemoteHeadDirection = null;
            }
            publishStatus("remote", "{\"state\":\"APPLIED\""
                    + (delta.body != null ? ",\"body\":\"" + escapeJson(delta.body) + "\"" : "")
                    + (delta.head != null ? ",\"head\":\"" + escapeJson(delta.head) + "\"" : "")
                    + "}");
        } else {
            publishStatus("remote", "{\"state\":\"KEEPALIVE\"}");
        }

        if (remote.body != null) {
            mRemoteControlSafetyHandler.removeCallbacks(mBodyRemoteStopRunnable);
            if (!"STOP".equalsIgnoreCase(remote.body.trim())) {
                mRemoteBodyControlActiveUntilMs = System.currentTimeMillis() + REMOTE_CONTROL_DEADMAN_MS;
                mRemoteControlSafetyHandler.postDelayed(mBodyRemoteStopRunnable, REMOTE_CONTROL_DEADMAN_MS);
            } else {
                mRemoteBodyControlActiveUntilMs = 0L;
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
        mLastRemoteBodyDirection = null;
        mRemoteBodyControlActiveUntilMs = 0L;
        publishStatus("remote", "{\"body\":\"STOP\",\"reason\":\"deadman_timeout\"}");
    }

    private void sendRemoteHeadStop() {
        InteractCommand.RemoteControlData stop = new InteractCommand.RemoteControlData();
        stop.head = "STOP";
        if (mSdkBridge != null) mSdkBridge.remoteControl(stop);
        mLastRemoteHeadDirection = null;
        publishStatus("remote", "{\"head\":\"STOP\",\"reason\":\"deadman_timeout\"}");
    }

    private void cancelRemoteControlSafety() {
        mRemoteControlSafetyHandler.removeCallbacks(mBodyRemoteStopRunnable);
        mRemoteControlSafetyHandler.removeCallbacks(mHeadRemoteStopRunnable);
    }

    private void applyDefaultOperatorSafety() {
        InteractCommand.SafetyData operatorDrive = new InteractCommand.SafetyData();
        operatorDrive.baseMotionEnabled = true;
        operatorDrive.collisionGuardEnabled = false;
        operatorDrive.fallGuardEnabled = false;
        operatorDrive.maxDistanceM = 0.75f;
        operatorDrive.maxSpeed = 7;
        operatorDrive.autoStopMs = 3000;
        applySafetyPolicy(operatorDrive);
    }

    private void applySafetyPolicy(InteractCommand.SafetyData safety) {
        if (safety == null) return;
        mSafetyPolicyEpoch++;
        if (!BuildConfig.SAFETY_MONITOR_ENABLED) {
            // Field/legacy builds keep wheels unlocked.  LIFF may still send
            // safety envelopes for audit, but they must not re-lock the base.
            mBaseMotionEnabled = true;
            mCollisionGuardEnabled = false;
            mFallGuardEnabled = false;
            mMaxMotionDistanceM = Math.max(0.05f, Math.min(5.0f, safety.maxDistanceM > 0 ? safety.maxDistanceM : 3.0f));
            mMaxMotionSpeed = Math.min(7, Math.max(1, safety.maxSpeed > 0 ? safety.maxSpeed : 7));
            mAutoStopMs = Math.max(1000, Math.min(30000, safety.autoStopMs > 0 ? safety.autoStopMs : 10000));
            notifySafetyStatus("Operator Drive", "ปลดล็อกล้อแล้ว — ควบคุมด้วย LIFF ได้", false);
            publishStatus("safety", "{\"state\":\"OPERATOR_DRIVE\",\"base_motion_enabled\":true"
                    + ",\"collision_guard_enabled\":false,\"fall_guard_enabled\":false"
                    + ",\"max_distance_m\":" + mMaxMotionDistanceM
                    + ",\"max_speed\":" + mMaxMotionSpeed
                    + ",\"auto_stop_ms\":" + mAutoStopMs + "}");
            return;
        }
        mBaseMotionEnabled = safety.baseMotionEnabled;
        mCollisionGuardEnabled = safety.collisionGuardEnabled;
        mFallGuardEnabled = safety.fallGuardEnabled;
        final boolean operatorSupervised = !BuildConfig.SAFETY_MONITOR_ENABLED
                && !mCollisionGuardEnabled && !mFallGuardEnabled;
        float distanceCap = operatorSupervised ? 5.0f
                : (safety.baseMotionEnabled ? 3.0f : 0.50f);
        int stopCap = safety.baseMotionEnabled ? 15000 : 30000;
        mMaxMotionDistanceM = Math.max(0.05f, Math.min(distanceCap, safety.maxDistanceM > 0 ? safety.maxDistanceM : distanceCap));
        mMaxMotionSpeed = operatorSupervised
                ? Math.min(7, Math.max(1, safety.maxSpeed > 0 ? safety.maxSpeed : 7)) : Math.min(7, Math.max(1, safety.maxSpeed));
        mAutoStopMs = Math.max(1000, Math.min(stopCap, safety.autoStopMs > 0 ? safety.autoStopMs : 10000));
        if (mSafetyMonitor != null) mSafetyMonitor.applyPolicy(safety);
        // A new policy must not silently supersede an in-flight L8 run.  Its
        // watchdog is cancelled below, so close the prior run as a safety stop.
        if (mActiveMotionScenarioRunId != null) {
            publishScenarioStatus(mActiveMotionScenarioRunId, "SAFETY_STOPPED");
            mActiveMotionScenarioRunId = null;
        }
        cancelRobotSequences();
        if (isMotionInterlocked()) {
            if (mSdkBridge != null) mSdkBridge.emergencyStop();
        }
        notifySafetyStatus(mBaseMotionEnabled ? "Safety Guard เปิดอยู่" : "Safety Guard: ฐานล็อกอยู่",
                "กันชน=" + mCollisionGuardEnabled + " · กันตก=" + mFallGuardEnabled, false);
        publishStatus("safety", "{\"state\":\"POLICY_APPLIED\",\"base_motion_enabled\":" + mBaseMotionEnabled
                + ",\"collision_guard_enabled\":" + mCollisionGuardEnabled
                + ",\"fall_guard_enabled\":" + mFallGuardEnabled
                + ",\"hardware_sensor_coverage\":" + (mSafetyMonitor != null && mSafetyMonitor.hasRequiredCoverage()) + "}");
    }

    private void relativeAck(InteractCommand cmd, String state, String reason,
                             Integer effective, long receivedAt) {
        java.util.Map<String, Object> ack = new java.util.LinkedHashMap<>();
        ack.put("command_id", cmd.commandId);
        ack.put("control_mode", "RELATIVE_BODY");
        ack.put("state", state);
        ack.put("requested_speed_level", cmd.motion.speed);
        ack.put("policy_max_speed_level", Math.min(mMaxMotionSpeed,
                cmd.policy == null ? 1 : cmd.policy.maxBodySpeedLevel));
        ack.put("effective_speed_level", effective);
        ack.put("reject_reason", reason);
        ack.put("received_at_ms", receivedAt);
        ack.put("sdk_submitted_at_ms", effective == null ? null : System.currentTimeMillis());
        ack.put("physical_velocity_verified", false);
        ack.put("apk_version", BuildConfig.VERSION_NAME);
        ack.put("apk_sha256", mInstalledApkSha256);
        publishStatus("motion_ack", new com.google.gson.GsonBuilder().serializeNulls().create().toJson(ack));
    }

    private void executeRelativeMotion(InteractCommand cmd) {
        long receivedAt = System.currentTimeMillis();
        relativeAck(cmd, "APK_RECEIVED", null, null, receivedAt);
        String reason = null;
        if (!BuildConfig.RELATIVE_MOTION_ENABLED) reason = "RELATIVE_MOTION_DISABLED";
        else if (!BuildConfig.SAFETY_MONITOR_ENABLED || mSafetyMonitor == null
                || !mSafetyMonitor.hasRequiredCoverage() || !mCollisionGuardEnabled
                || !mFallGuardEnabled || isMotionInterlocked()) reason = "FIELD_NOT_READY";
        else if (!mSdkBridge.isReady()) reason = "ROBOT_API_NOT_READY";
        else if (System.currentTimeMillis() < mRemoteBodyControlActiveUntilMs
                || SystemClock.elapsedRealtime() < mLegacyMotionUntilMs) reason = "MOTION_BUSY";
        if (reason != null) {
            relativeAck(cmd, "REJECTED", reason, null, receivedAt);
            return;
        }
        try {
            SpeedLevelDriveController.Command wire = RelativeMotionEnvelopeMapper.from(cmd);
            // Translate once to a monotonic deadline. Never extend the local hard limit.
            long remaining = Math.max(0, Math.min(wire.expiresAtMs - receivedAt, 3000));
            SpeedLevelDriveController.Command bounded = new SpeedLevelDriveController.Command(
                    wire.commandId, wire.sourceSessionId, wire.sourceSeq,
                    SystemClock.elapsedRealtime() + remaining,
                    wire.xMeters, wire.yMeters, wire.thetaDegrees, wire.requestedSpeedLevel,
                    Math.min(wire.policyMaxSpeedLevel, mMaxMotionSpeed),
                    Math.min(wire.policyMaxDistanceMeters, mMaxMotionDistanceM),
                    Math.min(wire.hardStopAfterMs, Math.min(mAutoStopMs, 3000)));
            SpeedLevelDriveController.Acknowledgement ack = mRelativeController.submit(bounded);
            relativeAck(cmd, ack.state == SpeedLevelDriveController.State.ACTUATOR_ACCEPTED
                    ? "SDK_SUBMITTED" : ack.state.name(),
                    ack.rejectReason == null ? null : ack.rejectReason.name(), ack.effectiveSpeedLevel, receivedAt);
        } catch (RuntimeException error) {
            relativeAck(cmd, "REJECTED", "INVALID_COMMAND", null, receivedAt);
        }
    }

    private boolean isMotionInterlocked() {
        if (!mBaseMotionEnabled) return true;
        if (!mCollisionGuardEnabled && !mFallGuardEnabled) return false;
        if (!BuildConfig.SAFETY_MONITOR_ENABLED) return true;
        return mSafetyMonitor == null || !mSafetyMonitor.hasRequiredCoverage();
    }

    private void safeMoveBody(InteractCommand.MotionData motion) {
        if (motion == null || mSdkBridge == null) return;
        if (mRelativeController != null && mRelativeController.isActive()) {
            publishSafetyBlocked("RELATIVE_MOTION_BUSY");
            return;
        }
        if (System.currentTimeMillis() < mRemoteBodyControlActiveUntilMs) {
            // Do not arm a second watchdog and cut an in-progress joystick
            // movement. The remote-control deadman remains responsible.
            publishStatus("remote", "{\"state\":\"MOTION_IGNORED_REMOTE_ACTIVE\"}");
            return;
        }
        if (isMotionInterlocked()) {
            publishSafetyBlocked(!mBaseMotionEnabled ? "BASE_MOTION_LOCKED" : "REQUIRED_SENSOR_UNAVAILABLE");
            mSdkBridge.emergencyStop();
            return;
        }
        float distance = (float) Math.sqrt(motion.x * motion.x + motion.y * motion.y);
        if (distance > mMaxMotionDistanceM || Math.abs(motion.theta) > 360f) {
            publishSafetyBlocked("MOTION_LIMIT_EXCEEDED");
            mSdkBridge.emergencyStop();
            return;
        }
        mMotionGuardHandler.removeCallbacks(mMotionGuardStopRunnable);
        mActiveMotionScenarioRunId = mActiveScenarioRunId;
        int targetSpeed = motion.speed > 0 ? motion.speed : 5;
        mSdkBridge.moveBody(motion.x, motion.y, motion.theta, Math.min(Math.max(1, targetSpeed), Math.min(7, mMaxMotionSpeed)));
        int dynamicWatchdogMs = Math.max(mAutoStopMs, (int) ((distance / 0.2f + Math.abs(motion.theta) / 25f) * 1000f) + 4000);
        mLegacyMotionUntilMs = SystemClock.elapsedRealtime() + dynamicWatchdogMs;
        mMotionGuardHandler.postDelayed(mMotionGuardStopRunnable, dynamicWatchdogMs);
        publishScenarioStatus(mActiveMotionScenarioRunId, "MOTION_STARTED");
        publishStatus("safety", "{\"state\":\"MOTION_ALLOWED_WITH_WATCHDOG\",\"timeout_ms\":" + dynamicWatchdogMs + "}");
    }

    private void runBehaviorSafely(InteractCommand.BehaviorData behavior) {
        if (behavior == null) return;
        String action = behavior.action == null ? "" : behavior.action.trim().toLowerCase();
        if ("follow_face".equals(action) || "follow_object".equals(action)) {
            publishSafetyBlocked("FOLLOW_BEHAVIOR_BLOCKED");
            if (mSdkBridge != null) mSdkBridge.emergencyStop();
            return;
        }
        if (mSdkBridge != null) mSdkBridge.runBehavior(behavior);
    }

    private void publishSafetyBlocked(String reason) {
        publishStatus("safety", "{\"state\":\"MOTION_BLOCKED\",\"reason\":\"" + escapeJson(reason) + "\"}");
    }

    /**
     * Sensor-triggered safety notices use the same Thai TTS path as normal
     * dialogue.  They are rate-limited so a persistent obstacle cannot queue
     * repeated audio while the robot is already stopped.
     */
    private boolean claimSafetySpeechSlot(String reason) {
        long now = System.currentTimeMillis();
        if (now - mLastSafetySpeechAtMs < SAFETY_SPEECH_COOLDOWN_MS) {
            publishStatus("safety", "{\"state\":\"SAFETY_NOTICE_SUPPRESSED\",\"reason\":\""
                    + escapeJson(reason) + "\"}");
            return false;
        }
        mLastSafetySpeechAtMs = now;
        return true;
    }

    /** Starts only after claimSafetySpeechSlot has accepted this safety event. */
    private void announceSafetyBreach(String reason, float meters) {
        final String phrase = "SONAR".equals(reason) ? "ฉันขอหลบ" : "ฉันจะระวัง";
        notifySpeechStatus(phrase, "Safety Guard: " + reason + " " + meters + " m");
        if (mSdkBridge != null) mSdkBridge.setExpression("SONAR".equals(reason) ? "SHOCKED" : "DOUBTING");
        if (mAudioPlayer == null) {
            publishStatus("tts", "{\"state\":\"ERROR\",\"message\":\"audio_player_unavailable\"}");
            return;
        }
        publishStatus("tts", "{\"state\":\"SAFETY_NOTICE_REQUESTED\",\"text\":\""
                + escapeJson(phrase) + "\"}");
        TtsClient.synthesize(phrase, null, null, null, null, new TtsClient.OnTtsResult() {
            @Override public void onSuccess(byte[] wavBytes) {
                notifySpeechStatus(phrase, "กำลังแจ้งเตือนความปลอดภัย");
                mAudioPlayer.playBytes(wavBytes, new AudioPlaybackManager.OnAudioFinishListener() {
                    @Override public void onFinished() {
                        notifySpeechStatus(phrase, "แจ้งเตือนความปลอดภัยแล้ว");
                        publishStatus("tts", "{\"state\":\"SAFETY_NOTICE_COMPLETED\",\"text\":\""
                                + escapeJson(phrase) + "\"}");
                    }
                });
            }

            @Override public void onError(String message) {
                Log.e(TAG, "Safety Thai TTS failed: " + message);
                notifySpeechStatus(phrase, "แจ้งเตือนเสียงไม่สำเร็จ");
                publishStatus("tts", "{\"state\":\"SAFETY_NOTICE_ERROR\",\"message\":\""
                        + escapeJson(message) + "\"}");
            }
        });
    }

    /** Shows a concise Thai narration for every command, including non-speech commands. */
    private void announceIncomingCommand(String topic, String message) {
        String narration = "ได้รับคำสั่งใหม่แล้ว";
        try {
            if (isTopic(topic, "cmd/interact") || isTopic(topic, "cmd/speak") || isTopic(topic, "audio")) {
                InteractCommand command = mGson.fromJson(message, InteractCommand.class);
                if (command != null && command.text != null && !command.text.trim().isEmpty()) {
                    narration = command.text.trim();
                } else if (command != null && command.remoteControl != null) {
                    narration = "ควบคุมด้วยจอยสติ๊ก";
                } else if (command != null && command.action != null && command.face != null) {
                    narration = "สีหน้า " + command.face + " และท่าทาง #" + command.action.actionId;
                } else if (command != null && command.action != null) {
                    narration = "ท่าทาง #" + command.action.actionId;
                } else if (command != null && command.face != null) {
                    narration = "เปลี่ยนสีหน้า: " + command.face;
                } else {
                    narration = "กำลังรับคำสั่ง";
                }
            } else if (isTopic(topic, "cmd/safety")) narration = "กำลังตั้งโหมดกันชนและกันตก";
            else if (isTopic(topic, "cmd/stop") || isTopic(topic, "stop")) narration = "กำลังหยุดการทำงานทันที";
            else if (isTopic(topic, "cmd/motion") || isTopic(topic, "movement")) narration = "กำลังรับคำสั่งเคลื่อนที่";
            else if (isTopic(topic, "cmd/head") || isTopic(topic, "cmd/head_sequence")) narration = "กำลังรับคำสั่งขยับศีรษะ";
            else if (isTopic(topic, "cmd/expression")) narration = "กำลังรับคำสั่งเปลี่ยนสีหน้า";
            else if (isTopic(topic, "cmd/action") || isTopic(topic, "cmd/emotional")) narration = "กำลังรับคำสั่งท่าทาง";
            else if (isTopic(topic, "cmd/lights")) narration = "กำลังรับคำสั่งไฟล้อ";
            else if (isTopic(topic, "cmd/remote")) narration = "กำลังรับคำสั่งจอยสติ๊ก";
            else if (isTopic(topic, "cmd/behavior")) narration = "กำลังรับคำสั่งพฤติกรรม";
            else if (isTopic(topic, "cmd/vision") || isTopic(topic, "vision")) narration = "กำลังรับคำสั่งกล้องและการมองเห็น";
            else if (isTopic(topic, "cmd/youtube")) narration = "กำลังรับคำสั่งเปิด YouTube";
            else if (isTopic(topic, "cmd/cancel")) narration = "กำลังยกเลิกคำสั่งปัจจุบัน";
        } catch (Exception error) {
            Log.w(TAG, "Unable to narrate command: " + error.getMessage());
        }
        notifySpeechStatus(narration, "รับคำสั่งแล้ว");
        if (mScreenTickerOverlay != null) {
            mScreenTickerOverlay.show(narration, 6000);
        }
    }

    @Override
    public void onConnectionStatusChanged(boolean isConnected, String statusMsg) {
        Log.d(TAG, "Status changed (" + mActiveEndpointType + "): " + statusMsg);
        if (!isConnected && mRelativeController != null && mRelativeController.isActive()) mRelativeController.cancel("DISCONNECTED");
        if (isConnected) {
            mConnectionFailureCount = 0;
            mIsFallbackAttempt = false;
            String activeDesc = "LAN".equals(mActiveEndpointType)
                    ? "LAN :1884 (" + BuildConfig.DIRECT_MQTT_HOST + ")"
                    : "Domain WSS (" + BuildConfig.DOMAIN_MQTT_HOST + BuildConfig.DOMAIN_MQTT_PATH + ")";
            statusMsg = "Connected via " + activeDesc;
        } else {
            // Auto fallback logic when in AUTO mode
            if (mBrokerMode == BROKER_MODE_AUTO) {
                mConnectionFailureCount++;
                if ("LAN".equals(mActiveEndpointType) && !mIsFallbackAttempt) {
                    Log.w(TAG, "LAN MQTT connection failed (" + statusMsg + "). Scheduling fallback to Domain WSS.");
                    mIsFallbackAttempt = true;
                    mFallbackHandler.removeCallbacksAndMessages(null);
                    mFallbackHandler.postDelayed(new Runnable() {
                        @Override public void run() {
                            connectDomainWssMqtt("LAN ล้มเหลว — สลับไป Domain WSS อัตโนมัติ");
                        }
                    }, 1200L);
                } else if ("DOMAIN".equals(mActiveEndpointType) && mIsFallbackAttempt) {
                    if (mConnectionFailureCount >= 3) {
                        Log.w(TAG, "Domain WSS also failed. Resetting loop to retry LAN.");
                        mIsFallbackAttempt = false;
                        mConnectionFailureCount = 0;
                    }
                }
            }
        }

        String state = isConnected ? "connected" : "disconnected";
        publishStatus("connection", "{\"state\":\"" + state + "\",\"endpoint\":\"" + mActiveEndpointType
                + "\",\"message\":\"" + escapeJson(statusMsg) + "\"}");
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

    private void notifySafetyStatus(String title, String detail, boolean danger) {
        mSafetyScreenTitle = title == null ? "Operator Drive" : title;
        mSafetyScreenDetail = detail == null ? "" : detail;
        mSafetyScreenDanger = danger;
        if (mSafetyStatusListener != null) {
            mSafetyStatusListener.onSafetyStatusChanged(mSafetyScreenTitle, mSafetyScreenDetail, danger);
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

    private String getBatteryInfoJson() {
        try {
            IntentFilter ifilter = new IntentFilter(Intent.ACTION_BATTERY_CHANGED);
            Intent batteryStatus = registerReceiver(null, ifilter);
            if (batteryStatus != null) {
                int level = batteryStatus.getIntExtra(BatteryManager.EXTRA_LEVEL, -1);
                int scale = batteryStatus.getIntExtra(BatteryManager.EXTRA_SCALE, -1);
                int status = batteryStatus.getIntExtra(BatteryManager.EXTRA_STATUS, -1);
                boolean isCharging = status == BatteryManager.BATTERY_STATUS_CHARGING
                        || status == BatteryManager.BATTERY_STATUS_FULL;
                int pct = (scale > 0 && level >= 0) ? Math.round(level * 100f / (float) scale) : -1;
                return "{\"level\":" + pct + ",\"charging\":" + isCharging + "}";
            }
        } catch (Exception ignored) {}
        return "{\"level\":-1,\"charging\":false}";
    }

    private void startInstalledApkDigest() {
        final File installedApk = new File(getApplicationInfo().sourceDir);
        long packageUpdatedAtMs = 0L;
        try {
            packageUpdatedAtMs = getPackageManager().getPackageInfo(getPackageName(), 0).lastUpdateTime;
        } catch (Exception error) {
            Log.w(TAG, "Unable to read package update metadata", error);
        }
        final String digestKey = installedApk.getAbsolutePath() + "|" + BuildConfig.VERSION_CODE
                + "|" + packageUpdatedAtMs + "|" + installedApk.length() + "|" + installedApk.lastModified();
        if (digestKey.equals(mInstalledApkDigestKey)
                && InstalledApkDigest.isSha256(mInstalledApkSha256)) {
            return;
        }
        mInstalledApkDigestKey = digestKey;
        mInstalledApkSha256 = "";
        mInstalledApkDigestState = "PENDING";
        Thread digestThread = new Thread(new Runnable() {
            @Override public void run() {
                try {
                    String digest = InstalledApkDigest.sha256(installedApk);
                    if (!InstalledApkDigest.isSha256(digest)
                            || !digestKey.equals(mInstalledApkDigestKey)) {
                        mInstalledApkDigestState = "ERROR";
                        return;
                    }
                    mInstalledApkSha256 = digest;
                    mInstalledApkDigestState = "READY";
                } catch (Exception error) {
                    mInstalledApkSha256 = "";
                    mInstalledApkDigestState = "ERROR";
                    Log.e(TAG, "Unable to hash installed base APK", error);
                }
            }
        }, "zenbo-apk-digest");
        digestThread.setDaemon(true);
        digestThread.start();
    }

    private void publishHeartbeat() {
        if (mMqttManager == null) return;
        long heartbeatAtMs = System.currentTimeMillis();
        long heartbeatSeq = ++mHeartbeatSeq;
        String robotSlug = mTopicPrefix.startsWith("zenbo/")
                ? mTopicPrefix.substring("zenbo/".length()) : mTopicPrefix;
        boolean robotApiReady = mSdkBridge != null && mSdkBridge.isReady();
        boolean safetyMonitorActive = mSafetyMonitor != null;
        // Compiled integration is OFF until the installed artifact passes calibration.
        // Advertise the executable capability, not merely compiled helper classes.
        boolean canonicalRelativeMotionEnabled = BuildConfig.RELATIVE_MOTION_ENABLED
                && BuildConfig.SAFETY_MONITOR_ENABLED && robotApiReady && safetyMonitorActive
                && mSafetyMonitor.hasRequiredCoverage();
        int policyMaxSpeedLevel = Math.min(7, Math.max(1, mMaxMotionSpeed));
        boolean apkDigestReady = InstalledApkDigest.isSha256(mInstalledApkSha256);
        String apkHashField = apkDigestReady
                ? ",\"apk_sha256\":\"" + mInstalledApkSha256 + "\"" : "";
        String artifact = "{\"hash_state\":\"" + escapeJson(mInstalledApkDigestState) + "\""
                + ",\"hash_scope\":\"BASE_APK_FILE\""
                + ",\"version_code\":" + BuildConfig.VERSION_CODE
                + (apkDigestReady ? ",\"base_apk_sha256\":\"" + mInstalledApkSha256 + "\"" : "")
                + "}";
        String payload = "{\"state\":\"connected\",\"app\":\"Zenbo Client Bridge\""
                + ",\"version_name\":\"" + BuildConfig.VERSION_NAME + "\""
                + apkHashField
                + ",\"robot_slug\":\"" + escapeJson(robotSlug) + "\""
                + ",\"client_id\":\"" + escapeJson(mMqttManager.getClientId()) + "\""
                + ",\"client_ip\":\"" + escapeJson(getClientIpAddress()) + "\""
                + ",\"topic_prefix\":\"" + escapeJson(mTopicPrefix) + "\""
                + ",\"broker\":{\"mode\":\"" + escapeJson(getBrokerModeName()) + "\",\"summary\":\"" + escapeJson(getActiveBrokerSummary()) + "\"}"
                + ",\"battery\":" + getBatteryInfoJson()
                + ",\"wifi\":" + getWifiInfoJson()
                + ",\"robot_api_ready\":" + robotApiReady
                + ",\"safety_monitor_active\":" + safetyMonitorActive
                + ",\"safety_guard\":{\"collision_guard_enabled\":" + mCollisionGuardEnabled
                + ",\"fall_guard_enabled\":" + mFallGuardEnabled
                + ",\"base_motion_enabled\":" + mBaseMotionEnabled
                + ",\"motion_interlocked\":" + isMotionInterlocked() + "}"
                + ",\"motion\":{\"body_relative\":{\"supported\":" + canonicalRelativeMotionEnabled + ","
                + "\"speed_levels\":[1,2,3,4,5,6,7],"
                + "\"policy_max_speed_level\":" + policyMaxSpeedLevel + ","
                + "\"max_distance_m\":" + mMaxMotionDistanceM + ","
                + "\"max_body_speed\":" + policyMaxSpeedLevel + ","
                + "\"auto_stop_ms\":" + mAutoStopMs + ","
                + "\"watchdog_hard_upper_bound\":false}}"
                + ",\"safety_monitor\":{\"enabled\":" + BuildConfig.SAFETY_MONITOR_ENABLED
                + ",\"active\":" + safetyMonitorActive
                + ",\"required_sensor_coverage\":" + (mSafetyMonitor != null && mSafetyMonitor.hasRequiredCoverage()) + "}"
                + ",\"artifact\":" + artifact
                + ",\"applied_policy\":{\"epoch\":" + mSafetyPolicyEpoch
                + ",\"base_motion_enabled\":" + mBaseMotionEnabled
                + ",\"collision_guard_enabled\":" + mCollisionGuardEnabled
                + ",\"fall_guard_enabled\":" + mFallGuardEnabled
                + ",\"max_distance_m\":" + mMaxMotionDistanceM
                + ",\"max_body_speed_level\":" + policyMaxSpeedLevel
                + ",\"watchdog_hard_upper_bound\":false}"
                + ",\"boot_session_id\":\"" + mBootSessionId + "\""
                + ",\"heartbeat_seq\":" + heartbeatSeq
                + ",\"liveness\":{\"boot_session_id\":\"" + mBootSessionId + "\""
                + ",\"heartbeat_seq\":" + heartbeatSeq
                + ",\"timestamp_ms\":" + heartbeatAtMs + "}"
                + ",\"capabilities\":[\"THAI_TTS\",\"EXPRESSION\",\"HEAD\",\"WHEEL_LIGHTS\",\"VISION_PERSON\",\"GESTURE_POINT\",\"DISPLAY_URL\",\"SAFETY_SONAR\",\"SAFETY_DROP_LASER\",\"CALIBRATED_ROUTE\",\"SCREEN_TICKER\",\"REMOTE_OTA\"]"
                + ",\"timestamp_ms\":" + heartbeatAtMs + "}";
        mMqttManager.publish(mTopicPrefix + "/status/heartbeat", payload, 1, false);
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

    private String getWifiInfoJson() {
        try {
            WifiManager wifi = (WifiManager) getApplicationContext().getSystemService(WIFI_SERVICE);
            if (wifi != null) {
                WifiInfo info = wifi.getConnectionInfo();
                if (info != null) {
                    String ssid = info.getSSID();
                    if (ssid != null && ssid.startsWith("\"") && ssid.endsWith("\"")) {
                        ssid = ssid.substring(1, ssid.length() - 1);
                    }
                    int rssi = info.getRssi();
                    int level = WifiManager.calculateSignalLevel(rssi, 5);
                    return "{\"ssid\":\"" + escapeJson(ssid != null ? ssid : "") + "\",\"rssi\":" + rssi + ",\"level\":" + level + "}";
                }
            }
        } catch (Exception ignored) {}
        return "{\"ssid\":\"unknown\",\"rssi\":0,\"level\":0}";
    }

    private String escapeJson(String value) {
        return JsonStrings.escape(value);
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
        if (mRelativeController != null && mRelativeController.isActive()) mRelativeController.cancel();
        mRelativeDeadline.shutdownNow();
        cancelRemoteControlSafety();
        mMotionGuardHandler.removeCallbacks(mMotionGuardStopRunnable);
        if (mSafetyMonitor != null) mSafetyMonitor.stop();
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
        mSafetyStatusListener = null;
    }

    private void announceVoicePrompt(final String phrase) {
        if (phrase == null || phrase.trim().isEmpty()) return;
        notifySpeechStatus(phrase, "กำลังแจ้งเตือนด้วยเสียง");
        TtsClient.synthesize(phrase, "male_child", null, null, null, new TtsClient.OnTtsResult() {
            @Override
            public void onSuccess(byte[] wavBytes) {
                mAudioPlayer.playBytes(wavBytes, null);
            }

            @Override
            public void onError(String message) {
                if (mSdkBridge != null) mSdkBridge.speak(phrase);
            }
        });
    }

    private void handleTickerCommand(String message) {
        try {
            String text = "";
            long durationMs = 10000L;
            if (message != null && message.trim().startsWith("{")) {
                org.json.JSONObject json = new org.json.JSONObject(message);
                text = json.optString("text", json.optString("message", ""));
                durationMs = json.optLong("duration_ms", 10000L);
            } else if (message != null) {
                text = message.trim();
            }
            if (!TextUtils.isEmpty(text)) {
                if (mScreenTickerOverlay != null) {
                    mScreenTickerOverlay.show(text, durationMs);
                }
                notifySpeechStatus(text, "แสดงข้อความวิ่ง (Ticker)");
                publishStatus("action_done", "{\"status\":\"SUCCESS\",\"type\":\"ticker\",\"text\":\"" + escapeJson(text) + "\"}");
            }
        } catch (Exception e) {
            Log.e(TAG, "Error handling ticker command: " + e.getMessage(), e);
        }
    }

    private void handleRemoteUpdateCommand(String message) {
        if (!BuildConfig.SELF_UPDATE_ENABLED) {
            Log.i(TAG, "Self-update is disabled in this build");
            publishStatus("update", "{\"state\":\"DISABLED\",\"message\":\"ระบบอัปเดตอัตโนมัติถูกปิดตามการตั้งค่า\"}");
            return;
        }
        try {
            Log.i(TAG, "Received remote update command: " + message);
            org.json.JSONObject json = null;
            if (message != null && !message.trim().isEmpty()) {
                try {
                    json = new org.json.JSONObject(message);
                } catch (Exception ignored) {}
            }
            final String action = json != null ? json.optString("action", "") : "";
            final String customUrl = json != null ? json.optString("url", "") : "";
            final String customSha = json != null ? json.optString("sha256", "") : "";

            publishStatus("update", "{\"state\":\"CHECKING\",\"message\":\"กำลังตรวจสอบอัปเดต...\"}");

            // If action is "check" or no custom url is provided, use SemiAutomaticUpdateManager
            if (TextUtils.isEmpty(customUrl) || "check".equalsIgnoreCase(action)) {
                if (mUpdateManager == null) {
                    mUpdateManager = new SemiAutomaticUpdateManager(this);
                }
                mUpdateManager.checkAndDownload(new SemiAutomaticUpdateManager.Listener() {
                    @Override
                    public void onStatus(String text, boolean isError) {
                        Log.i(TAG, "Update status: " + text);
                        publishStatus("update", "{\"state\":\"" + (isError ? "ERROR" : "PROGRESS")
                                + "\",\"message\":\"" + escapeJson(text) + "\"}");
                    }

                    @Override
                    public void onInstallReady(final File apkFile, final String versionName, final String notes) {
                        publishStatus("update", "{\"state\":\"READY_FOR_INSTALL\",\"version\":\""
                                + escapeJson(versionName) + "\"}");
                        if (mScreenTickerOverlay != null) {
                            mScreenTickerOverlay.show("อัปเดต v" + versionName + " พร้อมแล้ว แตะหน้าจอเพื่อติดตั้ง", 12000);
                        }
                        announceVoicePrompt("มีอัปเดตเวอร์ชันใหม่พร้อมติดตั้งครับ กรุณากดยืนยันบนหน้าจอ");
                        new Handler(Looper.getMainLooper()).post(new Runnable() {
                            @Override public void run() {
                                SemiAutomaticUpdateManager.requestUserConfirmedInstall(ZenboClientService.this, apkFile);
                            }
                        });
                    }
                });
                return;
            }

            // Otherwise, download from customUrl
            final String versionName = json.optString("version_name", "latest");
            if (mScreenTickerOverlay != null) {
                mScreenTickerOverlay.show("ตรวจพบอัปเดตแอป v" + versionName + " กำลังดาวน์โหลด...", 8000);
            }
            publishStatus("update", "{\"state\":\"DOWNLOADING\",\"version\":\"" + escapeJson(versionName) + "\"}");

            new Thread(new Runnable() {
                @Override
                public void run() {
                    try {
                        File cacheDir = new File(getCacheDir(), "updates");
                        if (!cacheDir.exists()) cacheDir.mkdirs();
                        final File dest = new File(cacheDir, "zenbo-update.apk");

                        java.net.HttpURLConnection conn = (java.net.HttpURLConnection) new java.net.URL(customUrl).openConnection();
                        if (conn instanceof javax.net.ssl.HttpsURLConnection) {
                            ((javax.net.ssl.HttpsURLConnection) conn).setSSLSocketFactory(
                                    com.hackathon.zenboclient.mqtt.SslUtils.getCompatibleSocketFactory());
                        }
                        conn.setConnectTimeout(15000);
                        conn.setReadTimeout(60000);
                        conn.connect();
                        if (conn.getResponseCode() == 200) {
                            java.io.InputStream in = conn.getInputStream();
                            java.io.FileOutputStream out = new java.io.FileOutputStream(dest);
                            byte[] buf = new byte[8192];
                            int len;
                            while ((len = in.read(buf)) != -1) {
                                out.write(buf, 0, len);
                            }
                            out.close();
                            in.close();

                            if (!TextUtils.isEmpty(customSha)) {
                                java.security.MessageDigest md = java.security.MessageDigest.getInstance("SHA-256");
                                java.io.FileInputStream fis = new java.io.FileInputStream(dest);
                                byte[] dBuf = new byte[8192];
                                int dLen;
                                while ((dLen = fis.read(dBuf)) != -1) md.update(dBuf, 0, dLen);
                                fis.close();
                                byte[] hash = md.digest();
                                StringBuilder hex = new StringBuilder();
                                for (byte b : hash) hex.append(String.format("%02x", b));
                                if (!customSha.equalsIgnoreCase(hex.toString())) {
                                    dest.delete();
                                    publishStatus("update", "{\"state\":\"ERROR\",\"message\":\"SHA-256 ไม่ตรงกัน\"}");
                                    return;
                                }
                            }

                            Log.i(TAG, "Update downloaded, prompting user install...");
                            publishStatus("update", "{\"state\":\"READY_FOR_INSTALL\",\"version\":\"" + escapeJson(versionName) + "\"}");
                            announceVoicePrompt("มีอัปเดตเวอร์ชันใหม่พร้อมติดตั้งครับ กรุณากดยืนยันบนหน้าจอ");
                            new Handler(Looper.getMainLooper()).post(new Runnable() {
                                @Override
                                public void run() {
                                    if (mScreenTickerOverlay != null) {
                                        mScreenTickerOverlay.show("ดาวน์โหลด v" + versionName + " สำเร็จ แตะหน้าจอเพื่อติดตั้ง", 10000);
                                    }
                                    SemiAutomaticUpdateManager.requestUserConfirmedInstall(ZenboClientService.this, dest);
                                }
                            });
                        } else {
                            publishStatus("update", "{\"state\":\"ERROR\",\"message\":\"HTTP " + conn.getResponseCode() + "\"}");
                        }
                    } catch (Exception e) {
                        Log.e(TAG, "Failed to download remote update: " + e.getMessage(), e);
                        publishStatus("update", "{\"state\":\"ERROR\",\"message\":\"" + escapeJson(e.getMessage()) + "\"}");
                    }
                }
            }).start();
        } catch (Exception e) {
            Log.e(TAG, "Malformed update command: " + e.getMessage(), e);
            publishStatus("update", "{\"state\":\"ERROR\",\"message\":\"" + escapeJson(e.getMessage()) + "\"}");
        }
    }
}
