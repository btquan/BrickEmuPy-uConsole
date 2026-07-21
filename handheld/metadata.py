"""Derive a display name and group for a .brick game. Pure and PyQt6-free.

The .brick format has no name/category fields; these are best-effort. Phase 5
will formalize categories for the launcher.
"""
import os

_CORE_GROUP = {
    "HT943": "Brick",
    "EM73000": "Brick",
    "SPL02": "Brick",
    "SPL03": "Brick",
    "SPL81408": "Brick",
    "E0C6200": "Virtual Pet",
    "SPLB32": "Virtual Pet",
    "SPLB20": "Virtual Pet",
    "KS57C21308": "Virtual Pet",
}


def game_name(config, brick_path):
    name = config.get("name")
    if name:
        return name
    stem = os.path.splitext(os.path.basename(brick_path))[0]
    return stem.replace("_", " ")


def game_group(config):
    category = config.get("category")
    if category:
        return category
    return _CORE_GROUP.get(config.get("core"), "Other")
