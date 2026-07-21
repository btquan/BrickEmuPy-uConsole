import queue
import os
import json
import tempfile
import subprocess

from ipc import FramedReader, FramedWriter
from runtime import emulator_interpreter

from PyQt6 import QtCore, QtGui, QtWidgets, QtSvgWidgets, QtSvg
from PyQt6.QtCore import Qt, pyqtSignal, QThread, pyqtSlot
from PyQt6.QtWidgets import QGraphicsScene, QMessageBox
from functools import partial

import audio_engine
from emulator_process import *

DEFAULT_MOTION_BLUR = 0.6
DEFAULT_GHOST_SEGMENTS = 0
DEFAULT_SHADOW = 5

DATA_QUEUE_MAXSIZE = 1000

class QueueReaderThread(QThread):
    messageSignal = pyqtSignal(list)

    def __init__(self, data_queue):
        super().__init__()
        self._dataQueue = data_queue
        self._running = True

    def run(self):
        while self._running:
            try:
                self.messageSignal.emit(self._dataQueue.get(timeout=0.1))
            except queue.Empty:
                continue
            except EOFError:
                break

    def stop(self):
        self._running = False
        self.wait()


class BrickWidget(QtWidgets.QGraphicsView):
    examineSignal = pyqtSignal(dict)
    connectionSignal = pyqtSignal(bytes)
    frameRendered = pyqtSignal()

    def __init__(self, config, settings):
        super().__init__()

        self.setViewportUpdateMode(QtWidgets.QGraphicsView.ViewportUpdateMode.MinimalViewportUpdate)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QtWidgets.QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setDragMode(QtWidgets.QGraphicsView.DragMode.ScrollHandDrag)
        self.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        self.setBackgroundRole(QtGui.QPalette.ColorRole.NoRole)
        self.setFrameStyle(0)
        
        self._config = config
        self._settings = settings

        self._displaySettings = {}
        self._motionBlur = DEFAULT_MOTION_BLUR
        self._ghostSegments = DEFAULT_GHOST_SEGMENTS
        self._shadow = DEFAULT_SHADOW
        self._screenFit = False
        self._lcdRect = None

        self._loadSettings()

        self._audioEngine = audio_engine.getAudioEngine()

        self._start_emulator()

        self._draw(config["face_path"])

    def _start_emulator(self):
        fd, self._config_path = tempfile.mkstemp(suffix=".brickcfg.json")
        with os.fdopen(fd, "w") as f:
            json.dump(self._config, f)

        repo_dir = os.path.dirname(os.path.abspath(__file__))
        entry = os.path.join(repo_dir, "emulator_main.py")
        self._proc = subprocess.Popen(
            [emulator_interpreter(), entry, self._config_path],
            cwd=repo_dir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            bufsize=0,
        )
        self._cmdQueue = FramedWriter(self._proc.stdin)
        self._dataQueue = FramedReader(self._proc.stdout, maxsize=DATA_QUEUE_MAXSIZE)

        self._QueueReaderThread = QueueReaderThread(self._dataQueue)
        self._QueueReaderThread.messageSignal.connect(self._processMessage)
        self._QueueReaderThread.start()

    def _processMessage(self, msg):
        op = msg[0]
        if (op == MSG_VRAM):
            self._renderVRAM(msg[1])
            self.frameRendered.emit()
        elif (op == MSG_EXAMINE):
            self.examineSignal.emit(msg[1])
        elif (op == MSG_ERROR):
            self._error(msg[1])
        elif (op == MSG_SOUND_DATA):
            self._soundProcess(msg[1], msg[2], msg[3])
        elif (op == MSG_SOUND_RESET):
            self._audioEngine.reset()
        elif (op == MSG_SEND_DATA):
            self.connectionSignal.emit(msg[1])

    def close(self):
        if (self._QueueReaderThread):
            self._QueueReaderThread.stop()
            self._QueueReaderThread = None

        if (self._proc and self._proc.poll() is None):
            try:
                self._cmdQueue.put((CMD_QUIT,))
            except Exception:
                pass
            try:
                self._proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
                    self._proc.wait()

        if (getattr(self, "_cmdQueue", None)):
            try:
                self._cmdQueue.close()
            except Exception:
                pass

        if (getattr(self, "_dataQueue", None)):
            try:
                self._dataQueue.close()
            except Exception:
                pass

        if (getattr(self, "_config_path", None)):
            try:
                os.remove(self._config_path)
            except OSError:
                pass

        self._saveSettings()
        super().close()

    def showEvent(self, event):
        self._fitBrickInView()
        return super().showEvent(event)

    def _loadSettings(self):
        self._scene_rect = self._settings.value("brick/" + self._config["id"] + "/scene_rect")
        self._displaySettings = self._settings.value("display", {
            "motion_blur": True,
            "ghost_segments": True,
            "shadow": True,
        })

    def _saveSettings(self):
        if (self._screenFit):
            return
        self._settings.setValue("brick/" + self._config["id"] + "/scene_rect", self.mapToScene(self.viewport().rect()).boundingRect())

    def _soundProcess(self, channel, data, tick):
        if (data):
            self._audioEngine.play(channel, data[0], data[1], data[2], tick / 1e9, data[3])
        else:
            self._audioEngine.stop(channel, tick / 1e9)

    @pyqtSlot(dict)
    def editState(self, state):
        self._cmdQueue.put((CMD_EDIT_STATE, state))

    @pyqtSlot()
    def step(self):
        self._cmdQueue.put((CMD_DEBUG, CMD_DEBUG_STEP))

    @pyqtSlot()
    def pause(self):
        self._cmdQueue.put((CMD_DEBUG, CMD_DEBUG_PAUSE))

    @pyqtSlot()
    def stop(self):
        self._cmdQueue.put((CMD_DEBUG, CMD_DEBUG_STOP))

    @pyqtSlot()
    def run(self):
        self._cmdQueue.put((CMD_DEBUG, CMD_DEBUG_RUN))

    def setBreakpoint(self, pc, add):
        self._cmdQueue.put((CMD_BREAKPOINT, pc, add))

    @pyqtSlot()
    def setSpeed(self):
        self._cmdQueue.put((CMD_SPEED, self.sender().checkedAction().property("factor")))

    def fitToScreen(self, enabled=True):
        # Handheld mode: fit to the LCD (segment bounding box), cropping the
        # machine's plastic border so the screen fills the view. Opt-in; the
        # desktop app never calls this and keeps its whole-face fit.
        self._screenFit = enabled
        if (enabled):
            self._scene_rect = None
        self._fitBrickInView()

    def _screenRect(self):
        # Prefer the SVG's marked LCD region (crops cleanly to the screen).
        if (self._lcdRect is not None and not self._lcdRect.isEmpty()):
            rect = self._lcdRect
            margin = max(rect.width(), rect.height()) * 0.03
            return rect.adjusted(-margin, -margin, margin, margin)
        # Fallback: bounding box of the lit segments.
        if (not getattr(self, "_segments", None)):
            return None
        rect = None
        for seg in self._segments:
            r = seg[2].sceneBoundingRect()
            rect = r if (rect is None) else rect.united(r)
        if (rect is None or rect.isEmpty()):
            return None
        margin = max(rect.width(), rect.height()) * 0.06
        return rect.adjusted(-margin, -margin, margin, margin)

    def contentAspect(self):
        # width/height of the LCD region, so the handheld shell can lock the
        # view to it and clip the machine's plastic body. None if unknown.
        rect = self._screenRect()
        if (rect is None or rect.height() <= 0):
            return None
        return rect.width() / rect.height()

    def _fitBrickInView(self):
        if (self._screenFit):
            rect = self._screenRect()
            if (rect is not None):
                self.fitInView(rect, Qt.AspectRatioMode.KeepAspectRatio)
                return
        if (self._scene_rect is not None):
            self.fitInView(self._scene_rect, Qt.AspectRatioMode.KeepAspectRatio)
        else:
            self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event):
        self._fitBrickInView()
        return super().resizeEvent(event)

    def keyPressEvent(self, event):
        if (not event.isAutoRepeat()):
            for name, value in self._config["buttons"].items():
                if (event.key() in value["hot_keys"]):
                    self._cmdQueue.put((CMD_BTN_PRESS, name))

    def keyReleaseEvent(self, event):
        if (not event.isAutoRepeat()):
            for name, value in self._config["buttons"].items():
                if (event.key() in value["hot_keys"]):
                    self._cmdQueue.put((CMD_BTN_RELEASE, name))

    def wheelEvent(self, event):
        zoomFactor = 1.1
        if (event.modifiers() == QtCore.Qt.KeyboardModifier.ControlModifier):
            zoomFactor = 1.01
        if (event.angleDelta().y() < 0):
            zoomFactor = 1 / zoomFactor
        self.scale(zoomFactor, zoomFactor)
        self.centerOn(self.scene().sceneRect().center().x(), self.mapToScene(self.viewport().rect().center()).y())
        self._scene_rect = self.mapToScene(self.viewport().rect()).boundingRect()

    def mouseMoveEvent(self, event):
        if event.buttons() == QtCore.Qt.MouseButton.LeftButton:
            self._scene_rect = self.mapToScene(self.viewport().rect()).boundingRect()
        return super().mouseMoveEvent(event)

    def _draw(self, faceSVG):
        self.setScene(QGraphicsScene())
        self.scene().setItemIndexMethod(QGraphicsScene.ItemIndexMethod.NoIndex)
        faceRenderer = QtSvg.QSvgRenderer(faceSVG)
        if (not faceRenderer.isValid()):
            QMessageBox(parent=self, text="Error loading SVG file").exec()

        # If the SVG marks the LCD screen region, remember it so handheld
        # screen-fit can crop to just the display (dropping the plastic body).
        self._lcdRect = None
        for eid in ("display", "screen", "lcd"):
            if (faceRenderer.elementExists(eid)):
                self._lcdRect = faceRenderer.boundsOnElement(eid)
                break

        body = QtSvgWidgets.QGraphicsSvgItem()
        body.setSharedRenderer(faceRenderer)
        body.setElementId("body")
        self.scene().addItem(body)

        overlay = QtSvgWidgets.QGraphicsSvgItem()
        overlay.setSharedRenderer(faceRenderer)
        overlay.setElementId("overlay")

        self._segments = []
        for ramBit in range(8):
            for ramByte in range(256):
                nextId = str(ramByte) + "_" + str(ramBit)
                if (faceRenderer.elementExists(nextId)):
                    group = QtWidgets.QGraphicsItemGroup()
                    segment = QtSvgWidgets.QGraphicsSvgItem()
                    segment.setSharedRenderer(faceRenderer)
                    segment.setElementId(nextId)
                    segment.setPos(faceRenderer.boundsOnElement(nextId).topLeft())
                    group.addToGroup(segment)

                    segment_shadow = QtSvgWidgets.QGraphicsSvgItem()
                    segment_shadow.setSharedRenderer(faceRenderer)
                    segment_shadow.setElementId(nextId)
                    segment_shadow.setVisible(False)
                    segment_shadow.setOpacity(0.1)
                    group.addToGroup(segment_shadow)

                    self.scene().addItem(group)
                    self._segments.append([ramByte, ramBit, group, -1])

        self._updateDisplaySettings()

        overlay.setPos(faceRenderer.boundsOnElement("overlay").topLeft())
        self.scene().addItem(overlay)

        for name, value in self._config["buttons"].items():
            if (faceRenderer.elementExists(name)):
                btn = QtWidgets.QPushButton(objectName="brickButton")
                btn.setGeometry(faceRenderer.boundsOnElement(name).toRect())
                shortcuts = "Shortcuts: "
                for shortcut in value["hot_keys"]:
                    shortcuts += Qt.Key(shortcut).name + ", "
                btn.setToolTip(shortcuts[:-2])
                btn.pressed.connect(partial(self._cmdQueue.put, (CMD_BTN_PRESS, name)))
                btn.released.connect(partial(self._cmdQueue.put, (CMD_BTN_RELEASE, name)))
                self.scene().addWidget(btn)

    def _renderVRAM(self, RAM):
        k = 1 - self._motionBlur
        ghostSegments = self._ghostSegments
        ramSize = len(RAM)
        for seg in self._segments:
            nibble, bit, segment, opacity = seg
            if nibble < ramSize:
                target = ((RAM[nibble] >> bit) & 0x1) + ghostSegments
                if (opacity != target):
                    opacity += k * (target - opacity)
                    if abs(opacity - target) < 1e-3:
                        opacity = target
                    segment.setOpacity(opacity)
                    seg[-1] = opacity
            else:
                seg[-1] = 0
                segment.setOpacity(ghostSegments)

    def _error(self, error):
        QMessageBox(parent=self, text=error).exec()

    def setDisplaySetting(self, key, value):
        self._displaySettings[key] = value
        self._updateDisplaySettings()

    def _updateDisplaySettings(self):
        if (self._displaySettings):
            if (self._displaySettings.get("motion_blur", False)):
                self._motionBlur = self._config.get("display", {}).get("motion_blur", DEFAULT_MOTION_BLUR)
            else:
                self._motionBlur = 0
            if (self._displaySettings.get("ghost_segments", False)):
                self._ghostSegments = self._config.get("display", {}).get("ghost_segments", DEFAULT_GHOST_SEGMENTS)
            else:
                self._ghostSegments = 0
            if (self._displaySettings.get("shadow", False)):
                self._shadow = self._config.get("display", {}).get("shadow", DEFAULT_SHADOW)
            else:
                self._shadow = 0

        for seg in self._segments:
            segmentItem = seg[2].childItems()[0]
            shadowItem = seg[2].childItems()[1]
            if (self._shadow):
                shadowItem.setPos(segmentItem.sceneBoundingRect().topLeft() + QtCore.QPointF(self._shadow, self._shadow))
                shadowItem.setVisible(True)
            else:
                shadowItem.setVisible(False)

    def receiveData(self, data):
        self._cmdQueue.put((CMD_RECEIVE_DATA, data))