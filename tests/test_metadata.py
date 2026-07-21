from handheld.metadata import game_name, game_group


def test_name_prefers_explicit_field():
    assert game_name({"name": "Tetris Jr."}, "/x/GA888.brick") == "Tetris Jr."


def test_name_falls_back_to_prettified_stem():
    assert game_name({}, "/x/E23PlusMarkII96in1.brick") == "E23PlusMarkII96in1"
    assert game_name({}, "/x/E33_2in1.brick") == "E33 2in1"


def test_group_prefers_explicit_category():
    assert game_group({"category": "Puzzle", "core": "HT943"}) == "Puzzle"


def test_group_falls_back_to_core_map():
    assert game_group({"core": "HT943"}) == "Brick"
    assert game_group({"core": "E0C6200"}) == "Virtual Pet"


def test_group_unknown_core_is_other():
    assert game_group({"core": "T6770S"}) == "Other"
    assert game_group({}) == "Other"
