from handheld.launcher_selection import (LauncherSelection,
                                         LEFT, RIGHT, UP, DOWN)

# groups: (name, [items]); items are plain strings here for simplicity
GROUPS = [
    ("Brick", ["a", "b", "c"]),
    ("Pet", ["p", "q"]),
    ("Other", ["x"]),
]


def test_starts_top_left():
    s = LauncherSelection(GROUPS)
    assert s.position() == (0, 0)
    assert s.selected() == "a"


def test_right_and_left_clamp():
    s = LauncherSelection(GROUPS)
    s.move(RIGHT); s.move(RIGHT); s.move(RIGHT)     # clamp at last (index 2)
    assert s.position() == (0, 2)
    s.move(LEFT); s.move(LEFT); s.move(LEFT)         # clamp at 0
    assert s.position() == (0, 0)


def test_down_changes_group_and_clamps_column():
    s = LauncherSelection(GROUPS)
    s.move(RIGHT); s.move(RIGHT)                      # (0, 2)
    s.move(DOWN)                                      # Pet has 2 -> clamp to 1
    assert s.position() == (1, 1)
    assert s.selected() == "q"
    s.move(DOWN)                                      # Other has 1 -> clamp to 0
    assert s.position() == (2, 0)


def test_up_clamps_at_top():
    s = LauncherSelection(GROUPS)
    s.move(UP)
    assert s.position() == (0, 0)


def test_empty_groups_safe():
    s = LauncherSelection([])
    assert s.selected() is None
    s.move(RIGHT)     # no crash
    assert s.selected() is None
