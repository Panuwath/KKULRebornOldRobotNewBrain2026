"""Contract tests for always-dance YouTube entertainment commands."""
import json
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from youtube_entertainment import (
    DEFAULT_DANCE_ACTION_IDS,
    EntertainmentRequest,
    YouTubeCommand,
    dispatch_entertainment,
)


URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_default_dance_ids_are_populated():
    command = YouTubeCommand(url=URL)
    assert sorted(command.dance_action_ids) == sorted(DEFAULT_DANCE_ACTION_IDS)
    assert command.loop_dance is True
    assert command.action == "play"


def test_loop_dance_false_is_rejected():
    with pytest.raises(ValidationError, match="DANCE_REQUIRED"):
        YouTubeCommand(url=URL, loop_dance=False)


@pytest.mark.parametrize("action", ["play", "pause", "stop"])
def test_entertainment_endpoint_dispatch(action):
    mqtt_client = Mock()
    record_history = Mock(return_value=42)

    response = dispatch_entertainment(
        "booky-1",
        action,
        EntertainmentRequest(url=URL),
        mqtt_client,
        record_history,
        username="operator",
    )

    topic, encoded = mqtt_client.publish.call_args.args[:2]
    assert topic == "zenbo/booky-1/cmd/youtube"
    assert mqtt_client.publish.call_args.kwargs == {"qos": 1}
    assert json.loads(encoded)["action"] == action
    assert sorted(json.loads(encoded)["dance_action_ids"]) == sorted(DEFAULT_DANCE_ACTION_IDS)
    assert response["history_id"] == 42
    assert record_history.call_args.kwargs == {"user_id": "operator", "display_name": "operator"}
