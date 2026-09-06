from __future__ import annotations

from typing import Any, Protocol


class SdkPublisher(Protocol):
    """Boundary for dispatching an envelope to a robot SDK bridge."""

    def __call__(self, topic: str, payload: str, qos: int) -> Any: ...


class MqttSdkBridgePublisher:
    """MQTT-backed SDK bridge publisher for production dispatch.

    Keeps broker calls behind an injectable boundary so fake publishers can be
    swapped in for unit and contract tests.
    """

    def __init__(self, mqtt_client: Any) -> None:
        self.mqtt_client = mqtt_client

    def __call__(self, topic: str, payload: str, qos: int) -> Any:
        return self.mqtt_client.publish(topic, payload, qos=qos)
