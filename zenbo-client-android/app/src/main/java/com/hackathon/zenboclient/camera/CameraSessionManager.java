package com.hackathon.zenboclient.camera;

import android.content.Context;
import android.util.Log;
import com.hackathon.zenboclient.model.InteractCommand;
import org.json.JSONException;
import org.json.JSONObject;
import java.util.UUID;

/**
 * WebRTC teleop camera/audio stub for Zenbo.
 *
 * This manager consumes MQTT camera commands and emits lifecycle status events.
 * It intentionally does not embed a real WebRTC stack yet; the peer connection,
 * camera capture, and two-way audio will be wired here once the low-level SDK
 * media permissions are validated on the physical robot.
 */
public class CameraSessionManager {
    private static final String TAG = "ZenboCamera";

    public interface StatusPublisher {
        void publishCameraStatus(String state, JSONObject detail);
    }

    private final Context mContext;
    private StatusPublisher mPublisher;
    private String mActiveSessionId;

    public CameraSessionManager(Context context) {
        this.mContext = context;
    }

    public void setStatusPublisher(StatusPublisher publisher) {
        this.mPublisher = publisher;
    }

    public void handleCameraCommand(InteractCommand.CameraData camera) {
        if (camera == null || camera.action == null) {
            Log.w(TAG, "Ignoring malformed camera command");
            return;
        }
        switch (camera.action.toLowerCase()) {
            case "start":
                mActiveSessionId = camera.sessionId != null ? camera.sessionId : UUID.randomUUID().toString();
                Log.i(TAG, "Camera session requested: " + mActiveSessionId);
                JSONObject readyDetail = sessionDetail(mActiveSessionId, "camera-ready");
                try {
                    readyDetail.put("state", "READY");
                    readyDetail.put("protocol", "webrtc-stream");
                    readyDetail.put("fps", 15);
                    readyDetail.put("width", 640);
                    readyDetail.put("height", 480);
                } catch (JSONException ignored) {}
                emit("READY", readyDetail);
                break;
            case "stop":
                Log.i(TAG, "Camera session stopped: " + mActiveSessionId);
                String sid = mActiveSessionId != null ? mActiveSessionId : camera.sessionId;
                JSONObject stopDetail = sessionDetail(sid, "stopped-by-operator");
                try {
                    stopDetail.put("state", "STOPPED");
                } catch (JSONException ignored) {}
                emit("STOPPED", stopDetail);
                mActiveSessionId = null;
                break;
            case "offer":
                Log.i(TAG, "Received remote WebRTC offer for session: " + camera.sessionId);
                JSONObject answerDetail = sessionDetail(camera.sessionId, "sdp-answer-ready");
                try {
                    answerDetail.put("state", "ANSWER");
                    answerDetail.put("type", "answer");
                } catch (JSONException ignored) {}
                emit("ANSWER", answerDetail);
                break;
            case "answer":
                Log.i(TAG, "Received remote WebRTC answer for session: " + camera.sessionId);
                JSONObject connDetail = sessionDetail(camera.sessionId, "remote-description-set");
                try {
                    connDetail.put("state", "CONNECTED");
                } catch (JSONException ignored) {}
                emit("CONNECTED", connDetail);
                break;
            case "candidate":
                Log.i(TAG, "Received remote ICE candidate for session: " + camera.sessionId);
                break;
            default:
                Log.w(TAG, "Unknown camera action: " + camera.action);
        }
    }

    private JSONObject sessionDetail(String sessionId, String note) {
        JSONObject detail = new JSONObject();
        try {
            detail.put("session_id", sessionId);
            detail.put("note", note);
        } catch (JSONException e) {
            Log.e(TAG, "Failed to build camera status JSON", e);
        }
        return detail;
    }

    private void emit(String state, JSONObject detail) {
        if (mPublisher != null) {
            mPublisher.publishCameraStatus(state, detail);
        }
    }
}
