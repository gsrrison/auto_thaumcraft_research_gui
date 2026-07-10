import ctypes
import os
import sys
import threading
import time
import traceback
from enum import Enum
from pathlib import Path
from typing import Optional


os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "0")


def enable_dpi_awareness():
    if sys.platform != "win32":
        return
    try:
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


enable_dpi_awareness()

import keyboard
import pydirectinput
from PyQt5 import QtCore, QtGui, QtWidgets

from hcb import ids, name_mapping
from research_core import ConfigError, ResearchConfig, ResearchScanner, ScanResult


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "gc.txt"


def get_foreground_window() -> int:
    if sys.platform != "win32":
        return 0
    try:
        return int(ctypes.windll.user32.GetForegroundWindow())
    except (AttributeError, OSError):
        return 0


def activate_window(window_handle: int) -> bool:
    if not window_handle or sys.platform != "win32":
        return True
    try:
        ctypes.windll.user32.SetForegroundWindow(window_handle)
        return get_foreground_window() == window_handle
    except (AttributeError, OSError):
        return False


def safe_mouse_up():
    try:
        pydirectinput.mouseUp()
    except Exception:
        pass


def apply_no_activate_style(widget: QtWidgets.QWidget):
    """让悬浮控制窗可点击但不抢走 Minecraft 的前台焦点。"""
    if sys.platform != "win32":
        return
    try:
        hwnd = int(widget.winId())
        get_style = ctypes.windll.user32.GetWindowLongW
        set_style = ctypes.windll.user32.SetWindowLongW
        extended_style = get_style(hwnd, -20)
        set_style(hwnd, -20, extended_style | 0x08000000 | 0x00000080)
    except (AttributeError, OSError):
        pass


class AppState(Enum):
    IDLE = "idle"
    SCANNING = "scanning"
    READY = "ready"
    DRAGGING = "dragging"
    STOPPING = "stopping"
    STOPPED = "stopped"
    COMPLETE = "complete"
    ERROR = "error"


class OverlayWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        no_focus_flag = getattr(QtCore.Qt, "WindowDoesNotAcceptFocus", 0)
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.WindowStaysOnTopHint
            | QtCore.Qt.Tool
            | no_focus_flag
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WA_NoSystemBackground)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        show_without_activation = getattr(QtCore.Qt, "WA_ShowWithoutActivating", None)
        if show_without_activation is not None:
            self.setAttribute(show_without_activation)

        self.result: Optional[ScanResult] = None
        self.calibration_boxes = []
        self.selected_screen = QtGui.QGuiApplication.primaryScreen()
        self._refresh_geometry()
        apply_no_activate_style(self)

    def set_screen(self, screen, clear=True):
        if screen is None:
            return
        self.selected_screen = screen
        if clear:
            self.clear_overlay()
        self._refresh_geometry()

    def _refresh_geometry(self):
        screen = self.selected_screen or QtGui.QGuiApplication.primaryScreen()
        if screen is not None:
            self.setGeometry(screen.geometry())

    def show_result(self, result: ScanResult):
        self.calibration_boxes = []
        self.result = result
        self._refresh_geometry()
        self.update()
        self.show()

    def show_calibration(self, config: ResearchConfig):
        research_boxes, source_boxes = config.create_boxes()
        self.result = None
        self.calibration_boxes = research_boxes + source_boxes
        self._refresh_geometry()
        self.update()
        self.show()

    def clear_overlay(self):
        self.result = None
        self.calibration_boxes = []
        self.update()
        self.hide()

    def showEvent(self, event):
        apply_no_activate_style(self)
        super().showEvent(event)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

        if self.calibration_boxes:
            pen = QtGui.QPen(QtGui.QColor(0, 255, 80), 2)
            painter.setPen(pen)
            for box in self.calibration_boxes:
                painter.drawRect(box.rect)
            painter.end()
            return

        if self.result is not None:
            path_pen = QtGui.QPen(QtGui.QColor(255, 220, 0), 5)
            path_pen.setCapStyle(QtCore.Qt.RoundCap)
            painter.setPen(path_pen)
            for grid_path, _ in self.result.connections:
                if not grid_path:
                    continue
                previous = self.result.node_boxes[grid_path[0]]
                for node_id in grid_path[1:]:
                    current = self.result.node_boxes[node_id]
                    painter.drawLine(previous.center, current.center)
                    previous = current

            for box in self.result.research_boxes:
                box.draw(painter)
            for box in self.result.source_boxes:
                box.draw(painter)

        painter.end()


