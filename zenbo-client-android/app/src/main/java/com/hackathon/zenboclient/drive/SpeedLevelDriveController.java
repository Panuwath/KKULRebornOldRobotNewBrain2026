package com.hackathon.zenboclient.drive;

import java.util.HashMap;
import java.util.Iterator;
import java.util.LinkedHashSet;
import java.util.Map;
import java.util.Set;

public final class SpeedLevelDriveController {
    public interface Clock {
        long nowMs();
    }

    public interface DeadlineScheduler {
        void schedule(Runnable task, long delayMs);
    }

    public interface StopListener {
        void onStop(Command command, String reason);
    }

    private StopListener stopListener;
    public synchronized void setStopListener(StopListener listener) { stopListener = listener; }

    public enum State {
        ACTUATOR_ACCEPTED,
        REJECTED,
        STOPPED
    }

    public enum RejectReason {
        COMMAND_EXPIRED,
        DUPLICATE_COMMAND,
        OUT_OF_ORDER,
        SPEED_EXCEEDS_POLICY,
        DISTANCE_EXCEEDS_POLICY,
        INVALID_COMMAND,
        MOTION_BUSY,
        ACTUATOR_ERROR
    }

    public static final class Command {
        public final String commandId;
        public final String sourceSessionId;
        public final long sourceSeq;
        public final long expiresAtMs;
        public final float xMeters;
        public final float yMeters;
        public final float thetaDegrees;
        public final int requestedSpeedLevel;
        public final int policyMaxSpeedLevel;
        public final float policyMaxDistanceMeters;
        public final long hardStopAfterMs;

        public Command(String commandId, String sourceSessionId, long sourceSeq, long expiresAtMs,
                       float xMeters, float yMeters, float thetaDegrees, int requestedSpeedLevel,
                       int policyMaxSpeedLevel, float policyMaxDistanceMeters, long hardStopAfterMs) {
            this.commandId = commandId;
            this.sourceSessionId = sourceSessionId;
            this.sourceSeq = sourceSeq;
            this.expiresAtMs = expiresAtMs;
            this.xMeters = xMeters;
            this.yMeters = yMeters;
            this.thetaDegrees = thetaDegrees;
            this.requestedSpeedLevel = requestedSpeedLevel;
            this.policyMaxSpeedLevel = policyMaxSpeedLevel;
            this.policyMaxDistanceMeters = policyMaxDistanceMeters;
            this.hardStopAfterMs = hardStopAfterMs;
        }
    }

    public static final class Acknowledgement {
        public final String commandId;
        public final State state;
        public final int requestedSpeedLevel;
        public final int policyMaxSpeedLevel;
        public final Integer effectiveSpeedLevel;
        public final RejectReason rejectReason;

        private Acknowledgement(String commandId, State state, int requestedSpeedLevel,
                                int policyMaxSpeedLevel, Integer effectiveSpeedLevel,
                                RejectReason rejectReason) {
            this.commandId = commandId;
            this.state = state;
            this.requestedSpeedLevel = requestedSpeedLevel;
            this.policyMaxSpeedLevel = policyMaxSpeedLevel;
            this.effectiveSpeedLevel = effectiveSpeedLevel;
            this.rejectReason = rejectReason;
        }
    }

    private static final int DEDUPE_LIMIT = 256;
    private final DriveActuator actuator;
    private final Clock clock;
    private final DeadlineScheduler scheduler;
    private final Set<String> commandIds = new LinkedHashSet<>();
    private final Map<String, Long> lastSequenceBySession = new HashMap<>();
    private long generation;
    private Command active;

    public SpeedLevelDriveController(DriveActuator actuator, Clock clock, DeadlineScheduler scheduler) {
        if (actuator == null || clock == null || scheduler == null) {
            throw new IllegalArgumentException("controller dependencies are required");
        }
        this.actuator = actuator;
        this.clock = clock;
        this.scheduler = scheduler;
    }

