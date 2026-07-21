import json
import os

from handheld.game_catalog import scan_catalog, group_catalog, GameEntry


def _game(assets, stem, core, with_rom=True, name=None, category=None):
    cfg = {"core": core, "face_path": "./assets/%s.svg" % stem,
           "mask_options": {"rom_path": "./assets/%s.bin" % stem}}
    if name:
        cfg["name"] = name
    if category:
        cfg["category"] = category
    (assets / (stem + ".brick")).write_text(json.dumps(cfg))
    (assets / (stem + ".svg")).write_text("<svg/>")
    if with_rom:
        (assets / (stem + ".bin")).write_bytes(b"\x00")


def test_scan_keeps_only_rom_present(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    _game(assets, "E23", "HT943", with_rom=True)
    _game(assets, "Tama", "E0C6200", with_rom=False)   # no .bin -> skipped
    entries = scan_catalog(str(assets))
    stems = sorted(os.path.basename(e.brick_path) for e in entries)
    assert stems == ["E23.brick"]
    e = entries[0]
    assert e.name == "E23" and e.group == "Brick"
    assert e.svg_path.endswith("E23.svg")


def test_scan_skips_malformed_brick(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "bad.brick").write_text("{ not json")
    _game(assets, "E88", "HT943")
    entries = scan_catalog(str(assets))
    assert [e.name for e in entries] == ["E88"]


def test_group_order_and_sort(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    _game(assets, "zzz", "HT943", name="Zzz Brick")
    _game(assets, "aaa", "HT943", name="Aaa Brick")
    _game(assets, "pet", "E0C6200", name="Pet One")
    _game(assets, "misc", "T6770S", name="Misc One")
    grouped = group_catalog(scan_catalog(str(assets)))
    names = [g[0] for g in grouped]
    assert names == ["Brick", "Virtual Pet", "Other"]
    brick_names = [e.name for e in dict(grouped)["Brick"]]
    assert brick_names == ["Aaa Brick", "Zzz Brick"]   # sorted by name