class ControlPanel(QtWidgets.QWidget):
    scan_requested = QtCore.pyqtSignal()
    drag_requested = QtCore.pyqtSignal()
    config_requested = QtCore.pyqtSignal()
    screen_requested = QtCore.pyqtSignal()
    closed = QtCore.pyqtSignal()

    def __init__(self):
        super().__init__()
        no_focus_flag = getattr(QtCore.Qt, "WindowDoesNotAcceptFocus", 0)
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.WindowStaysOnTopHint
            | QtCore.Qt.Tool
            | no_focus_flag
        )
        show_without_activation = getattr(QtCore.Qt, "WA_ShowWithoutActivating", None)
        if show_without_activation is not None:
            self.setAttribute(show_without_activation)
        self.setObjectName("controlPanel")
        self.setFixedWidth(300)
        self._drag_offset = None
        self.settings = QtCore.QSettings("AutoThaumcraftResearch", "ControlPanel")

        title = QtWidgets.QLabel("神秘时代自动研究")
        title.setObjectName("title")
        title.installEventFilter(self)
        close_button = QtWidgets.QPushButton("×")
        close_button.setObjectName("closeButton")
        close_button.setFixedSize(28, 28)
        close_button.clicked.connect(self.close)

        title_layout = QtWidgets.QHBoxLayout()
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.addWidget(title)
        title_layout.addWidget(close_button)

        self.status_label = QtWidgets.QLabel("等待扫描")
        self.status_label.setObjectName("status")
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumHeight(42)

        self.scan_button = QtWidgets.QPushButton("扫描研究  Ctrl + 8")
        self.drag_button = QtWidgets.QPushButton("开始连线  Ctrl + 5")
        self.config_button = QtWidgets.QPushButton("坐标设置")
        self.screen_button = QtWidgets.QPushButton("选择屏幕")
        self.scan_button.clicked.connect(self.scan_requested)
        self.drag_button.clicked.connect(self.drag_requested)
        self.config_button.clicked.connect(self.config_requested)
        self.screen_button.clicked.connect(self.screen_requested)

        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)

        hint = QtWidgets.QLabel("Esc：紧急停止")
        hint.setObjectName("hint")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(9)
        layout.addLayout(title_layout)
        layout.addWidget(self.status_label)
        layout.addWidget(self.progress)
        layout.addWidget(self.scan_button)
        layout.addWidget(self.drag_button)
        layout.addWidget(self.config_button)
        layout.addWidget(self.screen_button)
        layout.addWidget(hint)

        self.setStyleSheet(
            """
            QWidget#controlPanel {
                background: rgba(24, 28, 35, 238);
                border: 1px solid #596273;
                border-radius: 9px;
                color: #edf2f7;
            }
            QLabel#title {
                color: #ffffff;
                font-family: "Microsoft YaHei UI", "Microsoft YaHei";
                font-size: 15px;
                font-weight: 700;
                padding: 3px;
            }
            QLabel#status {
                background: rgba(8, 12, 18, 150);
                border-radius: 5px;
                padding: 8px;
                color: #cde6ff;
            }
            QLabel#hint { color: #aeb8c8; font-size: 12px; }
            QPushButton {
                min-height: 34px;
                background: #34445b;
                border: 1px solid #58708f;
                border-radius: 5px;
                color: white;
                font-size: 13px;
            }
            QPushButton:hover { background: #405775; }
            QPushButton:pressed { background: #29394e; }
            QPushButton:disabled { color: #6f7885; background: #262c35; border-color: #363d48; }
            QPushButton#closeButton {
                min-height: 0px;
                background: transparent;
                border: none;
                font-size: 20px;
                color: #c8d0dc;
            }
            QPushButton#closeButton:hover { background: #75404a; }
            QProgressBar { height: 5px; border: none; background: #202631; border-radius: 2px; }
            QProgressBar::chunk { background: #4fa3e3; border-radius: 2px; }
            """
        )
        self.apply_state(AppState.IDLE, can_drag=False)
        self._restore_position()

    def set_hotkeys(self, scan_hotkey: str, drag_hotkey: str):
        self.scan_button.setText(f"扫描研究  {scan_hotkey.upper()}")
        self.drag_button.setText(f"开始连线  {drag_hotkey.upper()}")

    def set_screen_label(self, label: str):
        self.screen_button.setText(f"选择屏幕  {label}")

    def move_to_screen(self, screen, force=False):
        if screen is None:
            return
        area = screen.availableGeometry()
        if force or not area.contains(self.frameGeometry().center()):
            self.move(area.right() - self.width() - 24, area.top() + 80)

    def _restore_position(self):
        saved_position = self.settings.value("position")
        if isinstance(saved_position, QtCore.QPoint):
            self.move(saved_position)
            return
        screen = QtGui.QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            self.move(area.right() - self.width() - 24, area.top() + 80)

    def apply_state(self, state: AppState, can_drag: bool):
        busy = state in {AppState.SCANNING, AppState.DRAGGING, AppState.STOPPING}
        self.scan_button.setEnabled(not busy)
        self.config_button.setEnabled(not busy)
        self.screen_button.setEnabled(not busy)
        self.drag_button.setEnabled(state == AppState.READY and can_drag)
        if state in {AppState.SCANNING, AppState.DRAGGING, AppState.STOPPING}:
            self.progress.setRange(0, 0)
        elif self.progress.maximum() == 0:
            self.progress.setRange(0, 1)
            self.progress.setValue(0)

    def set_status(self, text: str):
        self.status_label.setText(text)

    def set_progress(self, completed: int, total: int):
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(completed)

    def eventFilter(self, watched, event):
        if event.type() == QtCore.QEvent.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
            self._drag_offset = event.globalPos() - self.frameGeometry().topLeft()
            return True
        if event.type() == QtCore.QEvent.MouseMove and self._drag_offset is not None:
            if event.buttons() & QtCore.Qt.LeftButton:
                self.move(event.globalPos() - self._drag_offset)
                return True
        if event.type() == QtCore.QEvent.MouseButtonRelease:
            self._drag_offset = None
            return True
        return super().eventFilter(watched, event)

    def showEvent(self, event):
        apply_no_activate_style(self)
        super().showEvent(event)

    def closeEvent(self, event):
        self.settings.setValue("position", self.pos())
        self.closed.emit()
        event.accept()


