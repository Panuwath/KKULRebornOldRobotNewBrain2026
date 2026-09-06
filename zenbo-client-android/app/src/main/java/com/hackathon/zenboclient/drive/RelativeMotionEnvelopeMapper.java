package com.hackathon.zenboclient.drive;

import com.hackathon.zenboclient.model.InteractCommand;

public final class RelativeMotionEnvelopeMapper {
    private RelativeMotionEnvelopeMapper() {}

    public static SpeedLevelDriveController.Command from(InteractCommand envelope) {
        if (envelope == null || envelope.motion == null || envelope.policy == null
                || !"RELATIVE_BODY".equals(envelope.motion.controlMode)
                || envelope.sourceSeq == null || envelope.expiresAtMs == null) {
            throw new IllegalArgumentException("invalid relative motion envelope");
        }
        return new SpeedLevelDriveController.Command(
                envelope.commandId,
                envelope.sourceSessionId,
                envelope.sourceSeq,
                envelope.expiresAtMs,
                envelope.motion.x,
                envelope.motion.y,
                envelope.motion.theta,
                envelope.motion.speed,
                envelope.policy.maxBodySpeedLevel,
                envelope.policy.maxDistanceM,
                envelope.policy.hardStopAfterMs
        );
    }
}
