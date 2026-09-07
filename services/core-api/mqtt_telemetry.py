"""Connection/SUBACK readback for status subscriptions; never publishes commands."""
from threading import Lock
import time


class TelemetryConnection:
    def __init__(self, clock=time.time):
        self._clock = clock
        self._lock = Lock()
        self._mid = None
        self._status = dict(state='NOT_STARTED', connected=False, subscribed=False,
                            connect_count=0, last_event_at_ms=None,
                            live_heartbeat_count=0, retained_heartbeat_count=0,
                            last_live_heartbeat_at_ms=None, last_retained_heartbeat_at_ms=None)

    def snapshot(self):
        with self._lock:
            return dict(self._status)

    def _event(self, state, connected=False, subscribed=False):
        self._status.update(state=state, connected=connected, subscribed=subscribed,
                            last_event_at_ms=int(self._clock() * 1000))

    def bind(self, client):
        client.on_connect = self.on_connect
        client.on_connect_fail = self.on_connect_fail
        client.on_disconnect = self.on_disconnect
        client.on_subscribe = self.on_subscribe

    def starting(self):
        with self._lock:
            self._mid = None
            self._event('CONNECTING')

    def configuration_error(self):
        with self._lock:
            self._mid = None
            self._event('CONFIGURATION_ERROR')

    def on_connect(self, client, userdata, flags, reason_code, properties=None):
        # Paho v2 callback. Every successful CONNACK must subscribe again because
        # the clean broker session does not preserve subscriptions on reconnect.
        with self._lock:
            self._mid = None
            if reason_code != 0:
                self._event('CONNECT_REJECTED')
                return
            self._status['connect_count'] += 1
            self._event('SUBSCRIBING', connected=True)
        try:
            rc, mid = client.subscribe('zenbo/+/status/#', qos=1)
            with self._lock:
                if rc == 0:
                    self._mid = mid
                else:
                    self._event('SUBSCRIBE_FAILED', connected=True)
        except Exception:
            with self._lock:
                self._event('SUBSCRIBE_FAILED', connected=True)

    def on_subscribe(self, client, userdata, mid, reason_codes, properties=None):
        with self._lock:
            if mid != self._mid or not self._status['connected']:
                return
            accepted = bool(reason_codes) and all(getattr(code, 'value', code) in (0, 1, 2) for code in reason_codes)
            self._event('READY' if accepted else 'SUBSCRIBE_REJECTED', connected=True, subscribed=accepted)
            self._mid = None

    def on_connect_fail(self, client, userdata):
        with self._lock:
            self._mid = None
            self._event('CONNECT_FAILED')

    def on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties=None):
        with self._lock:
            self._mid = None
            self._event('DISCONNECTED')

    def heartbeat(self, retained):
        kind = 'retained' if retained else 'live'
        with self._lock:
            self._status[kind + '_heartbeat_count'] += 1
            self._status['last_' + kind + '_heartbeat_at_ms'] = int(self._clock() * 1000)