class ConfigDialog(QtWidgets.QDialog):
    preview_requested = QtCore.pyqtSignal(object)
    config_saved = QtCore.pyqtSignal(object)
    runtime_saved = QtCore.pyqtSignal(float, str, str)

    HEADERS = ("起始 X", "起始 Y", "横向间距", "横向数量", "纵向间距", "纵向数量", "框大小")
    ROWS = ("研究点阵 1", "研究点阵 2", "左侧要素", "右侧要素")

    def __init__(
        self,
        config: ResearchConfig,
        config_path: Path,
        drag_duration: float,
        scan_hotkey: str,
        drag_hotkey: str,
    ):
        super().__init__(None)
        self.config_path = config_path
        self.setWindowTitle("坐标设置")
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)
        self.resize(810, 360)

        self.table = QtWidgets.QTableWidget(4, 7)
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setVerticalHeaderLabels(self.ROWS)
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        for row, grid in enumerate(config.grids):
            for column, value in enumerate(grid.as_values()):
                self.table.setItem(row, column, QtWidgets.QTableWidgetItem(f"{value:g}"))

        explanation = QtWidgets.QLabel("预览会显示绿色框；保存后主程序会立即使用新坐标。")
        self.drag_duration = QtWidgets.QDoubleSpinBox()
        self.drag_duration.setRange(0.05, 1.50)
        self.drag_duration.setSingleStep(0.05)
        self.drag_duration.setSuffix(" 秒")
        self.drag_duration.setValue(drag_duration)
        self.scan_hotkey = QtWidgets.QLineEdit(scan_hotkey)
        self.drag_hotkey = QtWidgets.QLineEdit(drag_hotkey)

        runtime_form = QtWidgets.QFormLayout()
        runtime_form.addRow("单次拖动时长", self.drag_duration)
        runtime_form.addRow("扫描快捷键", self.scan_hotkey)
        runtime_form.addRow("连线快捷键", self.drag_hotkey)
        preview_button = QtWidgets.QPushButton("预览绿框")
        save_button = QtWidgets.QPushButton("保存并关闭")
        cancel_button = QtWidgets.QPushButton("取消")
        preview_button.clicked.connect(self._preview)
        save_button.clicked.connect(self._save)
        cancel_button.clicked.connect(self.reject)

        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addStretch(1)
        button_layout.addWidget(preview_button)
        button_layout.addWidget(save_button)
        button_layout.addWidget(cancel_button)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(explanation)
        layout.addWidget(self.table)
        layout.addLayout(runtime_form)
        layout.addLayout(button_layout)

    def _build_config(self) -> ResearchConfig:
        lines = []
        for row in range(self.table.rowCount()):
            values = []
            for column in range(self.table.columnCount()):
                item = self.table.item(row, column)
                values.append(item.text().strip() if item is not None else "")
            lines.append(",".join(values))
        return ResearchConfig.from_text("\n".join(lines))

    def _preview(self):
        try:
            self.preview_requested.emit(self._build_config())
        except ConfigError as exc:
            QtWidgets.QMessageBox.warning(self, "坐标错误", str(exc))

    def _save(self):
        try:
            config = self._build_config()
            scan_hotkey = self.scan_hotkey.text().strip().lower()
            drag_hotkey = self.drag_hotkey.text().strip().lower()
            if not scan_hotkey or not drag_hotkey:
                raise ConfigError("快捷键不能为空")
            if scan_hotkey == drag_hotkey or "esc" in {scan_hotkey, drag_hotkey}:
                raise ConfigError("两个功能快捷键必须不同，且不能占用 Esc")
            keyboard.parse_hotkey(scan_hotkey)
            keyboard.parse_hotkey(drag_hotkey)
            config.save(self.config_path)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "保存失败", str(exc))
            return
        self.runtime_saved.emit(self.drag_duration.value(), scan_hotkey, drag_hotkey)
        self.config_saved.emit(config)
        self.accept()


