"""Malformed telemetry must close the preflight gate without server errors."""
import time

import pytest

from field_calibration_check import check


def robot():
    return {
        'robot_slug': 'test', 'version_name': 'test', 'last_seen': time.time(),
        'robot_api_ready': True,
        'safety_guard': {'collision_guard_enabled': True, 'fall_guard_enabled': True,
                         'base_motion_enabled': False},
        'safety_monitor': {'enabled': True, 'active': True, 'required_sensor_coverage': True},
        'motion': {'body_relative': {'supported': True, 'max_distance_m': 0.15,
                                     'max_body_speed': 3, 'auto_stop_ms': 1500}},
    }


@pytest.mark.parametrize('value', [True, False, None, 'fresh', float('nan'), float('inf'), -1, 0])
def test_bad_heartbeat_timestamp_blocks(value):
    data = robot()
    data['last_seen'] = value
    assert 'STALE_HEARTBEAT' in check(data).blockers


@pytest.mark.parametrize('key', ['max_distance_m', 'max_body_speed', 'auto_stop_ms'])
@pytest.mark.parametrize('value', [True, '1500', None, -1, 0, float('nan'), float('inf')])
def test_bad_motion_limit_blocks(key, value):
    data = robot()
    data['motion']['body_relative'][key] = value
    assert not check(data).ready


@pytest.mark.parametrize('key', ['enabled', 'active', 'required_sensor_coverage'])
def test_integer_is_not_safety_attestation(key):
    data = robot()
    data['safety_monitor'][key] = 1
    assert not check(data).ready


def test_ready_and_future_timestamp():
    data = robot()
    assert check(data).ready
    data['last_seen'] = time.time() + 30
    assert not check(data).ready
