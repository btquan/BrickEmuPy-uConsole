"""Pure decoding of Linux joystick (/dev/input/js0) events. No Qt, no I/O."""
import struct

# struct js_event { __u32 time; __s16 value; __u8 type; __u8 number; }
_FMT = "IhBB"
EVENT_SIZE = 8
_JS_EVENT_BUTTON = 0x01
_JS_EVENT_AXIS = 0x02
_JS_EVENT_INIT = 0x80


def parse_js_event(data):
    if len(data) != EVENT_SIZE:
        raise ValueError("js_event must be %d bytes, got %d"
                         % (EVENT_SIZE, len(data)))
    _time, value, typ, number = struct.unpack(_FMT, data)
    if typ & _JS_EVENT_INIT:
        return ("init", number, value)
    typ &= 0x7F
    if typ == _JS_EVENT_BUTTON:
        return ("button", number, value)
    if typ == _JS_EVENT_AXIS:
        return ("axis", number, value)
    return ("unknown", number, value)


def button_role(number, profile):
    return profile.get("buttons", {}).get(str(number))


def axis_roles(number, profile):
    entry = profile.get("axes", {}).get(str(number), {})
    return (entry.get("negative"), entry.get("positive"))
