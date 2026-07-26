from engine.event_bus import EventBus


class _FakeEvent:
    def __init__(self, event_type):
        self.event_type = event_type


def test_publish_routes_to_matching_subscriber_only():
    bus = EventBus()
    matched = []
    other = []
    bus.subscribe("FOO", lambda e: matched.append(e))
    bus.subscribe("BAR", lambda e: other.append(e))

    bus.publish(_FakeEvent("FOO"))

    assert len(matched) == 1
    assert len(other) == 0


def test_wildcard_subscriber_receives_everything():
    bus = EventBus()
    seen = []
    bus.subscribe_all(lambda e: seen.append(e.event_type))

    bus.publish_many([_FakeEvent("FOO"), _FakeEvent("BAR")])

    assert seen == ["FOO", "BAR"]


def test_publish_with_no_subscribers_does_not_raise():
    bus = EventBus()
    bus.publish(_FakeEvent("NOBODY_LISTENING"))
