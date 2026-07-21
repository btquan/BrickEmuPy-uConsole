import sys
import argparse

from PyQt6 import QtWidgets, QtCore

from handheld.window import HandheldWindow
from handheld.game_catalog import scan_catalog, group_catalog

ASSETS_DIR = "assets"


def main():
    parser = argparse.ArgumentParser(description="BrickEmuPy handheld shell.")
    parser.add_argument("-brick", required=False,
                        help="Boot straight into this Brick Game config (*.brick)")
    args = parser.parse_args()

    app = QtWidgets.QApplication(sys.argv)
    try:
        with open("ui/style.css") as f:
            app.setStyleSheet(f.read())
    except FileNotFoundError:
        pass

    settings = QtCore.QSettings("azya", "BrickEmuPy")
    groups = group_catalog(scan_catalog(ASSETS_DIR))
    window = HandheldWindow(groups, settings, initial_brick=args.brick)
    window.showFullScreen()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
