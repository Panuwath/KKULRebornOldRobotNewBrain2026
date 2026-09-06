package com.hackathon.zenboclient.drive;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNull;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import com.hackathon.zenboclient.model.InteractCommand;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.List;
import java.util.Scanner;
import org.junit.Test;

public class SpeedLevelDriveControllerTest {
    @Test
    public void parsesCanonicalRelativeMotionEnvelope() {
        InputStream stream = getClass().getClassLoader().getResourceAsStream("relative_motion_golden.json");
        Scanner scanner = new Scanner(stream, "UTF-8").useDelimiter("\\A");
        JsonObject fixture = new Gson().fromJson(scanner.next(), JsonObject.class).getAsJsonObject("valid");
        InteractCommand command = new Gson().fromJson(fixture.get("expected_envelope"), InteractCommand.class);
        Fixture controllerFixture = new Fixture();
        SpeedLevelDriveController.Acknowledgement acknowledgement = controllerFixture.controller.submit(
                RelativeMotionEnvelopeMapper.from(command));

        assertEquals("RELATIVE_BODY", command.motion.controlMode);
        assertEquals(3, command.motion.speed);
        assertEquals(4, command.policy.maxBodySpeedLevel);
        assertEquals(Long.valueOf(12), command.sourceSeq);
        assertEquals(SpeedLevelDriveController.State.ACTUATOR_ACCEPTED, acknowledgement.state);
        assertEquals("move:3", controllerFixture.actuator.events.get(0));
    }

    @Test
    public void sendsEverySpeedLevelToFakeActuator() {
        for (int level = 1; level <= 7; level++) {
            Fixture fixture = new Fixture();
            SpeedLevelDriveController.Acknowledgement ack = fixture.controller.submit(
                    fixture.command("command-" + level, level, level, 7, 1500));

            assertEquals(SpeedLevelDriveController.State.ACTUATOR_ACCEPTED, ack.state);
            assertEquals(Integer.valueOf(level), ack.effectiveSpeedLevel);
            assertEquals("move:" + level, fixture.actuator.events.get(0));
        }
    }

    @Test
    public void duplicateAndOutOfOrderCommandsNeverReachActuator() {
        Fixture fixture = new Fixture();
        SpeedLevelDriveController.Command accepted = fixture.command("same", 2, 2, 7, 1500);
        fixture.controller.submit(accepted);

        SpeedLevelDriveController.Acknowledgement duplicate = fixture.controller.submit(accepted);
        SpeedLevelDriveController.Acknowledgement old = fixture.controller.submit(
                fixture.command("old", 1, 2, 7, 1500));

        assertEquals(SpeedLevelDriveController.RejectReason.DUPLICATE_COMMAND, duplicate.rejectReason);
        assertEquals(SpeedLevelDriveController.RejectReason.OUT_OF_ORDER, old.rejectReason);
        assertEquals(1, fixture.actuator.moveCount);
    }

    @Test
    public void staleAndOverCapCommandsHaveNoEffectiveSpeedOrActuatorCall() {
        Fixture fixture = new Fixture();
        fixture.clock.now = 2000;
        SpeedLevelDriveController.Acknowledgement stale = fixture.controller.submit(
                fixture.command("stale", 1, 3, 7, 1500));
        fixture.clock.now = 1000;
        SpeedLevelDriveController.Acknowledgement overCap = fixture.controller.submit(
                fixture.command("over-cap", 2, 5, 4, 1500));

        assertEquals(SpeedLevelDriveController.RejectReason.COMMAND_EXPIRED, stale.rejectReason);
        assertEquals(SpeedLevelDriveController.RejectReason.SPEED_EXCEEDS_POLICY, overCap.rejectReason);
        assertNull(stale.effectiveSpeedLevel);
        assertNull(overCap.effectiveSpeedLevel);
        assertEquals(0, fixture.actuator.moveCount);
    }