class ScanWorker(QtCore.QObject):
    finished = QtCore.pyqtSignal(object)
    failed = QtCore.pyqtSignal(str)

    def __init__(self, config: ResearchConfig, screen_bbox):
        super().__init__()
        self.config = config
        self.screen_bbox = screen_bbox

    @QtCore.pyqtSlot()
    def run(self):
        try:
            result = ResearchScanner().capture_and_scan(self.config, self.screen_bbox)
        except Exception as exc:
            traceback.print_exc()
            self.failed.emit(str(exc))
            return
        self.finished.emit(result)


class DragWorker(QtCore.QObject):
    progress = QtCore.pyqtSignal(int, int)
    finished = QtCore.pyqtSignal(bool, str)
    failed = QtCore.pyqtSignal(str)

    def __init__(
        self,
        result: ScanResult,
        stop_event: threading.Event,
        target_window: int,
        drag_duration: float,
        screen_origin,
    ):
        super().__init__()
        self.result = result
        self.stop_event = stop_event
        self.target_window = target_window
        self.drag_duration = drag_duration
        self.screen_origin = screen_origin

    def _must_stop(self) -> Optional[str]:
        if self.stop_event.is_set():
            return "已按 Esc 紧急停止"
        if self.target_window and get_foreground_window() != self.target_window:
            self.stop_event.set()
            return "游戏窗口失去焦点，已自动停止"
        return None

    def _move_cursor(self, x: int, y: int, _duration: float = 0.0) -> Optional[str]:
        """使用虚拟桌面坐标瞬移鼠标，保持旧版 pydirectinput 的速度。"""
        reason = self._must_stop()
        if reason:
            return reason

        if sys.platform != "win32":
            pydirectinput.moveTo(x, y)
            return self._must_stop()

        if not ctypes.windll.user32.SetCursorPos(x, y):
            raise RuntimeError("无法移动鼠标到所选屏幕")
        time.sleep(pydirectinput.PAUSE)
        return self._must_stop()

    @QtCore.pyqtSlot()
    def run(self):
        total = len(self.result.placements)
        pydirectinput.PAUSE = 0.02
        try:
            for index, placement in enumerate(self.result.placements):
                reason = self._must_stop()
                if reason:
                    self.finished.emit(True, reason)
                    return

                screen_x, screen_y = self.screen_origin
                source_x = placement.source.center.x() + screen_x
                source_y = placement.source.center.y() + screen_y
                target_x = placement.target.center.x() + screen_x
                target_y = placement.target.center.y() + screen_y

                reason = self._move_cursor(source_x, source_y)
                if reason:
                    self.finished.emit(True, reason)
                    return

                try:
                    pydirectinput.mouseDown()
                    time.sleep(0.08)
                    reason = self._must_stop()
                    if reason:
                        self.finished.emit(True, reason)
                        return
                    reason = self._move_cursor(target_x, target_y, self.drag_duration)
                    if reason:
                        self.finished.emit(True, reason)
                        return
                finally:
                    safe_mouse_up()

                reason = self._must_stop()
                if reason:
                    self.finished.emit(True, reason)
                    return
                self.progress.emit(index + 1, total)

            self.finished.emit(False, "连线完成，请重新扫描下一项研究")
        except Exception as exc:
            traceback.print_exc()
            self.failed.emit(str(exc))
        finally:
            safe_mouse_up()


