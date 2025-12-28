import math
import traceback
from pathlib import Path
from PySide6.QtCore import Qt, QTimer, QRectF, QSize
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QIcon,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)
from recorder import AudioRecorder


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


class MiniRecordIndicator(QWidget):
    """RecordArea 左側的小動畫：4 條豎線（錄音時）/ 4 個點（閒置時）。

    原理跟 WaveformBusyIndicator 類似，但固定 4 個元素，讓 UI 更簡潔。
    """

    def __init__(
        self,
        accent: str,
        fps: int = 30,
        speed: float = 0.25,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setStyleSheet("background: transparent;")

        self._color = QColor(accent)
        self._active = False
        self._phase = 0.0
        self._speed = float(speed)

        self._fps = max(1, int(fps))
        self._interval_ms = int(1000 / self._fps)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

        self.setFixedWidth(44)
        self.setMinimumHeight(24)

    def set_color(self, accent: str) -> None:
        self._color = QColor(accent)
        self.update()

    def set_active(self, active: bool) -> None:
        """設定是否播放動畫（錄音中 = True）。"""
        active = bool(active)
        if self._active == active:
            return

        self._active = active
        if self._active:
            if not self._timer.isActive():
                self._timer.start(self._interval_ms)
        else:
            if self._timer.isActive():
                self._timer.stop()
            self.update()

    def _tick(self) -> None:
        self._phase += self._speed
        if self._phase > 1_000_000:
            self._phase = 0.0
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        w = self.width()
        h = self.height()
        if w <= 0 or h <= 0:
            return

        painter.setPen(Qt.NoPen)
        painter.setBrush(self._color)

        count = 4
        gap = 6
        bar_w = 5
        total_w = count * bar_w + (count - 1) * gap
        start_x = (w - total_w) / 2.0

        if not self._active:
            # 閒置：豎線縮成 4 個點
            radius = 2.2
            y = h * 0.65
            for i in range(count):
                x = start_x + i * (bar_w + gap) + bar_w / 2.0
                painter.drawEllipse(QRectF(x - radius, y - radius, radius * 2, radius * 2))
            return

        # 錄音：4 條豎線隨時間跳動
        min_h = max(4.0, h * 0.25)
        max_h = max(min_h, h * 0.90)
        radius = min(bar_w / 2.0, 4.0)

        for i in range(count):
            v = math.sin(self._phase + i * 0.8) * 0.7 + math.sin(self._phase * 1.17 + i * 0.33) * 0.3
            norm = (v + 1.0) / 2.0
            bar_h = min_h + norm * (max_h - min_h)

            x = start_x + i * (bar_w + gap)
            y = (h - bar_h) / 2.0
            painter.drawRoundedRect(QRectF(x, y, bar_w, bar_h), radius, radius)


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


class RecordArea(PanelBase):
    """錄音區域：計時器 + (Record/Pause) + Undo + Transcribe。

    設計重點：
    - UI 只負責「錄音狀態」與「事件回呼」，實際轉譯流程由 MainWindow 控制。
    - 錄音資料不落地：AudioRecorder.stop() 回傳 numpy float32 waveform。
    """

    def __init__(
        self,
        pal: dict[str, str],
        *,
        get_input_device,
        on_transcribe,
        on_error,
        asset_dir: Path | None = None,
    ):
        super().__init__(panel_bg=pal["panel_bg"], border=pal["border"], radius=12)

        self._pal = pal
        self._get_input_device = get_input_device
        self._on_transcribe = on_transcribe
        self._on_error = on_error

        self._asset_dir = asset_dir or (Path(__file__).resolve().parent / "asset")
        self._recorder = AudioRecorder(sample_rate=16000, channels=1)

        self._state = "idle"  # idle / recording / paused
        self._elapsed_seconds = 0

        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._tick_clock)

        self._build_ui()

    def _build_ui(self) -> None:
        root = QHBoxLayout()
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(12)

        # 左側：迷你波形/點點
        self.indicator = MiniRecordIndicator(self._pal["accent"])
        root.addWidget(self.indicator, 0, Qt.AlignVCenter)

        # 中間：計時器
        self.timer_label = QLabel("0:00:00")
        self.timer_label.setObjectName("RecordTimer")
        self.timer_label.setAlignment(Qt.AlignCenter)
        root.addWidget(self.timer_label, 1)

        # 右側：按鍵群（純圖示）
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.btn_record_pause = self._make_icon_button("R", tooltip="Record / Pause")
        self.btn_undo = self._make_icon_button("U", tooltip="Undo (clear recording)")
        self.btn_transcribe = self._make_icon_button("T", tooltip="Transcribe (in-memory)")

        self.btn_record_pause.clicked.connect(self._on_record_pause_clicked)
        self.btn_undo.clicked.connect(self._on_undo_clicked)
        self.btn_transcribe.clicked.connect(self._on_transcribe_clicked)

        btn_row.addWidget(self.btn_record_pause)
        btn_row.addWidget(self.btn_undo)
        btn_row.addWidget(self.btn_transcribe)

        btn_wrap = QWidget()
        btn_wrap.setLayout(btn_row)
        root.addWidget(btn_wrap, 0, Qt.AlignVCenter)

        self.setLayout(root)

        # 初始狀態
        self._apply_icon_paths()
        self._sync_ui()

    def _make_icon_button(self, fallback_text: str, tooltip: str = "") -> QPushButton:
        btn = QPushButton()
        btn.setObjectName("IconButton")
        btn.setFixedSize(38, 38)
        btn.setToolTip(tooltip)
        btn.setText(fallback_text)  # 若 icon 檔案不存在，至少還能操作/除錯
        btn.setFocusPolicy(Qt.NoFocus)
        return btn

    def _set_btn_icon(self, btn: QPushButton, png_path: Path, *, fallback_text: str) -> None:
        if png_path.exists():
            btn.setText("")
            btn.setIcon(QIcon(str(png_path)))
            btn.setIconSize(QSize(int(btn.width() * 0.62), int(btn.height() * 0.62)))
        else:
            # icon 尚未放入專案時：保留 fallback text
            btn.setIcon(QIcon())
            btn.setText(fallback_text)

    def _apply_icon_paths(self) -> None:
        """讀取 ./asset/ 的 png 圖示。

        檔名是「預設值」：使用者可自行替換檔案（或改這裡的命名規則）。
        """
        record_png = self._asset_dir / "record.png"
        pause_png = self._asset_dir / "pause.png"
        undo_png = self._asset_dir / "undo.png"
        transcribe_png = self._asset_dir / "transcribe.png"

        # Record/Pause 由狀態決定 icon
        self._record_png = record_png
        self._pause_png = pause_png

        self._set_btn_icon(self.btn_undo, undo_png, fallback_text="U")
        self._set_btn_icon(self.btn_transcribe, transcribe_png, fallback_text="T")

    def _sync_ui(self) -> None:
        """依照目前狀態同步 UI（文字、按鈕 enable、動畫）。"""
        self.timer_label.setText(self._format_time(self._elapsed_seconds))

        if self._state == "recording":
            self.indicator.set_active(True)
            self._set_btn_icon(self.btn_record_pause, self._pause_png, fallback_text="P")
            self.btn_transcribe.setEnabled(True)
        elif self._state == "paused":
            self.indicator.set_active(False)
            self._set_btn_icon(self.btn_record_pause, self._record_png, fallback_text="R")
            self.btn_transcribe.setEnabled(True)
        else:
            self.indicator.set_active(False)
            self._set_btn_icon(self.btn_record_pause, self._record_png, fallback_text="R")
            self.btn_transcribe.setEnabled(self._elapsed_seconds > 0)

        self.btn_undo.setEnabled(self._elapsed_seconds > 0 or self._recorder.is_recording)

    @staticmethod
    def _format_time(total_seconds: int) -> str:
        total_seconds = max(0, int(total_seconds))
        h = total_seconds // 3600
        m = (total_seconds % 3600) // 60
        s = total_seconds % 60
        return f"{h}:{m:02d}:{s:02d}"

    def _tick_clock(self) -> None:
        self._elapsed_seconds += 1
        self._sync_ui()

    def set_controls_enabled(self, enabled: bool) -> None:
        """讓 MainWindow 在 BusyArea 時禁用/啟用按鍵。"""
        enabled = bool(enabled)
        self.btn_record_pause.setEnabled(enabled)
        self.btn_undo.setEnabled(enabled)
        self.btn_transcribe.setEnabled(enabled and (self._elapsed_seconds > 0 or self._state != "idle"))

    def shutdown(self) -> None:
        """程式關閉時，保證錄音 stream 被關閉。"""
        try:
            self._recorder.reset()
        except Exception:
            pass

    def reset_recording(self) -> None:
        """強制停止並清空錄音（切換模式或主題時可用）。"""
        self._clock_timer.stop()
        try:
            self._recorder.reset()
        except Exception:
            pass
        self._state = "idle"
        self._elapsed_seconds = 0
        self._sync_ui()

    def _on_record_pause_clicked(self) -> None:
        try:
            if self._state == "idle":
                self._start_recording()
            elif self._state == "recording":
                self._pause_recording()
            else:
                self._resume_recording()
        except Exception as exc:
            self._on_error(str(exc).strip() or exc.__class__.__name__, traceback.format_exc())

    def _start_recording(self) -> None:
        device_id = int(self._get_input_device() or -1)
        self._recorder.start(device_id=device_id)

        self._state = "recording"
        if self._elapsed_seconds <= 0:
            self._elapsed_seconds = 0

        if not self._clock_timer.isActive():
            self._clock_timer.start()

        self._sync_ui()

    def _pause_recording(self) -> None:
        self._recorder.pause()
        self._state = "paused"
        if self._clock_timer.isActive():
            self._clock_timer.stop()
        self._sync_ui()

    def _resume_recording(self) -> None:
        self._recorder.resume()
        self._state = "recording"
        if not self._clock_timer.isActive():
            self._clock_timer.start()
        self._sync_ui()

    def _on_undo_clicked(self) -> None:
        self.reset_recording()

    def _on_transcribe_clicked(self) -> None:
        try:
            if self._state in ("recording", "paused"):
                if self._clock_timer.isActive():
                    self._clock_timer.stop()

            audio = self._recorder.stop()
            self._state = "idle"
            # 按下 Transcribe 後：UI 回到可再次錄音的狀態
            recorded_seconds = int(self._elapsed_seconds)
            self._elapsed_seconds = 0
            self._sync_ui()

            # 避免空音訊
            if audio is None or getattr(audio, "size", 0) <= 0:
                self._on_error("No recorded audio.", "")
                return

            # 很短的音訊往往只有環境雜訊，保守加個門檻
            if recorded_seconds <= 0:
                self._on_error("Recorded audio is too short.", "")
                return

            self._on_transcribe(audio)

        except Exception as exc:
            self._on_error(str(exc).strip() or exc.__class__.__name__, traceback.format_exc())


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
