package com.hackathon.zenboclient.ui;

import android.content.Context;
import android.graphics.Color;
import android.graphics.PixelFormat;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.text.TextUtils;
import android.util.Log;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.widget.FrameLayout;
import android.widget.TextView;

/**
 * ScreenTickerOverlay displays a floating ticker / narration banner at the bottom
 * of the screen via WindowManager, persisting across YouTube, browsers, and Zenbo activities.
 */
public class ScreenTickerOverlay {
    private static final String TAG = "ScreenTickerOverlay";

    private final Context mContext;
    private final WindowManager mWindowManager;
    private final Handler mMainHandler = new Handler(Looper.getMainLooper());

    private FrameLayout mOverlayView;
    private TextView mTickerText;
    private boolean mIsAttached = false;

    private final Runnable mHideRunnable = new Runnable() {
        @Override
        public void run() {
            hide();
        }
    };

    public ScreenTickerOverlay(Context context) {
        this.mContext = context.getApplicationContext();
        this.mWindowManager = (WindowManager) mContext.getSystemService(Context.WINDOW_SERVICE);
    }

    public void show(final String text, final long durationMs) {
        if (TextUtils.isEmpty(text)) {
            return;
        }

        mMainHandler.post(new Runnable() {
            @Override
            public void run() {
                try {
                    ensureViewCreated();
                    if (mTickerText != null) {
                        mTickerText.setText(text);
                        mTickerText.setSelected(false);
                        mTickerText.setSelected(true); // restart marquee
                    }

                    if (mOverlayView != null) {
                        mOverlayView.setVisibility(View.VISIBLE);
                    }

                    mMainHandler.removeCallbacks(mHideRunnable);
                    if (durationMs > 0) {
                        mMainHandler.postDelayed(mHideRunnable, durationMs);
                    }
                } catch (Exception e) {
                    Log.w(TAG, "Failed to display overlay ticker: " + e.getMessage());
                }
            }
        });
    }

    public void hide() {
        mMainHandler.post(new Runnable() {
            @Override
            public void run() {
                if (mOverlayView != null) {
                    mOverlayView.setVisibility(View.GONE);
                }
            }
        });
    }

    private void ensureViewCreated() {
        if (mOverlayView != null && mIsAttached) {
            return;
        }

        // On Android 6 (API 23), TYPE_SYSTEM_ALERT is standard
        int layoutType;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            layoutType = WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY;
        } else {
            layoutType = WindowManager.LayoutParams.TYPE_SYSTEM_ALERT;
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            if (!Settings.canDrawOverlays(mContext)) {
                Log.d(TAG, "SYSTEM_ALERT_WINDOW permission not yet granted; overlay skipped");
                return;
            }
        }

        mOverlayView = new FrameLayout(mContext);
        mOverlayView.setBackgroundColor(Color.parseColor("#E60B0F19")); // dark slate transparent
        mOverlayView.setClickable(true);
        mOverlayView.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                hide();
            }
        });

        mTickerText = new TextView(mContext);
        mTickerText.setTextColor(Color.parseColor("#38BDF8")); // cyan-400
        mTickerText.setTextSize(TypedValue.COMPLEX_UNIT_SP, 22);
        mTickerText.setSingleLine(true);
        mTickerText.setEllipsize(TextUtils.TruncateAt.MARQUEE);
        mTickerText.setMarqueeRepeatLimit(-1);
        mTickerText.setGravity(Gravity.CENTER_VERTICAL);
        mTickerText.setPadding(32, 16, 32, 16);

        FrameLayout.LayoutParams textParams = new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.WRAP_CONTENT
        );
        textParams.gravity = Gravity.CENTER_VERTICAL;
        mOverlayView.addView(mTickerText, textParams);

        WindowManager.LayoutParams params = new WindowManager.LayoutParams(
                WindowManager.LayoutParams.MATCH_PARENT,
                WindowManager.LayoutParams.WRAP_CONTENT,
                layoutType,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
                        | WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL
                        | WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
                PixelFormat.TRANSLUCENT
        );
        params.gravity = Gravity.BOTTOM;

        try {
            mWindowManager.addView(mOverlayView, params);
            mIsAttached = true;
            Log.i(TAG, "ScreenTickerOverlay attached successfully");
        } catch (Exception e) {
            Log.w(TAG, "Cannot attach ScreenTickerOverlay: " + e.getMessage());
        }
    }

    public static boolean canDrawOverlays(Context context) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            return Settings.canDrawOverlays(context);
        }
        return true;
    }
}
