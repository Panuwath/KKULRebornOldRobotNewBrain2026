package com.hackathon.zenboclient.robot;

import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import java.util.Random;

/**
 * Natural Speech Gesture & Expression Controller for ASUS Zenbo.
 *
 * Ensures Zenbo ALWAYS displays vivid facial expressions and organic gestures
 * (nodding, head sway, subtle body actions) whenever speech is active.
 * Restores a friendly neutral pose when speech finishes.
 */
public class SpeechGestureController {
    private static final String TAG = "SpeechGesture";

    private final ZenboSdkBridge mSdkBridge;
    private final Handler mHandler;
    private final Random mRandom = new Random();

    private boolean mIsActive = false;
    private boolean mAllowHead = true;
    private boolean mAllowFace = true;
    private int mCycleCount = 0;
    private String mCurrentFace = "HAPPY";

    // Engaging facial expressions for conversational interaction
    private static final String[] ENGAGING_FACES = {
        "HAPPY", "PLEASED", "INTERESTED", "CONFIDENT", "EXPECTING", "ACTIVE"
    };

    public SpeechGestureController(ZenboSdkBridge sdkBridge) {
        this.mSdkBridge = sdkBridge;
        this.mHandler = new Handler(Looper.getMainLooper());
    }

    /**
     * Infer the best starting facial expression based on Thai utterance content.
     */
    public static String inferExpression(String text) {
        if (text == null || text.trim().isEmpty()) return "HAPPY";
        String lower = text.toLowerCase();
        if (lower.contains("สวัสดี") || lower.contains("ยินดี") || lower.contains("ขอบคุณ") || lower.contains("ครับ") || lower.contains("ค่ะ")) {
            return "HAPPY";
        }
        if (lower.contains("อะไร") || lower.contains("ที่ไหน") || lower.contains("อย่างไร") || lower.contains("ไหม") || lower.contains("?") || lower.contains("ค้นหา")) {
            return "INTERESTED";
        }
        if (lower.contains("ระวัง") || lower.contains("ขออภัย") || lower.contains("หยุด") || lower.contains("เตือน")) {
            return "CONFIDENT";
        }
        if (lower.contains("สำเร็จ") || lower.contains("เรียบร้อย") || lower.contains("เยี่ยม")) {
            return "PLEASED";
        }
        return "HAPPY";
    }

    private final Runnable mGestureCycle = new Runnable() {
        @Override
        public void run() {
            if (!mIsActive || mSdkBridge == null) return;

            mCycleCount++;

            // 1. Organic Head & Body Gestures
            if (mAllowHead) {
                try {
                    float yaw;
                    float pitch;

                    if (mCycleCount % 3 == 0) {
                        // Polite conversational nod
                        pitch = 10f;
                        yaw = (mRandom.nextFloat() * 6f) - 3f;
                    } else if (mCycleCount % 3 == 1) {
                        // Engaging slight upward tilt with natural yaw
                        pitch = 4f + mRandom.nextFloat() * 5f;
                        yaw = (mRandom.nextBoolean() ? 1 : -1) * (5f + mRandom.nextFloat() * 5f);
                    } else {
                        // Attentive listening tilt
                        pitch = 2f + mRandom.nextFloat() * 4f;
                        yaw = (mRandom.nextBoolean() ? 1 : -1) * (3f + mRandom.nextFloat() * 4f);
                    }

                    mSdkBridge.moveHead(yaw, pitch, 1);
                } catch (Exception e) {
                    Log.w(TAG, "Head gesture failed: " + e.getMessage());
                }
            }

            // 2. Continuous Facial Expression Variation
            if (mAllowFace && mCycleCount % 2 == 1) {
                try {
                    String nextFace = ENGAGING_FACES[mRandom.nextInt(ENGAGING_FACES.length)];
                    if (!nextFace.equals(mCurrentFace)) {
                        mCurrentFace = nextFace;
                        mSdkBridge.setExpression(nextFace);
                    }
                } catch (Exception e) {
                    Log.w(TAG, "Face gesture failed: " + e.getMessage());
                }
            }

            // 3. Subtle Canned Body Gestures (every 4th cycle during longer speech)
            if (mCycleCount % 4 == 0) {
                try {
                    // Canned Action 2 = Nod_1 (gentle nod)
                    mSdkBridge.playAction(2);
                } catch (Exception ignored) {}
            }

            // Dynamic timing: micro-gesture every 900..1500 ms for lively presence
            long nextDelayMs = 900L + mRandom.nextInt(600);
            mHandler.postDelayed(mGestureCycle, nextDelayMs);
        }
    };

    /**
     * Start speech gesture and facial animation.
     *
     * @param text The utterance text for mood inference
     * @param allowHead Whether head motion is permitted
     * @param allowFace Whether facial expression variation is permitted
     */
    public synchronized void start(String text, boolean allowHead, boolean allowFace) {
        stop();
        mIsActive = true;
        mAllowHead = allowHead;
        mAllowFace = allowFace;
        mCycleCount = 0;

        // 1. Immediately display an expressive face at speech onset
        if (mAllowFace && mSdkBridge != null) {
            mCurrentFace = inferExpression(text);
            try {
                mSdkBridge.setExpression(mCurrentFace);
            } catch (Exception e) {
                Log.w(TAG, "Initial face expression failed: " + e.getMessage());
            }
        }

        // 2. Immediate conversational greeting nod / head tilt towards listener
        if (mAllowHead && mSdkBridge != null) {
            try {
                mSdkBridge.moveHead(0f, 8f, 1);
            } catch (Exception ignored) {}
        }

        Log.d(TAG, "Speech gesture started (face=" + mCurrentFace + ", head=" + allowHead + ")");

        // Schedule next gesture cycle after brief initial greeting
        mHandler.postDelayed(mGestureCycle, 800L);
    }

    /**
     * Stop speech gesture animation and restore a friendly neutral pose.
     */
    public synchronized void stop() {
        mIsActive = false;
        mHandler.removeCallbacks(mGestureCycle);

        if (mSdkBridge != null) {
            try {
                // Smoothly return to friendly neutral face and head pose
                if (mAllowFace) {
                    mSdkBridge.setExpression("HAPPY");
                }
                if (mAllowHead) {
                    mSdkBridge.moveHead(0f, 5f, 1);
                }
            } catch (Exception ignored) {}
        }
        Log.d(TAG, "Speech gesture stopped — neutral pose restored");
    }

    public boolean isActive() {
        return mIsActive;
    }
}
