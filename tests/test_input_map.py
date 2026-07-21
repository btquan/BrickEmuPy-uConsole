from handheld.input_map import (load_profile, resolve_role, control_hints,
                                DEFAULT_PROFILE)

E23 = {"buttons": {"btnStart": {}, "btnOnOff": {}, "btnMute": {}, "btnLeft": {},
                   "btnDown": {}, "btnRight": {}, "btnRotate": {}}}


def test_resolve_uses_first_existing_candidate():
    assert resolve_role("BTN_START", E23, DEFAULT_PROFILE) == "btnStart"
    assert resolve_role("BTN_SELECT", E23, DEFAULT_PROFILE) == "btnMute"
    assert resolve_role("BTN_A", E23, DEFAULT_PROFILE) == "btnRotate"
    assert resolve_role("DPAD_LEFT", E23, DEFAULT_PROFILE) == "btnLeft"


def test_up_is_unmapped_on_brick():
    assert resolve_role("DPAD_UP", E23, DEFAULT_PROFILE) is None   # no btnUp


def test_no_candidate_returns_none():
    assert resolve_role("BTN_X", E23, DEFAULT_PROFILE) is None


def test_per_game_override_wins():
    cfg = {"buttons": {"btnRotate": {}, "btnOnOff": {}},
           "input_map": {"BTN_B": "btnOnOff"}}
    assert resolve_role("BTN_B", cfg, DEFAULT_PROFILE) == "btnOnOff"


def test_load_profile_missing_returns_default():
    assert load_profile("/nonexistent/uconsole.json") == DEFAULT_PROFILE


def test_shipped_uconsole_json_matches_default():
    assert load_profile() == DEFAULT_PROFILE


def test_control_hints_group_roles_per_button():
    hints = dict(control_hints(E23, DEFAULT_PROFILE))
    assert set(hints["btnRotate"]) == {"BTN_A", "BTN_B"}
    assert hints["btnStart"] == ["BTN_START"]
    assert hints["btnMute"] == ["BTN_SELECT"]
    assert hints["btnLeft"] == ["DPAD_LEFT"]
    assert hints["btnOnOff"] == []           # nothing maps here
