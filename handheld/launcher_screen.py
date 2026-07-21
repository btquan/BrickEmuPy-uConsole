from PyQt6 import QtWidgets, QtCore, QtGui, QtSvg

from handheld.launcher_selection import LauncherSelection, LEFT, RIGHT, UP, DOWN

_THUMB_HEIGHT = 92
_ROLE_DIR = {"DPAD_LEFT": LEFT, "DPAD_RIGHT": RIGHT,
             "DPAD_UP": UP, "DPAD_DOWN": DOWN}
_KEY_DIR = {
    QtCore.Qt.Key.Key_Left: LEFT, QtCore.Qt.Key.Key_Right: RIGHT,
    QtCore.Qt.Key.Key_Up: UP, QtCore.Qt.Key.Key_Down: DOWN,
}


def _render_thumbnail(svg_path, height):
    renderer = QtSvg.QSvgRenderer(svg_path)
    if not renderer.isValid():
        pix = QtGui.QPixmap(int(height * 0.6), height)
        pix.fill(QtCore.Qt.GlobalColor.darkGray)
        return pix
    bounds = renderer.boundsOnElement("body")
    if bounds.isEmpty():
        bounds = renderer.viewBoxF()
    aspect = bounds.width() / bounds.height() if bounds.height() else 0.6
    width = max(1, int(height * aspect))
    pix = QtGui.QPixmap(width, height)
    pix.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pix)
    renderer.render(painter, "body", QtCore.QRectF(0, 0, width, height))
    painter.end()
    return pix


def _make_tile(entry):
    tile = QtWidgets.QWidget()
    tile.setObjectName("launcherTile")
    v = QtWidgets.QVBoxLayout(tile)
    v.setContentsMargins(6, 6, 6, 6)
    thumb = QtWidgets.QLabel()
    thumb.setPixmap(_render_thumbnail(entry.svg_path, _THUMB_HEIGHT))
    thumb.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
    name = QtWidgets.QLabel(entry.name)
    name.setObjectName("launcherName")
    name.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
    v.addWidget(thumb)
    v.addWidget(name)
    return tile


class LauncherScreen(QtWidgets.QWidget):
    gameSelected = QtCore.pyqtSignal(str)

    def __init__(self, groups, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            'QWidget#launcherTile[selected="true"] '
            '{ border: 3px solid palette(highlight); border-radius: 6px; }')
        self._groups = [(name, items) for name, items in groups if items]
        self._selection = LauncherSelection(self._groups)
        self._tiles = {}      # (g, i) -> tile widget
        self._rows = []       # per group -> QScrollArea

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(8, 4, 8, 4)
        outer.setSpacing(2)
        if not self._groups:
            outer.addWidget(QtWidgets.QLabel("No games with ROMs found."))
            outer.addStretch(1)
            return

        for g, (gname, items) in enumerate(self._groups):
            label = QtWidgets.QLabel(gname)
            label.setObjectName("launcherGroup")
            outer.addWidget(label)

            row_area = QtWidgets.QScrollArea()
            row_area.setWidgetResizable(True)
            row_area.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
            row_area.setVerticalScrollBarPolicy(
                QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            row_area.setHorizontalScrollBarPolicy(
                QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            row = QtWidgets.QWidget()
            hbox = QtWidgets.QHBoxLayout(row)
            hbox.setContentsMargins(0, 0, 0, 0)
            for i, entry in enumerate(items):
                tile = _make_tile(entry)
                self._tiles[(g, i)] = tile
                hbox.addWidget(tile)
            hbox.addStretch(1)
            row_area.setWidget(row)
            self._rows.append(row_area)
            outer.addWidget(row_area)
        outer.addStretch(1)
        self._refresh()

    def _refresh(self):
        g, i = self._selection.position()
        for (tg, ti), tile in self._tiles.items():
            tile.setProperty("selected", tg == g and ti == i)
            tile.style().unpolish(tile)
            tile.style().polish(tile)
        sel = self._tiles.get((g, i))
        if sel is not None and 0 <= g < len(self._rows):
            self._rows[g].ensureWidgetVisible(sel)

    def handleRolePressed(self, role):
        if role in _ROLE_DIR:
            self._selection.move(_ROLE_DIR[role])
            self._refresh()
        elif role == "BTN_A":
            self._launch()

    def handleRoleReleased(self, role):
        pass

    def keyPressEvent(self, event):
        key = event.key()
        if key in _KEY_DIR:
            self._selection.move(_KEY_DIR[key])
            self._refresh()
        elif key in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter):
            self._launch()
        else:
            super().keyPressEvent(event)

    def _launch(self):
        entry = self._selection.selected()
        if entry is not None:
            self.gameSelected.emit(entry.brick_path)
