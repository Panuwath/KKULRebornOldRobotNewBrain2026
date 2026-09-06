package com.hackathon.zenboclient.robot;

/** Minimal motion surface wired to the official ASUS SDK. No private APIs. */
public interface RobotMotionBridge {
    boolean isReady();
    void moveBody(float x, float y, float theta, int speedLevel);
    void emergencyStop();
}
