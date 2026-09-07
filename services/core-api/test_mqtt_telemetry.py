from types import SimpleNamespace
from mqtt_telemetry import TelemetryConnection


class Client:
    def __init__(self):
        self.calls = []
        self.rc = 0

    def subscribe(self, topic, qos):
        self.calls.append((topic, qos))
        return self.rc, len(self.calls)


def test_connect_requires_suback_and_resubscribes_after_reconnect():
    tracker = TelemetryConnection(clock=lambda: 100)
    client = Client(); tracker.bind(client); tracker.starting()
    assert tracker.snapshot()['state'] == 'CONNECTING'
    client.on_connect(client, None, None, 0, None)
    assert client.calls == [('zenbo/+/status/#', 1)]
    assert tracker.snapshot()['connected'] is True
    assert tracker.snapshot()['subscribed'] is False
    client.on_subscribe(client, None, 1, [SimpleNamespace(value=1)], None)
    assert tracker.snapshot()['state'] == 'READY'
    client.on_disconnect(client, None, None, 7, None)
    assert tracker.snapshot()['connected'] is False
    assert tracker.snapshot()['subscribed'] is False
    client.on_connect(client, None, None, 0, None)
    assert len(client.calls) == 2
    client.on_subscribe(client, None, 1, [1], None)
    assert tracker.snapshot()['subscribed'] is False  # old SUBACK
    client.on_subscribe(client, None, 2, [1], None)
    assert tracker.snapshot()['state'] == 'READY'
    assert tracker.snapshot()['connect_count'] == 2


def test_failed_connection_and_rejected_subscriptions_are_not_ready():
    tracker = TelemetryConnection(); client = Client()
    tracker.on_connect(client, None, None, 5)
    assert not client.calls
    assert tracker.snapshot()['state'] == 'CONNECT_REJECTED'
    tracker.on_connect_fail(client, None)
    assert tracker.snapshot()['state'] == 'CONNECT_FAILED'
    tracker.on_connect(client, None, None, 0)
    tracker.on_subscribe(client, None, 1, [SimpleNamespace(value=128)])
    assert tracker.snapshot()['state'] == 'SUBSCRIBE_REJECTED'
    assert tracker.snapshot()['subscribed'] is False
    client.rc = 4
    tracker.on_connect(client, None, None, 0)
    assert tracker.snapshot()['state'] == 'SUBSCRIBE_FAILED'


def test_retained_heartbeat_never_counts_as_live_and_snapshot_is_detached():
    tracker = TelemetryConnection(clock=lambda: 100)
    tracker.heartbeat(True)
    result = tracker.snapshot()
    assert result['retained_heartbeat_count'] == 1
    assert result['live_heartbeat_count'] == 0
    assert result['last_live_heartbeat_at_ms'] is None
    tracker.heartbeat(False)
    assert tracker.snapshot()['last_live_heartbeat_at_ms'] == 100000
    result['connected'] = True
    assert tracker.snapshot()['connected'] is False


def test_delayed_suback_after_disconnect_does_not_restore_ready():
    tracker = TelemetryConnection(); client = Client()
    tracker.on_connect(client, None, None, 0)
    tracker.on_disconnect(client, None, None, 0)
    tracker.on_subscribe(client, None, 1, [1])
    assert tracker.snapshot()['state'] == 'DISCONNECTED'


def test_setup_error_does_not_claim_connection():
    tracker = TelemetryConnection(); tracker.configuration_error()
    assert tracker.snapshot()['state'] == 'CONFIGURATION_ERROR'
    assert tracker.snapshot()['connected'] is False
