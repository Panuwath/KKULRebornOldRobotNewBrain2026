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
        if (!bridge.isReady()) return;
        bridge.moveBody(xMeters, yMeters, thetaDegrees, speedLevel);
    }

    @Override
    public void stop() {
        if (!bridge.isReady()) return;
        bridge.emergencyStop();
    }
}
