import struct

import pytest

from handheld.js_events import (parse_js_event, button_role, axis_roles,
                                EVENT_SIZE)


def _ev(value, typ, number):
    return struct.pack("IhBB", 0, value, typ, number)


def test_parse_button_press_and_release():
    assert parse_js_event(_ev(1, 0x01, 5)) == ("button", 5, 1)
    assert parse_js_event(_ev(0, 0x01, 0)) == ("button", 0, 0)


def test_parse_axis():
    assert parse_js_event(_ev(-32767, 0x02, 1)) == ("axis", 1, -32767)


def test_init_flag_recognised():
    assert parse_js_event(_ev(1, 0x81, 5)) == ("init", 5, 1)


def test_wrong_size_raises():
    with pytest.raises(ValueError):
        parse_js_event(b"\x00\x00")


def test_role_lookup():
    profile = {"buttons": {"5": "BTN_START"},
               "axes": {"0": {"negative": "DPAD_LEFT", "positive": "DPAD_RIGHT"}}}
    assert button_role(5, profile) == "BTN_START"
    assert button_role(9, profile) is None
    assert axis_roles(0, profile) == ("DPAD_LEFT", "DPAD_RIGHT")
    assert axis_roles(7, profile) == (None, None)
    assert EVENT_SIZE == 8
