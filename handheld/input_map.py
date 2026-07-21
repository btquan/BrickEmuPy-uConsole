"""Load the gamepad profile and resolve roles to game buttons. Pure, no Qt."""
import json
import os

_PROFILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "uconsole.json")

DEFAULT_PROFILE = {
    "buttons": {"0": "BTN_A", "1": "BTN_B", "2": "BTN_X", "3": "BTN_Y",
                "4": "BTN_SELECT", "5": "BTN_START"},
    "axes": {"0": {"negative": "DPAD_LEFT", "positive": "DPAD_RIGHT"},
             "1": {"negative": "DPAD_UP", "positive": "DPAD_DOWN"}},
    "axis_threshold": 16000,
    "roles": {
        "DPAD_LEFT": ["btnLeft"], "DPAD_RIGHT": ["btnRight"],
        "DPAD_DOWN": ["btnDown"], "DPAD_UP": ["btnUp"],
        "BTN_A": ["btnRotate"], "BTN_B": ["btnRotate"],
        "BTN_X": [], "BTN_Y": [],
        "BTN_START": ["btnStart"], "BTN_SELECT": ["btnMute", "btnSelect"],
    },
}


def load_profile(path=_PROFILE_PATH):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return DEFAULT_PROFILE


def resolve_role(role, config, profile):
    override = config.get("input_map")
    if override and role in override:
        return override[role]
    buttons = config.get("buttons", {})
    for candidate in profile.get("roles", {}).get(role, []):
        if candidate in buttons:
            return candidate
    return None


def control_hints(config, profile):
    order = list(config.get("buttons", {}))
    hints = {name: [] for name in order}
    roles = list(profile.get("buttons", {}).values())
    for ax in profile.get("axes", {}).values():
        for r in (ax.get("negative"), ax.get("positive")):
            if r:
                roles.append(r)
    for role in roles:
        button = resolve_role(role, config, profile)
        if button in hints:
            hints[button].append(role)
    return [(name, hints[name]) for name in order]
