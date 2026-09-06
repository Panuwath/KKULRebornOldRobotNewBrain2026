package com.hackathon.zenboclient.drive;

import com.hackathon.zenboclient.robot.RobotMotionBridge;
import java.util.ArrayList;
import java.util.List;

public final class FakeRobotMotionBridge implements RobotMotionBridge {
    public boolean ready = true;
    public final List<String> calls = new ArrayList<>();

    @Override
    public boolean isReady() {
        return ready;
    }

    @Override
    public void moveBody(float x, float y, float theta, int speedLevel) {
        calls.add("move:" + speedLevel + ":" + x + ":" + y + ":" + theta);
    }

    @Override
    public void emergencyStop() {
        calls.add("stop");
    }
}
