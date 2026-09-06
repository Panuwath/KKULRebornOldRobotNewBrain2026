package com.hackathon.zenboclient.drive;

import com.hackathon.zenboclient.robot.RobotMotionBridge;

/** Guarded adapter between the bounded relative controller and the Zenbo SDK. */
public final class SdkDriveActuator implements DriveActuator {
    private final RobotMotionBridge bridge;

    public SdkDriveActuator(RobotMotionBridge bridge) {
        if (bridge == null) {
            throw new IllegalArgumentException("Robot motion bridge is required");
        }
        this.bridge = bridge;
    }

    @Override
    public void moveRelative(float xMeters, float yMeters, float thetaDegrees, int speedLevel) {
        if (speedLevel < 1 || speedLevel > 7 || !Float.isFinite(xMeters)
                || !Float.isFinite(yMeters) || !Float.isFinite(thetaDegrees)
                || Math.abs(thetaDegrees) > 360f) {
            throw new IllegalArgumentException("Invalid bounded motion");
        }
        if (!bridge.isReady()) throw new IllegalStateException("Robot API is not ready");
        bridge.moveBody(xMeters, yMeters, thetaDegrees, speedLevel);
    }

    @Override
    public void stop() {
        bridge.emergencyStop();
    }
}
