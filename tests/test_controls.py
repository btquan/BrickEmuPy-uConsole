from handheld.controls import controls_legend


def test_builds_rows_with_injected_key_name():
    config = {"buttons": {
        "btnLeft": {"hot_keys": [65, 16777234]},
        "btnRotate": {"hot_keys": [32]},
    }}
    rows = controls_legend(config, lambda c: f"K{c}")
    assert rows == [
        ("btnLeft", "K65, K16777234"),
        ("btnRotate", "K32"),
    ]


def test_handles_missing_buttons_and_hotkeys():
    assert controls_legend({}, lambda c: str(c)) == []
    rows = controls_legend({"buttons": {"btnX": {}}}, lambda c: str(c))
    assert rows == [("btnX", "")]