class HotkeyBridge(QtCore.QObject):
    scan = QtCore.pyqtSignal()
    drag = QtCore.pyqtSignal()
    emergency = QtCore.pyqtSignal()


class HotkeyManager:
    def __init__(self, bridge: HotkeyBridge, stop_event: threading.Event):
        self.bridge = bridge
        self.stop_event = stop_event
        self.handles = []

    def register(self, scan_hotkey: str, drag_hotkey: str) -> Optional[str]:
        try:
            self.handles.append(keyboard.add_hotkey(scan_hotkey, self.bridge.scan.emit))
            self.handles.append(keyboard.add_hotkey(drag_hotkey, self.bridge.drag.emit))
            self.handles.append(keyboard.add_hotkey("esc", self._emergency_stop))
        except Exception as exc:
            self.unregister()
            return str(exc)
        return None

    def _emergency_stop(self):
        self.stop_event.set()
        safe_mouse_up()
        self.bridge.emergency.emit()

    def unregister(self):
        for handle in self.handles:
            try:
                keyboard.remove_hotkey(handle)
            except Exception:
                pass
        self.handles.clear()


class ApplicationController(QtCore.QObject):
    def __init__(self, app: QtWidgets.QApplication):
        super().__init__()
        self.app = app
        self.state = AppState.IDLE
        self.overlay = OverlayWindow()
        self.panel = ControlPanel()
        self.stop_event = threading.Event()
        self.latest_result: Optional[ScanResult] = None
        self.target_window = 0
        self.config_dialog: Optional[ConfigDialog] = None
        self.scan_thread = None
        self.scan_worker = None
        self.drag_thread = None
        self.drag_worker = None
        self.selected_screen = self._load_selected_screen()
        self.overlay.set_screen(self.selected_screen)
        self.panel.set_screen_label(self._screen_short_label(self.selected_screen))
        self.panel.move_to_screen(self.selected_screen)
        self.last_external_window = get_foreground_window()
        self.scan_hotkey = str(self.panel.settings.value("scan_hotkey", "ctrl+8"))
        self.drag_hotkey = str(self.panel.settings.value("drag_hotkey", "ctrl+5"))
        try:
            self.drag_duration = float(self.panel.settings.value("drag_duration", 0.3))
        except (TypeError, ValueError):
            self.drag_duration = 0.3
        self.panel.set_hotkeys(self.scan_hotkey, self.drag_hotkey)

        self.panel.scan_requested.connect(self.scan)
        self.panel.drag_requested.connect(self.start_drag)
        self.panel.config_requested.connect(self.open_config)
        self.panel.screen_requested.connect(self.select_screen)
        self.panel.closed.connect(self.shutdown)

        self.hotkey_bridge = HotkeyBridge()
        self.hotkey_bridge.scan.connect(self.scan, QtCore.Qt.QueuedConnection)
        self.hotkey_bridge.drag.connect(self.start_drag, QtCore.Qt.QueuedConnection)
        self.hotkey_bridge.emergency.connect(self.emergency_stop, QtCore.Qt.QueuedConnection)
        self.hotkeys = HotkeyManager(self.hotkey_bridge, self.stop_event)
        hotkey_error = self.hotkeys.register(self.scan_hotkey, self.drag_hotkey)
        if hotkey_error:
            self.panel.set_status(f"全局快捷键注册失败：{hotkey_error}\n仍可使用窗口按钮。")

        self.foreground_timer = QtCore.QTimer(self)
        self.foreground_timer.timeout.connect(self._remember_foreground_window)
        self.foreground_timer.start(100)
        self.app.screenRemoved.connect(self._screen_removed)
        self.app.aboutToQuit.connect(self._cleanup)
        self.panel.show()

    def _load_selected_screen(self):
        screens = QtGui.QGuiApplication.screens()
        saved_name = str(self.panel.settings.value("screen_name", ""))
        for screen in screens:
            if screen.name() == saved_name:
                return screen
        return QtGui.QGuiApplication.primaryScreen() or (screens[0] if screens else None)

    @staticmethod
    def _screen_short_label(screen):
        if screen is None:
            return "未检测到"
        raw_name = screen.name()
        digits = "".join(character for character in raw_name if character.isdigit())
        if digits:
            return f"屏幕 {digits}"
        screens = QtGui.QGuiApplication.screens()
        try:
            return f"屏幕 {screens.index(screen) + 1}"
        except ValueError:
            return raw_name or "未知屏幕"

    def _screen_menu_label(self, screen):
        geometry = screen.geometry()
        short_label = self._screen_short_label(screen)
        primary = "（主屏）" if screen == QtGui.QGuiApplication.primaryScreen() else ""
        return (
            f"{short_label}{primary}  {geometry.width()}×{geometry.height()}  "
            f"位置 ({geometry.x()}, {geometry.y()})"
        )

    def _screen_bbox(self):
        screen = self.selected_screen or QtGui.QGuiApplication.primaryScreen()
        if screen is None:
            raise RuntimeError("没有检测到可用屏幕")
        geometry = screen.geometry()
        return (
            geometry.x(),
            geometry.y(),
            geometry.x() + geometry.width(),
            geometry.y() + geometry.height(),
        )

    def _set_selected_screen(self, screen, invalidate_result=True):
        if screen is None:
            return
        changed = self.selected_screen is None or screen.name() != self.selected_screen.name()
        self.selected_screen = screen
        self.panel.settings.setValue("screen_name", screen.name())
        self.panel.set_screen_label(self._screen_short_label(screen))
        self.panel.move_to_screen(screen, force=changed)
        self.overlay.set_screen(screen, clear=changed)
        if changed and invalidate_result:
            self.latest_result = None
            self._set_state(AppState.IDLE, f"已切换到{self._screen_short_label(screen)}，请重新扫描")

    @QtCore.pyqtSlot()
    def select_screen(self):
        if self.config_dialog is not None or self.state in {
            AppState.SCANNING,
            AppState.DRAGGING,
            AppState.STOPPING,
        }:
            return
        menu = QtWidgets.QMenu(self.panel)
        menu.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, True)
        for screen in QtGui.QGuiApplication.screens():
            action = menu.addAction(self._screen_menu_label(screen))
            action.setCheckable(True)
            action.setChecked(
                self.selected_screen is not None and screen.name() == self.selected_screen.name()
            )
            action.triggered.connect(
                lambda checked=False, selected=screen: self._set_selected_screen(selected)
            )
        position = self.panel.screen_button.mapToGlobal(
            QtCore.QPoint(0, self.panel.screen_button.height())
        )
        menu.exec_(position)

    def _screen_removed(self, removed_screen):
        if self.selected_screen is not None and removed_screen.name() == self.selected_screen.name():
            self._set_selected_screen(QtGui.QGuiApplication.primaryScreen())

    def _own_window_handles(self):
        handles = {int(self.panel.winId()), int(self.overlay.winId())}
        if self.config_dialog is not None:
            handles.add(int(self.config_dialog.winId()))
        return handles

    @QtCore.pyqtSlot()
    def _remember_foreground_window(self):
        candidate = get_foreground_window()
        if candidate and candidate not in self._own_window_handles():
            self.last_external_window = candidate

    def _selected_target_window(self):
        candidate = get_foreground_window()
        if candidate and candidate not in self._own_window_handles():
            self.last_external_window = candidate
            return candidate
        return self.last_external_window

    def _set_state(self, state: AppState, text: str, can_drag: bool = False):
        self.state = state
        self.panel.set_status(text)
        self.panel.apply_state(state, can_drag)

    @QtCore.pyqtSlot()
    def scan(self):
        if self.config_dialog is not None or self.state in {
            AppState.SCANNING,
            AppState.DRAGGING,
            AppState.STOPPING,
        }:
            return
        try:
            config = ResearchConfig.load(CONFIG_PATH)
        except ConfigError as exc:
            self._set_state(AppState.ERROR, str(exc))
            return

        self.latest_result = None
        self.stop_event.clear()
        self.target_window = self._selected_target_window()
        self._set_state(
            AppState.SCANNING,
            f"正在截取{self._screen_short_label(self.selected_screen)}并计算连接方案……",
        )
        self.overlay.clear_overlay()
        self.panel.hide()
        try:
            screen_bbox = self._screen_bbox()
        except RuntimeError as exc:
            self.panel.show()
            self._set_state(AppState.ERROR, str(exc))
            return
        QtCore.QTimer.singleShot(150, lambda: self._start_scan_worker(config, screen_bbox))

    def _start_scan_worker(self, config: ResearchConfig, screen_bbox):
        self.scan_thread = QtCore.QThread(self)
        self.scan_worker = ScanWorker(config, screen_bbox)
        self.scan_worker.moveToThread(self.scan_thread)
        self.scan_thread.started.connect(self.scan_worker.run)
        self.scan_worker.finished.connect(self._scan_finished)
        self.scan_worker.failed.connect(self._scan_failed)
        self.scan_worker.finished.connect(self.scan_thread.quit)
        self.scan_worker.failed.connect(self.scan_thread.quit)
        self.scan_thread.finished.connect(self.scan_worker.deleteLater)
        self.scan_thread.finished.connect(self.scan_thread.deleteLater)
        self.scan_thread.finished.connect(self._scan_thread_finished)
        self.scan_thread.start()

    @QtCore.pyqtSlot(object)
    def _scan_finished(self, result: ScanResult):
        self.latest_result = result
        self.panel.show()
        self.overlay.show_result(result)

        if result.missing_aspects:
            names = "、".join(result.aspect_name(aspect_id) for aspect_id in result.missing_aspects)
            self._set_state(AppState.ERROR, f"扫描完成，但左右列表缺少：{names}")
            return
        if not result.placements:
            message = result.warnings[0] if result.warnings else "当前研究无需放置额外要素"
            self._set_state(AppState.COMPLETE, message)
            return

        message = f"扫描完成：识别 {result.fixed_count} 个固定要素，需要放置 {len(result.placements)} 个要素"
        if result.warnings:
            message += "\n" + "；".join(result.warnings)
        self._set_state(AppState.READY, message, can_drag=True)

    @QtCore.pyqtSlot(str)
    def _scan_failed(self, message: str):
        self.latest_result = None
        self.overlay.clear_overlay()
        self.panel.show()
        self._set_state(AppState.ERROR, f"扫描失败：{message}")

    @QtCore.pyqtSlot()
    def _scan_thread_finished(self):
        self.scan_worker = None
        self.scan_thread = None

    @QtCore.pyqtSlot()
    def start_drag(self):
        if self.config_dialog is not None or self.state != AppState.READY or self.latest_result is None:
            return
        if self.target_window and self._selected_target_window() != self.target_window:
            self._set_state(AppState.READY, "请先切回扫描时的 Minecraft 窗口，再开始连线", can_drag=True)
            return

        self.stop_event.clear()
        self._set_state(AppState.DRAGGING, "正在自动连线，按 Esc 可立即停止")

        # 两种窗口均在鼠标动作前隐藏，避免遮挡或接收任何一次点击。
        self.panel.hide()
        self.overlay.clear_overlay()
        QtCore.QTimer.singleShot(100, self._start_drag_worker)

    def _start_drag_worker(self):
        if self.latest_result is None or self.state != AppState.DRAGGING:
            return
        if self.target_window and not activate_window(self.target_window):
            self.panel.show()
            self.overlay.show_result(self.latest_result)
            self._set_state(
                AppState.READY,
                "无法切回扫描时的 Minecraft 窗口，请手动切回后重试",
                can_drag=True,
            )
            return
        self.drag_thread = QtCore.QThread(self)
        geometry = self.selected_screen.geometry()
        self.drag_worker = DragWorker(
            self.latest_result,
            self.stop_event,
            self.target_window,
            self.drag_duration,
            (geometry.x(), geometry.y()),
        )
        self.drag_worker.moveToThread(self.drag_thread)
        self.drag_thread.started.connect(self.drag_worker.run)
        self.drag_worker.progress.connect(self.panel.set_progress)
        self.drag_worker.finished.connect(self._drag_finished)
        self.drag_worker.failed.connect(self._drag_failed)
        self.drag_worker.finished.connect(self.drag_thread.quit)
        self.drag_worker.failed.connect(self.drag_thread.quit)
        self.drag_thread.finished.connect(self.drag_worker.deleteLater)
        self.drag_thread.finished.connect(self.drag_thread.deleteLater)
        self.drag_thread.finished.connect(self._drag_thread_finished)
        self.drag_thread.start()

    @QtCore.pyqtSlot()
    def emergency_stop(self):
        if self.state != AppState.DRAGGING:
            return
        self.stop_event.set()
        safe_mouse_up()
        if self.drag_thread is None:
            self.latest_result = None
            self.overlay.clear_overlay()
            self.panel.show()
            self._set_state(AppState.STOPPED, "已按 Esc 紧急停止，请重新扫描")
            return
        self.state = AppState.STOPPING
        # 等工作线程确认停止后再恢复控制窗，避免窗口出现在仍移动的鼠标下方。

    @QtCore.pyqtSlot(bool, str)
    def _drag_finished(self, cancelled: bool, message: str):
        safe_mouse_up()
        self.latest_result = None
        self.overlay.clear_overlay()
        self.panel.show()
        if cancelled or self.state == AppState.STOPPING:
            self._set_state(AppState.STOPPED, message + "，请重新扫描")
        else:
            self._set_state(AppState.COMPLETE, message)

    @QtCore.pyqtSlot(str)
    def _drag_failed(self, message: str):
        safe_mouse_up()
        self.latest_result = None
        self.overlay.clear_overlay()
        self.panel.show()
        self._set_state(AppState.ERROR, f"自动连线失败：{message}，请重新扫描")

    @QtCore.pyqtSlot()
    def _drag_thread_finished(self):
        self.drag_worker = None
        self.drag_thread = None

    @QtCore.pyqtSlot()
    def open_config(self):
        if self.config_dialog is not None or self.state in {
            AppState.SCANNING,
            AppState.DRAGGING,
            AppState.STOPPING,
        }:
            return
        try:
            config = ResearchConfig.load(CONFIG_PATH)
        except ConfigError as exc:
            self._set_state(AppState.ERROR, str(exc))
            return

        self.config_dialog = ConfigDialog(
            config,
            CONFIG_PATH,
            self.drag_duration,
            self.scan_hotkey,
            self.drag_hotkey,
        )
        self.target_window = self._selected_target_window()
        self.config_dialog.preview_requested.connect(self._preview_config)
        self.config_dialog.runtime_saved.connect(self._runtime_saved)
        self.config_dialog.config_saved.connect(self._config_saved)
        self.config_dialog.finished.connect(self._config_dialog_closed)
        self.panel.scan_button.setEnabled(False)
        self.panel.drag_button.setEnabled(False)
        self.panel.config_button.setEnabled(False)
        self.panel.screen_button.setEnabled(False)
        self.config_dialog.show()
        QtCore.QTimer.singleShot(0, self._move_config_dialog_to_selected_screen)

    def _move_config_dialog_to_selected_screen(self):
        if self.config_dialog is None or self.selected_screen is None:
            return
        area = self.selected_screen.availableGeometry()
        frame = self.config_dialog.frameGeometry()
        self.config_dialog.move(
            area.center().x() - frame.width() // 2,
            area.center().y() - frame.height() // 2,
        )

    @QtCore.pyqtSlot(object)
    def _preview_config(self, config: ResearchConfig):
        self.overlay.show_calibration(config)

    @QtCore.pyqtSlot(object)
    def _config_saved(self, config: ResearchConfig):
        self.latest_result = None
        self._set_state(AppState.IDLE, "坐标已保存，请扫描研究")

    @QtCore.pyqtSlot(float, str, str)
    def _runtime_saved(self, drag_duration: float, scan_hotkey: str, drag_hotkey: str):
        old_scan_hotkey = self.scan_hotkey
        old_drag_hotkey = self.drag_hotkey
        self.hotkeys.unregister()
        hotkey_error = self.hotkeys.register(scan_hotkey, drag_hotkey)
        if hotkey_error:
            self.hotkeys.register(old_scan_hotkey, old_drag_hotkey)
            QtCore.QTimer.singleShot(
                0,
                lambda: self._set_state(AppState.ERROR, f"快捷键更新失败：{hotkey_error}"),
            )
            return

        self.drag_duration = drag_duration
        self.scan_hotkey = scan_hotkey
        self.drag_hotkey = drag_hotkey
        self.panel.settings.setValue("drag_duration", drag_duration)
        self.panel.settings.setValue("scan_hotkey", scan_hotkey)
        self.panel.settings.setValue("drag_hotkey", drag_hotkey)
        self.panel.set_hotkeys(scan_hotkey, drag_hotkey)

    @QtCore.pyqtSlot()
    def _config_dialog_closed(self):
        self.overlay.clear_overlay()
        if self.config_dialog is not None:
            self.config_dialog.deleteLater()
        self.config_dialog = None
        can_drag = self.state == AppState.READY and self.latest_result is not None
        self.panel.apply_state(self.state, can_drag=can_drag)

    @QtCore.pyqtSlot()
    def shutdown(self):
        self._cleanup()
        self.app.quit()

    def _cleanup(self):
        self.stop_event.set()
        safe_mouse_up()
        self.hotkeys.unregister()


def main():
    disable_scaling = getattr(QtCore.Qt, "AA_DisableHighDpiScaling", None)
    if disable_scaling is not None:
        QtWidgets.QApplication.setAttribute(disable_scaling, True)
    app = QtWidgets.QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    controller = ApplicationController(app)
    exit_code = app.exec_()
    controller._cleanup()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
