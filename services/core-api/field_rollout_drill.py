"""Offline rehearsal entry point. Uses synthetic permits in memory only."""
import json
import os


def main():
    # Set before imports; never inherit production DB selection or paths.
    os.environ['DB_CONNECTION'] = 'sqlite'
    os.environ['COMMAND_HISTORY_DB'] = ':memory:'
    import db
    import field_permit
    import field_rollout

    db.init()
    actor = {'sub': 'synthetic-operator', 'role': 'operator'}
    robot = 'synthetic-robot'
    permit = field_permit.issue(robot, actor['sub'], level_max=3,
                                attestation={'synthetic': True})
    session = field_rollout.start(robot, permit['permit_id'], actor)
    outcomes = []
    for level in range(1, 4):
        session = field_rollout.transition(session['session_id'], robot, actor, session['revision'])
        gate = field_rollout.authorize_preview(session['session_id'], robot, permit['permit_id'], actor, level)
        outcomes.append(gate['state'])
    session = field_rollout.transition(session['session_id'], robot, actor, session['revision'], rollback=True)
    try:
        field_rollout.authorize_preview(session['session_id'], robot, permit['permit_id'], actor, 1)
    except field_rollout.RolloutError as error:
        assert str(error) == 'SESSION_TERMINAL'
    else:
        raise AssertionError('Rolled-back session allowed a preview')
    print(json.dumps({'result': 'PASS', 'evidence': 'SYNTHETIC_SESSION_GATES_ONLY',
                      'stages': outcomes, 'rollback_state': session['state'],
                      'preview_after_rollback': 'BLOCKED', 'database': ':memory:',
                      'mqtt_publish_attempted': False, 'physical_authorized': False}, indent=2))


if __name__ == '__main__':
    main()
