"""Scan the assets directory for playable games. Pure, PyQt6-free."""
import os
import json
from dataclasses import dataclass

from handheld.metadata import game_name, game_group

_GROUP_ORDER = ["Brick", "Virtual Pet", "Other"]


@dataclass
class GameEntry:
    name: str
    group: str
    brick_path: str
    svg_path: str


def _asset(assets_dir, ref):
    # A .brick path like "./assets/Foo.bin" -> that file inside assets_dir.
    return os.path.join(assets_dir, os.path.basename(ref)) if ref else ""


def _rom_present(config, assets_dir):
    rp = config.get("mask_options", {}).get("rom_path")
    return bool(rp) and os.path.exists(_asset(assets_dir, rp))


def scan_catalog(assets_dir):
    entries = []
    for fname in sorted(os.listdir(assets_dir)):
        if not fname.endswith(".brick"):
            continue
        brick_path = os.path.join(assets_dir, fname)
        try:
            with open(brick_path) as f:
                config = json.load(f)
        except (OSError, ValueError):
            continue
        if not _rom_present(config, assets_dir):
            continue
        entries.append(GameEntry(
            name=game_name(config, brick_path),
            group=game_group(config),
            brick_path=brick_path,
            svg_path=_asset(assets_dir, config.get("face_path", "")),
        ))
    return entries


def group_catalog(entries):
    buckets = {}
    for e in entries:
        buckets.setdefault(e.group, []).append(e)
    result = []
    seen = set()
    for name in _GROUP_ORDER:
        if buckets.get(name):
            result.append((name, sorted(buckets[name], key=lambda x: x.name)))
            seen.add(name)
    for name in sorted(buckets):
        if name not in seen and buckets[name]:
            result.append((name, sorted(buckets[name], key=lambda x: x.name)))
    return result
