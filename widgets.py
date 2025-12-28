import math

from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QLabel,
    QSizePolicy,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)


class PanelBase(QWidget):
    """
    繪製自己的背景和虛線邊框的面板基類
    避免依賴 QSS 邊框渲染（在某些情況下可能不穩定）
    """

    def __init__(self, panel_bg: str, border: str, radius: int = 12):
        super().__init__()
        self._panel_bg = panel_bg
        self._border = border
        self._radius = radius
        self.setAttribute(Qt.WA_StyledBackground, True)

    def paintEvent(self, event):
        """繪製圓角背景和虛線邊框"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = self.rect().adjusted(2, 2, -2, -2)

        # 繪製背景
        painter.setBrush(QColor(self._panel_bg))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(rect, self._radius, self._radius)

        # 繪製虛線邊框
        pen = QPen(QColor(self._border))
        pen.setWidth(2)
        pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect, self._radius, self._radius)


class WaveformBusyIndicator(QWidget):
    """
    模擬音頻波形的忙碌指示器：
    等間距的垂直條，高度隨時間動畫變化
    """

    def __init__(
        self,
        accent: str,
        bar_width: int = 4,
        bar_gap: int = 3,
        min_height_ratio: float = 0.20,
        max_height_ratio: float = 0.95,
        fps: int = 30,
        speed: float = 0.22,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("WaveformIndicator")

        # 設置背景透明
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setStyleSheet("background: transparent;")

        self._color = QColor(accent)
        self._bar_width = max(1, int(bar_width))
        self._bar_gap = max(0, int(bar_gap))
        self._min_height_ratio = float(min_height_ratio)
        self._max_height_ratio = float(max_height_ratio)

        self._fps = max(1, int(fps))
        self._interval_ms = int(1000 / self._fps)
        self._speed = float(speed)
        self._phase = 0.0

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(self._interval_ms)

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_color(self, accent: str) -> None:
        """設置顏色"""
        self._color = QColor(accent)
        self.update()

    def _tick(self) -> None:
        """定時器回調：更新動畫相位"""
        self._phase += self._speed
        if self._phase > 1_000_000:
            self._phase = 0.0
        self.update()

    def showEvent(self, event) -> None:
        """顯示時啟動定時器"""
        super().showEvent(event)
        if not self._timer.isActive():
            self._timer.start(self._interval_ms)

    def hideEvent(self, event) -> None:
        """隱藏時停止定時器"""
        if self._timer.isActive():
            self._timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event) -> None:
        """繪製波形動畫"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        w = self.width()
        h = self.height()
        if w <= 0 or h <= 0:
            return

        step = self._bar_width + self._bar_gap
        if step <= 0:
            return

        # 根據當前寬度自動適配條數
        count = max(1, int((w + self._bar_gap) / step))
        total_w = count * self._bar_width + (count - 1) * self._bar_gap
        x = (w - total_w) / 2.0

        min_h = max(1.0, h * self._min_height_ratio)
        max_h = max(min_h, h * self._max_height_ratio)

        painter.setPen(Qt.NoPen)
        painter.setBrush(self._color)

        radius = min(self._bar_width / 2.0, 6.0)

        # 雙正弦混合產生更「音頻感」的動態效果
        for i in range(count):
            v1 = math.sin(self._phase + i * 0.55)
            v2 = math.sin(self._phase * 1.27 + i * 0.23 + 1.5)
            mixed = v1 * 0.65 + v2 * 0.35  # 範圍約 [-1, 1]
            norm = (mixed + 1.0) / 2.0     # -> [0, 1]

            bar_h = min_h + norm * (max_h - min_h)
            y = (h - bar_h) / 2.0

            rect = QRectF(x, y, float(self._bar_width), float(bar_h))
            painter.drawRoundedRect(rect, radius, radius)

            x += step


class DropArea(PanelBase):
    """拖放區域：顯示提示並接收拖放的檔案"""

    def __init__(self, callback, pal: dict[str, str]):
        super().__init__(panel_bg=pal["panel_bg"], border=pal["border"], radius=12)
        self.callback = callback
        self.setAcceptDrops(True)

        layout = QVBoxLayout()
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(10)

        label = QLabel("Drop video or audio files here")
        label.setAlignment(Qt.AlignCenter)
        label.setObjectName("DropLabel")

        hint = QLabel("MP4 • MKV • MOV • MP3 • WAV")
        hint.setAlignment(Qt.AlignCenter)
        hint.setObjectName("DropHint")

        layout.addStretch(1)
        layout.addWidget(label)
        layout.addWidget(hint)
        layout.addStretch(1)
        self.setLayout(layout)

    def dragEnterEvent(self, e: QDragEnterEvent):
        """拖放進入事件"""
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e: QDropEvent):
        """拖放釋放事件"""
        files = [url.toLocalFile() for url in e.mimeData().urls()]
        self.callback(files)


class BusyArea(PanelBase):
    """忙碌區域：顯示波形動畫和狀態文字"""

    def __init__(self, pal: dict[str, str], busy_widget: QWidget, status_label: QLabel):
        super().__init__(panel_bg=pal["panel_bg"], border=pal["border"], radius=12)

        layout = QVBoxLayout()
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(0)

        # 使用 QStackedLayout 讓 status_label 置中於 busy_widget 之上
        stack = QStackedLayout()
        stack.setStackingMode(QStackedLayout.StackAll)
        stack.addWidget(busy_widget)
        stack.addWidget(status_label)

        layout.addLayout(stack)
        self.setLayout(layout)
