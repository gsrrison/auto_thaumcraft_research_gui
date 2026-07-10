import sys
import ctypes
from pathlib import Path

from PyQt5 import QtCore, QtGui, QtWidgets
from research_core import ConfigError, ResearchConfig

# 配置
CONFIG_PATH = Path(__file__).resolve().parent / "gc.txt"
RELOAD_INTERVAL = 500  # ms

class OverlayWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint |
            QtCore.Qt.WindowStaysOnTopHint |
            QtCore.Qt.Tool
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WA_NoSystemBackground)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)

        # 全屏覆盖
        screen = QtGui.QGuiApplication.primaryScreen()
        if screen is not None:
            self.setGeometry(screen.geometry())

        # 点击穿透
        hwnd = int(self.winId())
        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x80000
        WS_EX_TRANSPARENT = 0x20
        WS_EX_TOOLWINDOW = 0x80
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        style |= WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW
        ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)

        # 加载框配置与模型
        self.box_objects = []
        self.last_modified = None
        self.load_config()

        # 定时重载配置
        self.reload_timer = QtCore.QTimer()
        self.reload_timer.timeout.connect(self.on_reload)
        self.reload_timer.start(RELOAD_INTERVAL)


    def load_config(self):
        if not CONFIG_PATH.exists():
            self.box_objects = []
            return
        try:
            modified = CONFIG_PATH.stat().st_mtime_ns
            if modified == self.last_modified:
                return
            config = ResearchConfig.load(CONFIG_PATH)
            research_boxes, source_boxes = config.create_boxes()
        except (ConfigError, OSError) as exc:
            print(f"坐标配置读取失败：{exc}")
            return
        self.last_modified = modified
        self.box_objects = research_boxes + source_boxes

    @QtCore.pyqtSlot()
    def on_reload(self):
        self.load_config()
        self.update()

    @QtCore.pyqtSlot()
    def detect_boxes(self):
        if not self.box_objects:
            return

        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setPen(QtGui.QPen(QtGui.QColor(0, 255, 0), 2))
        for box in self.box_objects:
            painter.drawRect(box.rect)
        painter.end()


if __name__ == '__main__':
    print("[INFO] 坐标预览已启动，修改 gc.txt 后会自动刷新。")
    app = QtWidgets.QApplication(sys.argv)
    window = OverlayWindow()
    window.show()
    sys.exit(app.exec_())
