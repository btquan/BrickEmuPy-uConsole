from handheld.battery import read_battery, BatteryStatus


def _make_supply(root, name, capacity=None, status=None):
    d = root / name
    d.mkdir()
    if capacity is not None:
        (d / "capacity").write_text(capacity)
    if status is not None:
        (d / "status").write_text(status)
    return d


def test_reads_percent_and_discharging(tmp_path):
    _make_supply(tmp_path, "BAT0", capacity="83\n", status="Discharging\n")
    s = read_battery(str(tmp_path))
    assert s == BatteryStatus(percent=83, charging=False)


def test_charging_and_full_map_to_charging(tmp_path):
    _make_supply(tmp_path, "BAT0", capacity="50", status="Charging")
    assert read_battery(str(tmp_path)).charging is True
    (tmp_path / "BAT0" / "status").write_text("Full")
    assert read_battery(str(tmp_path)).charging is True


def test_skips_supplies_without_capacity(tmp_path):
    _make_supply(tmp_path, "AC", status="Charging")          # no capacity file
    _make_supply(tmp_path, "BAT0", capacity="12", status="Discharging")
    assert read_battery(str(tmp_path)).percent == 12


def test_none_when_no_battery(tmp_path):
    assert read_battery(str(tmp_path)) is None


def test_none_on_missing_root():
    assert read_battery("/nonexistent/path/xyz") is None


def test_none_on_malformed_capacity(tmp_path):
    _make_supply(tmp_path, "BAT0", capacity="not-a-number", status="Full")
    assert read_battery(str(tmp_path)) is None
