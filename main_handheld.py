import sys
import json
import argparse

from PyQt6 import QtWidgets, QtCore

from handheld.window import HandheldWindow


def main():
    parser = argparse.ArgumentParser(description="BrickEmuPy handheld shell.")
    parser.add_argument("-brick", required=True, help="Brick Game config (*.brick)")
    args = parser.parse_args()

    try:
        with open(args.brick) as f:
            config = json.load(f)
    except (OSError, ValueError) as e:   # ValueError covers JSONDecodeError + UnicodeDecodeError
        print("Cannot open brick config: %s" % e, file=sys.stderr)
        return 2

    app = QtWidgets.QApplication(sys.argv)
    try:
        with open("ui/style.css") as f:
            app.setStyleSheet(f.read())
    except FileNotFoundError:
        pass

    settings = QtCore.QSettings("azya", "BrickEmuPy")
    window = HandheldWindow(config, args.brick, settings)
    window.showFullScreen()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
