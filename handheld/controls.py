"""Build a button->keys legend from a .brick config. Pure and PyQt6-free.

key_name(code) is injected so this module never imports PyQt6; the widget
passes lambda c: Qt.Key(c).name.
"""


def controls_legend(config, key_name):
    rows = []
    for name, value in config.get("buttons", {}).items():
        keys = ", ".join(key_name(code) for code in value.get("hot_keys", []))
        rows.append((name, keys))
    return rows
