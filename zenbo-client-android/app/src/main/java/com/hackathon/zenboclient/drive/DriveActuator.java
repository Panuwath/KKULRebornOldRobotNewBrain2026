package com.hackathon.zenboclient.drive;

public interface DriveActuator {
    void moveRelative(float xMeters, float yMeters, float thetaDegrees, int speedLevel);
    void stop();
}
