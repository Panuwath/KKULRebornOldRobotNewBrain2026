import pytest

from sdk_bridge_publisher import MqttSdkBridgePublisher


class FakeMqttClient:
    def __init__(self):
        self.calls = []

    def publish(self, topic: str, payload: str, *, qos: int):
        self.calls.append((topic, payload, qos))


def test_publisher_forwards_to_mqtt():
    fake = FakeMqttClient()
    publisher = MqttSdkBridgePublisher(fake)
    publisher("zenbo/booky-1/cmd/interact", '{"x":0.05}', 1)
    assert fake.calls == [("zenbo/booky-1/cmd/interact", '{"x":0.05}', 1)]


def test_publisher_preserves_qos():
    fake = FakeMqttClient()
    publisher = MqttSdkBridgePublisher(fake)
    publisher("zenbo/booky-1/cmd/stop", "{}", 2)
    assert fake.calls[0][2] == 2
