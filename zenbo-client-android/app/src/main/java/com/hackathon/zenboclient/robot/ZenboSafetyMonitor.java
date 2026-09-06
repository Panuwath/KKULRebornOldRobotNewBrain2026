package com.hackathon.zenboclient.robot;

import android.content.Context;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorEventListener;
import android.hardware.SensorManager;
import android.os.SystemClock;
import android.util.Log;
import com.asus.robotframework.API.Utility;
import com.hackathon.zenboclient.model.InteractCommand;

/**
 * Reads the Zenbo-specific SensorManager streams described by ASUS: DROP_LASER
 * (five base-to-floor distances) and SONAR (surrounding obstacle distances).
 * It deliberately reports unavailable sensors; callers must keep movement
 * interlocked rather than pretending software has physical protection.
 */
public final class ZenboSafetyMonitor implements SensorEventListener {
    private static final String TAG = "ZenboSafetyMonitor";
    private static final long BREACH_DEBOUNCE_MS = 800L;
    private static final long SAMPLE_INTERVAL_MS = 1000L;

    public interface Listener {
        void onSafetyEvent(String state, String detail);
        void onSafetyBreach(String reason, float meters);
        void onSafetySample(String sensor, float meters);
    }

    private final SensorManager sensorManager;
    private final Listener listener;
    private final Sensor dropLaser;
    private final Sensor sonar;
    private boolean collisionGuard = true;
    private boolean fallGuard = true;
    private float collisionDistanceM = 0.35f;
    private float dropDistanceM = 0.16f;
    private long lastBreachAtMs;
    private long lastDropSampleAtMs;
    private long lastSonarSampleAtMs;

    public ZenboSafetyMonitor(Context context, Listener listener) {
        this.listener = listener;
        sensorManager = (SensorManager) context.getSystemService(Context.SENSOR_SERVICE);
        dropLaser = sensorManager == null ? null : sensorManager.getDefaultSensor(Utility.SensorType.DROP_LASER);
        sonar = sensorManager == null ? null : sensorManager.getDefaultSensor(Utility.SensorType.SONAR);
    }

    public void start() {
        if (sensorManager == null) {
            listener.onSafetyEvent("SENSOR_MANAGER_UNAVAILABLE", "android_sensor_manager_missing");
            return;
        }
        if (dropLaser != null) sensorManager.registerListener(this, dropLaser, SensorManager.SENSOR_DELAY_NORMAL);
        if (sonar != null) sensorManager.registerListener(this, sonar, SensorManager.SENSOR_DELAY_NORMAL);
        listener.onSafetyEvent("SENSORS_READY", "drop_laser=" + (dropLaser != null) + ",sonar=" + (sonar != null));
    }

    public void stop() {
        if (sensorManager != null) sensorManager.unregisterListener(this);
    }

    public void applyPolicy(InteractCommand.SafetyData policy) {
        if (policy == null) return;
        collisionGuard = policy.collisionGuardEnabled;
        fallGuard = policy.fallGuardEnabled;
        collisionDistanceM = clamp(policy.collisionDistanceM, 0.10f, 1.00f);
        dropDistanceM = clamp(policy.dropDistanceM, 0.08f, 0.50f);
    }

    public boolean hasRequiredCoverage() {
        return (!fallGuard || dropLaser != null) && (!collisionGuard || sonar != null);
    }

    @Override public void onSensorChanged(SensorEvent event) {
        if (event == null || event.sensor == null || event.values == null) return;
        int type = event.sensor.getType();
        if (type == Utility.SensorType.DROP_LASER) {
            float furthestGround = maxPositive(event.values, 5);
            sample("DROP_LASER_MAX", furthestGround);
            // A cliff increases base-to-floor distance; this is not a bumper.
            if (fallGuard && furthestGround >= dropDistanceM) breach("DROP_LASER", furthestGround);
        } else if (type == Utility.SensorType.SONAR) {
            float nearestObstacle = minPositive(event.values, 6);
            sample("SONAR_MIN", nearestObstacle);
            if (collisionGuard && nearestObstacle > 0f && nearestObstacle <= collisionDistanceM) breach("SONAR", nearestObstacle);
        }
    }

    @Override public void onAccuracyChanged(Sensor sensor, int accuracy) { }

    private void breach(String reason, float meters) {
        long now = SystemClock.elapsedRealtime();
        if (now - lastBreachAtMs < BREACH_DEBOUNCE_MS) return;
        lastBreachAtMs = now;
        Log.w(TAG, "Safety breach " + reason + " at " + meters + "m");
        listener.onSafetyBreach(reason, meters);
    }

    private void sample(String sensor, float meters) {
        long now = SystemClock.elapsedRealtime();
        boolean isDropLaser = sensor.startsWith("DROP_LASER");
        long lastSampleAtMs = isDropLaser ? lastDropSampleAtMs : lastSonarSampleAtMs;
        if (now - lastSampleAtMs < SAMPLE_INTERVAL_MS) return;
        if (isDropLaser) lastDropSampleAtMs = now;
        else lastSonarSampleAtMs = now;
        listener.onSafetySample(sensor, meters);
    }

    private static float minPositive(float[] values, int limit) {
        float result = Float.MAX_VALUE;
        for (int i = 0; i < Math.min(values.length, limit); i++) {
            float value = values[i];
            if (!Float.isNaN(value) && !Float.isInfinite(value) && value > 0f && value < result) result = value;
        }
        return result == Float.MAX_VALUE ? 0f : result;
    }

    private static float maxPositive(float[] values, int limit) {
        float result = 0f;
        for (int i = 0; i < Math.min(values.length, limit); i++) {
            float value = values[i];
            if (!Float.isNaN(value) && !Float.isInfinite(value) && value > result) result = value;
        }
        return result;
    }

    private static float clamp(float value, float min, float max) {
        return Math.max(min, Math.min(max, value));
    }
}