    @Test
    public void overDistanceCommandNeverReachesActuator() {
        Fixture fixture = new Fixture();
        SpeedLevelDriveController.Command command = new SpeedLevelDriveController.Command(
                "over-distance", "session", 1, 2000, 0.16f, 0f, 0f, 2, 4, 0.15f, 1500);

        SpeedLevelDriveController.Acknowledgement acknowledgement = fixture.controller.submit(command);

        assertEquals(SpeedLevelDriveController.RejectReason.DISTANCE_EXCEEDS_POLICY,
                acknowledgement.rejectReason);
        assertNull(acknowledgement.effectiveSpeedLevel);
        assertEquals(0, fixture.actuator.moveCount);
    }

    @Test
    public void directionOrSpeedChangeStopsBeforeLatestMove() {
        Fixture fixture = new Fixture();
        fixture.controller.submit(fixture.command("first", 1, 2, 7, 1500));
        fixture.controller.submit(fixture.command("second", 2, 3, 7, 1500));

        assertEquals("move:2", fixture.actuator.events.get(0));
        assertEquals("stop", fixture.actuator.events.get(1));
        assertEquals("move:3", fixture.actuator.events.get(2));
    }

    @Test
    public void stopPreemptsAndInvalidatesScheduledDeadline() {
        Fixture fixture = new Fixture();
        fixture.controller.submit(fixture.command("move", 1, 2, 7, 1500));
        SpeedLevelDriveController.Acknowledgement stopped = fixture.controller.stop("stop-command");
        fixture.scheduler.run(0);

        assertEquals(SpeedLevelDriveController.State.STOPPED, stopped.state);
        assertEquals(1, fixture.actuator.stopCount);
    }

    @Test
    public void deadlineUsesSmallerOfExpiryAndHardStopAndCannotBeExtended() {
        Fixture fixture = new Fixture();
        fixture.controller.submit(fixture.command("expiry-bound", 1, 2, 7, 5000));

        assertEquals(1000, fixture.scheduler.delays.get(0).longValue());
        fixture.scheduler.run(0);
        assertEquals(1, fixture.actuator.stopCount);
    }

    @Test
    public void hardStopDeadlineStopsExactlyOnce() {
        Fixture fixture = new Fixture();
        fixture.controller.submit(fixture.command("hard-stop", 1, 2, 7, 250));

        assertEquals(250, fixture.scheduler.delays.get(0).longValue());
        fixture.scheduler.run(0);
        fixture.scheduler.run(0);
        assertEquals(1, fixture.actuator.stopCount);
    }

    private static final class Fixture {
        final FakeClock clock = new FakeClock();
        final FakeScheduler scheduler = new FakeScheduler();
        final FakeActuator actuator = new FakeActuator();
        final SpeedLevelDriveController controller =
                new SpeedLevelDriveController(actuator, clock, scheduler);

        SpeedLevelDriveController.Command command(String id, long sequence, int speed,
                                                   int cap, long hardStopMs) {
            return new SpeedLevelDriveController.Command(
                    id, "session", sequence, 2000, 0.1f, 0f, 0f, speed, cap, 0.15f, hardStopMs);
        }
    }

    private static final class FakeClock implements SpeedLevelDriveController.Clock {
        long now = 1000;

        @Override
        public long nowMs() {
            return now;
        }
    }

    private static final class FakeScheduler implements SpeedLevelDriveController.DeadlineScheduler {
        final List<Runnable> tasks = new ArrayList<>();
        final List<Long> delays = new ArrayList<>();

        @Override
        public void schedule(Runnable task, long delayMs) {
            tasks.add(task);
            delays.add(delayMs);
        }

        void run(int index) {
            tasks.get(index).run();
        }
    }

    private static final class FakeActuator implements DriveActuator {
        final List<String> events = new ArrayList<>();
        int moveCount;
        int stopCount;

        @Override
        public void moveRelative(float xMeters, float yMeters, float thetaDegrees, int speedLevel) {
            moveCount++;
            events.add("move:" + speedLevel);
        }

        @Override
        public void stop() {
            stopCount++;
            events.add("stop");
        }
    }
}
