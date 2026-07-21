from handheld.js_events import AxisTracker


def test_press_then_release():
    t = AxisTracker(16000)
    assert t.feed(0, -32767, "DPAD_LEFT", "DPAD_RIGHT") == [("DPAD_LEFT", True)]
    assert t.feed(0, 0, "DPAD_LEFT", "DPAD_RIGHT") == [("DPAD_LEFT", False)]


def test_direction_flip_without_center():
    t = AxisTracker(16000)
    t.feed(0, -32767, "DPAD_LEFT", "DPAD_RIGHT")
    assert t.feed(0, 32767, "DPAD_LEFT", "DPAD_RIGHT") == [
        ("DPAD_LEFT", False), ("DPAD_RIGHT", True)]


def test_below_threshold_is_noop():
    t = AxisTracker(16000)
    assert t.feed(0, 5000, "DPAD_LEFT", "DPAD_RIGHT") == []


def test_repeat_same_direction_is_noop():
    t = AxisTracker(16000)
    t.feed(0, -32767, "DPAD_LEFT", "DPAD_RIGHT")
    assert t.feed(0, -30000, "DPAD_LEFT", "DPAD_RIGHT") == []


def test_none_roles_are_safe():
    t = AxisTracker(16000)
    assert t.feed(2, -32767, None, None) == []
    assert t.feed(2, 0, None, None) == []