    public synchronized Acknowledgement submit(Command command) {
        RejectReason rejection = validate(command);
        if (rejection != null) {
            return rejected(command, rejection);
        }
        if (active != null) {
            remember(command); // A QoS retry must not start a previously rejected step later.
            return rejected(command, RejectReason.MOTION_BUSY);
        }
        remember(command);
        active = command;
        final long deadlineGeneration = ++generation;
        try {
            actuator.moveRelative(command.xMeters, command.yMeters, command.thetaDegrees,
                    command.requestedSpeedLevel);
        } catch (RuntimeException error) {
            active = null;
            generation++;
            actuator.stop();
            return rejected(command, RejectReason.ACTUATOR_ERROR);
        }
        long delayMs = Math.min(command.hardStopAfterMs, command.expiresAtMs - clock.nowMs());
        try {
            scheduler.schedule(new Runnable() {
                @Override
                public void run() {
                    stopAtDeadline(deadlineGeneration);
                }
            }, delayMs);
        } catch (RuntimeException error) {
            stopWithReason("DEADLINE_SCHEDULER_ERROR");
            return rejected(command, RejectReason.ACTUATOR_ERROR);
        }
        return new Acknowledgement(command.commandId, State.ACTUATOR_ACCEPTED,
                command.requestedSpeedLevel, command.policyMaxSpeedLevel,
                command.requestedSpeedLevel, null);
    }

    public synchronized Acknowledgement stop(String commandId) {
        stopWithReason("EXPLICIT_STOP");
        return new Acknowledgement(commandId, State.STOPPED, 0, 0, null, null);
    }

    public synchronized void cancel() { cancel("CANCELLED"); }

    public synchronized void cancel(String reason) { stopWithReason(reason); }

    private void stopWithReason(String reason) {
        Command previous = active;
        generation++;
        active = null;
        try { actuator.stop(); }
        finally {
            if (previous != null && stopListener != null) stopListener.onStop(previous, reason);
        }
    }

    private RejectReason validate(Command command) {
        if (command == null || blank(command.commandId) || blank(command.sourceSessionId)
                || command.sourceSeq < 0 || command.hardStopAfterMs <= 0
                || !Float.isFinite(command.xMeters) || !Float.isFinite(command.yMeters)
                || !Float.isFinite(command.thetaDegrees) || Math.abs(command.thetaDegrees) > 360f
                || command.requestedSpeedLevel < 1 || command.requestedSpeedLevel > 7
                || command.policyMaxSpeedLevel < 1 || command.policyMaxSpeedLevel > 7
                || !Float.isFinite(command.policyMaxDistanceMeters)
                || command.policyMaxDistanceMeters <= 0) {
            return RejectReason.INVALID_COMMAND;
        }
        if (clock.nowMs() >= command.expiresAtMs) return RejectReason.COMMAND_EXPIRED;
        if (commandIds.contains(command.commandId)) return RejectReason.DUPLICATE_COMMAND;
        Long lastSequence = lastSequenceBySession.get(command.sourceSessionId);
        if (lastSequence != null && command.sourceSeq <= lastSequence) return RejectReason.OUT_OF_ORDER;
        if (command.requestedSpeedLevel > command.policyMaxSpeedLevel) {
            return RejectReason.SPEED_EXCEEDS_POLICY;
        }
        if (Math.hypot(command.xMeters, command.yMeters) > command.policyMaxDistanceMeters) {
            return RejectReason.DISTANCE_EXCEEDS_POLICY;
        }
        return null;
    }

    private void remember(Command command) {
        commandIds.add(command.commandId);
        if (commandIds.size() > DEDUPE_LIMIT) {
            Iterator<String> iterator = commandIds.iterator();
            iterator.next();
            iterator.remove();
        }
        lastSequenceBySession.put(command.sourceSessionId, command.sourceSeq);
    }

    public synchronized boolean isActive() { return active != null; }

    private synchronized void stopAtDeadline(long deadlineGeneration) {
        if (active == null || generation != deadlineGeneration) return;
        stopWithReason("HARD_DEADLINE");
    }

    private Acknowledgement rejected(Command command, RejectReason reason) {
        return new Acknowledgement(command == null ? null : command.commandId, State.REJECTED,
                command == null ? 0 : command.requestedSpeedLevel,
                command == null ? 0 : command.policyMaxSpeedLevel, null, reason);
    }

    private boolean blank(String value) {
        return value == null || value.trim().isEmpty();
    }
}
