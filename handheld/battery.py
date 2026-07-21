"""Read uConsole battery state from sysfs. Pure and PyQt6-free."""
import os
from dataclasses import dataclass


@dataclass
class BatteryStatus:
    percent: int
    charging: bool


def read_battery(sysfs_root="/sys/class/power_supply"):
    try:
        for name in sorted(os.listdir(sysfs_root)):
            base = os.path.join(sysfs_root, name)
            cap_path = os.path.join(base, "capacity")
            if not os.path.isfile(cap_path):
                continue
            with open(cap_path) as f:
                percent = int(f.read().strip())
            charging = False
            status_path = os.path.join(base, "status")
            if os.path.isfile(status_path):
                with open(status_path) as f:
                    charging = f.read().strip().lower() in ("charging", "full")
            return BatteryStatus(percent=percent, charging=charging)
    except (OSError, ValueError):
        return None
    return None
