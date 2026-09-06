package com.hackathon.zenboclient.drive;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public class SdkDriveActuatorTest {
    @Test
    public void passesRelativeMotionToReadyBridge() {
        FakeRobotMotionBridge bridge = new FakeRobotMotionBridge();
        SdkDriveActuator actuator = new SdkDriveActuator(bridge);
        actuator.moveRelative(0.05f, 0f, 0f, 2);
        assertEquals(1, bridge.calls.size());
        assertTrue(bridge.calls.get(0).startsWith("move:2"));
    }

    @Test(expected = IllegalStateException.class)
    public void doesNotCallBridgeWhenNotReady() {
        FakeRobotMotionBridge bridge = new FakeRobotMotionBridge();
        bridge.ready = false;
        SdkDriveActuator actuator = new SdkDriveActuator(bridge);
        actuator.moveRelative(0.05f, 0f, 0f, 2);

    }

    @Test
    public void stopCallsEmergencyStopOnBridge() {
        FakeRobotMotionBridge bridge = new FakeRobotMotionBridge();
        SdkDriveActuator actuator = new SdkDriveActuator(bridge);
        actuator.stop();
        assertEquals("stop", bridge.calls.get(0));
    }

    @Test
    public void invalidLevelsNeverReachSdk() {
        FakeRobotMotionBridge bridge = new FakeRobotMotionBridge();
        for (int level : new int[] {0, 8, -1}) {
            try {
                new SdkDriveActuator(bridge).moveRelative(0.05f, 0f, 0f, level);
                org.junit.Assert.fail("invalid level accepted");
            } catch (IllegalArgumentException expected) { }
        }
        assertTrue(bridge.calls.isEmpty());
    }

    @Test
    public void stopIsAttemptedEvenWhenReadinessIsLost() {
        FakeRobotMotionBridge bridge = new FakeRobotMotionBridge();
        bridge.ready = false;
        new SdkDriveActuator(bridge).stop();
        assertEquals("stop", bridge.calls.get(0));
    }

    @Test(expected = IllegalArgumentException.class)
    public void rejectsNullBridge() {
        new SdkDriveActuator(null);
    }
}
