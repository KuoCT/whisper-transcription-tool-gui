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
        bar_width: int = 5,
        bar_gap: int = 5,
        min_height_ratio: float = 0.20,
        max_height_ratio: float = 1,
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
    """RecordArea 的迷你動畫：豎線（錄音中）/ 點點（閒置時）。

    這個元件刻意做得「小而可控」：不追求寫實波形，只提供清楚的錄音狀態回饋。

    你可以在 __init__ 這裡調整外觀參數：
    - bar_count：豎線數量（例如 15）
    - bar_width：單條豎線寬度
    - bar_gap：豎線間距（等間隔）
    - min_height_ratio / max_height_ratio：豎線高度範圍（相對於 widget 高度）
    """

    def __init__(
        self,
        accent: str,
        *,
        bar_count: int = 15,
        bar_width: int = 3,
        bar_gap: int = 3,
        min_height_ratio: float = 0.25,
        max_height_ratio: float = 1,
        idle_dot_radius: float = 2.2,
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

        # --- 外觀參數（可調整豎線數量 / 間距 / 高度）---
        self._bar_count = max(1, int(bar_count))
        self._bar_width = max(1, int(bar_width))
        self._bar_gap = max(0, int(bar_gap))
        self._min_height_ratio = float(min_height_ratio)
        self._max_height_ratio = float(max_height_ratio)
        self._idle_dot_radius = float(idle_dot_radius)

        self._fps = max(1, int(fps))
        self._interval_ms = int(1000 / self._fps)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

        # 依照豎線數量估算一個合理寬度，避免「多條」時擠在一起看不清楚
        total_w = self._bar_count * self._bar_width + (self._bar_count - 1) * self._bar_gap
        self.setFixedWidth(max(44, total_w + 8))
        self.setMinimumHeight(24)

    def set_color(self, accent: str) -> None:
        """設置顏色"""
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

        count = self._bar_count
        gap = self._bar_gap
        bar_w = self._bar_width

        total_w = count * bar_w + (count - 1) * gap
        start_x = (w - total_w) / 2.0

        if not self._active:
            # 閒置：豎線縮成點點（維持等間隔位置，不會跳動）
            radius = max(1.0, self._idle_dot_radius)
            y = h * 0.65
            for i in range(count):
                x = start_x + i * (bar_w + gap) + bar_w / 2.0
                painter.drawEllipse(QRectF(x - radius, y - radius, radius * 2, radius * 2))
            return

        # 錄音：豎線隨時間跳動（高度在 min/max 之間變化）
        min_h = max(4.0, h * self._min_height_ratio)
        max_h = max(min_h, h * self._max_height_ratio)
        radius = min(bar_w / 2.0, 4.0)

        for i in range(count):
            v1 = math.sin(self._phase + i * 0.55)
            v2 = math.sin(self._phase * 1.25 + i * 0.21 + 1.2)
            mixed = v1 * 0.65 + v2 * 0.35  # 範圍約 [-1, 1]
            norm = (mixed + 1.0) / 2.0     # -> [0, 1]

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
    """錄音區域：計時器 + Record + Pause + Undo + Transcribe。

    設計重點：
    - UI 只負責「錄音狀態」與「事件回呼」，實際轉譯流程由 MainWindow 控制。
    - 錄音資料不落地：AudioRecorder.stop() 回傳 numpy float32 waveform。
    - 按鍵外觀走「卡帶機」邏輯：Record 會保持按下狀態，直到按下 Pause 才會彈起。
    """

    def __init__(
        self,
        pal: dict[str, str],
        *,
        get_input_device,
        on_transcribe,
        on_error,
        on_record_start=None,
        on_record_cancel=None,
        asset_dir: Path | None = None,
    ):
        super().__init__(panel_bg=pal["panel_bg"], border=pal["border"], radius=12)

        self._pal = pal
        self._get_input_device = get_input_device
        self._on_transcribe = on_transcribe
        self._on_error = on_error
        self._on_record_start = on_record_start
        self._on_record_cancel = on_record_cancel

        self._asset_dir = asset_dir or (Path(__file__).resolve().parent / "asset")
        self._recorder = AudioRecorder(sample_rate=16000, channels=1)

        # 狀態機（idle / recording / paused）
        self._state = "idle"
        self._elapsed_seconds = 0

        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._tick_clock)

        self._build_ui()
        self._sync_ui()

    def _build_ui(self) -> None:
        """建立 UI：左側計時器，中央動畫 + 四個圖示按鍵。

        備註：
        - 透明背景與外觀統一交給 style.py（QSS）管理。
        - 這裡只放版面結構與行為綁定，避免 widgets.py 出現大量外觀代碼。
        """
        root = QHBoxLayout()
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(12)

        # 左側：計時器（HH:MM:SS，至少 2 位數；100 小時會顯示 100:00:00）
        self.timer_label = QLabel("00:00:00")
        self.timer_label.setObjectName("RecordTimer")
        self.timer_label.setAlignment(Qt.AlignCenter)

        # 固定寬度避免版面被字寬影響（也保留 100:00:00 的空間）
        self.timer_label.setFixedWidth(120)

        root.addWidget(self.timer_label, 0, Qt.AlignVCenter)

        # 中央：把動畫與按鍵群放在一起（背景必須透明，避免蓋住 PanelBase 的面板底色）
        center_wrap = QWidget()
        center_wrap.setObjectName("RecordCenterWrap")
        center_wrap.setAttribute(Qt.WA_StyledBackground, True)

        center_layout = QVBoxLayout(center_wrap)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(8)

        # 中央：迷你動畫（錄音時跳動，閒置時為點點）
        #
        # 想調整「豎線數量 / 間距 / 長度」：
        # - bar_count：豎線數量（目前先設 15）
        # - bar_width / bar_gap：粗細與間距（等間隔）
        # - min_height_ratio / max_height_ratio：豎線高度範圍（越大看起來越「長」）
        self.indicator = MiniRecordIndicator(
            self._pal["accent"],
            bar_count=20,
            bar_width=5,
            bar_gap=5,
            min_height_ratio=0.25,
            max_height_ratio=0.90,
        )

        center_layout.addStretch(1)
        center_layout.addWidget(self.indicator, 0, Qt.AlignHCenter)

        # 底部四個按鈕
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(10)

        # === 生成按鍵 ===
        self.btn_record = self._make_icon_button(tooltip="Record")
        self.btn_pause = self._make_icon_button(tooltip="Pause")
        self.btn_undo = self._make_icon_button(tooltip="Undo (clear recording)")
        self.btn_transcribe = self._make_icon_button(tooltip="Transcribe")

        self.btn_record.setCheckable(True)
        self.btn_pause.setCheckable(True)

        # === 綁定事件 ===
        self.btn_record.clicked.connect(self._on_record_clicked)
        self.btn_pause.clicked.connect(self._on_pause_clicked)
        self.btn_undo.clicked.connect(self._on_undo_clicked)
        self.btn_transcribe.clicked.connect(self._on_transcribe_clicked)

        # === 加入按鍵列 ===
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_record)
        btn_row.addWidget(self.btn_pause)
        btn_row.addWidget(self.btn_undo)
        btn_row.addWidget(self.btn_transcribe)
        btn_row.addStretch(1)

        center_layout.addLayout(btn_row)
        center_layout.addStretch(1)

        # 加回主體
        root.addWidget(center_wrap, 1)
        self.setLayout(root)

        # 載入 icons（若檔案不存在，退化成顯示字母）
        self._apply_icon_paths()

    def _make_icon_button(self, tooltip: str) -> QPushButton:
        """建立純圖示按鈕（統一尺寸與行為）。

        外觀（背景透明/外框/hover/checked）由 style.py 的 QPushButton#IconButton 統一控制。
        """
        btn = QPushButton("")
        btn.setObjectName("IconButton")
        btn.setToolTip(tooltip)
        btn.setFixedSize(46, 46)
        btn.setIconSize(QSize(28, 28))
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setAutoDefault(False)
        btn.setCursor(Qt.PointingHandCursor)
        return btn

    @staticmethod
    def _set_btn_icon(btn: QPushButton, icon_path: Path, fallback_text: str = "") -> None:
        if icon_path.exists():
            btn.setText("")
            btn.setIcon(QIcon(str(icon_path)))
            btn.setIconSize(QSize(28, 28))
        else:
            # 若沒有圖示檔案，先用字母代替，避免 UI 空白
            btn.setIcon(QIcon())
            btn.setText(fallback_text)

    def _apply_icon_paths(self) -> None:
        record_png = self._asset_dir / "record.png"
        pause_png = self._asset_dir / "pause.png"
        undo_png = self._asset_dir / "undo.png"
        transcribe_png = self._asset_dir / "transcribe.png"

        self._set_btn_icon(self.btn_record, record_png, fallback_text="R")
        self._set_btn_icon(self.btn_pause, pause_png, fallback_text="P")
        self._set_btn_icon(self.btn_undo, undo_png, fallback_text="U")
        self._set_btn_icon(self.btn_transcribe, transcribe_png, fallback_text="T")

    def _sync_ui(self) -> None:
        """依照目前狀態同步 UI（計時器、按鍵 enable、動畫、按下狀態）。"""
        self.timer_label.setText(self._format_time(self._elapsed_seconds))

        is_recording = self._state == "recording"
        is_paused = self._state == "paused"

        # 左側動畫：只在 recording 時播放
        self.indicator.set_active(is_recording)

        # 卡帶機效果：
        # - recording：Record 按下去
        # - paused：Pause 按下去（Record 彈起）
        # - idle：兩個都彈起
        self.btn_record.setChecked(is_recording)
        self.btn_pause.setChecked(is_paused)

        # 按鍵可用性
        self.btn_pause.setEnabled(self._state in ("recording", "paused"))
        self.btn_undo.setEnabled(self._elapsed_seconds > 0 or self._recorder.is_recording)

        # Transcribe：
        # - recording / paused：允許直接「停下來並轉譯」
        # - idle：有錄音才可按
        if self._state in ("recording", "paused"):
            self.btn_transcribe.setEnabled(True)
        else:
            self.btn_transcribe.setEnabled(self._elapsed_seconds > 0)

    @staticmethod
    def _format_time(total_seconds: int) -> str:
        total_seconds = max(0, int(total_seconds))
        h = total_seconds // 3600
        m = (total_seconds % 3600) // 60
        s = total_seconds % 60
        return f"{h:02d}:{m:02d}:{s:02d}"

    def _tick_clock(self) -> None:
        self._elapsed_seconds += 1
        self._sync_ui()

    def set_controls_enabled(self, enabled: bool) -> None:
        """讓 MainWindow 在 BusyArea 時禁用/啟用按鈕。

        注意：重新啟用時，需要依照目前狀態重新套用 enable/checked。
        """
        enabled = bool(enabled)
        if not enabled:
            self.btn_record.setEnabled(True)
            self.btn_pause.setEnabled(False)
            self.btn_undo.setEnabled(False)
            self.btn_transcribe.setEnabled(False)
            return

        # 重新啟用時：依照完整的狀態邏輯重新同步所有按鈕
        self._sync_ui()

    def shutdown(self) -> None:
        """程式關閉時，保證錄音 stream 被關閉。"""
        try:
            self._recorder.reset()
        except Exception:
            pass

    def reset_recording(self) -> None:
        """強制停止並清空錄音（切換模式或主題時可用）。"""
        had_activity = (
            self._state != "idle"
            or self._elapsed_seconds > 0
            or self._recorder.is_recording
        )
        self._clock_timer.stop()
        try:
            self._recorder.reset()
        except Exception:
            pass
        self._state = "idle"
        self._elapsed_seconds = 0
        self._sync_ui()

        if had_activity and self._on_record_cancel:
            self._on_record_cancel()

    # -------------------------------------------------------------------------
    # Button handlers
    # -------------------------------------------------------------------------

    def _on_record_clicked(self) -> None:
        """Record：開始錄音 / 續錄。

        錄音中再次點擊 Record：不做狀態切換（維持「按下去」）。
        """
        try:
            if self._state == "idle":
                self._start_recording()
            elif self._state == "paused":
                self._resume_recording()
            else:
                # recording：保持按下狀態（避免使用者誤點造成彈起）
                self._sync_ui()
        except Exception as exc:
            self._on_error(str(exc).strip() or exc.__class__.__name__, traceback.format_exc())

    def _on_pause_clicked(self) -> None:
        """Pause：只負責把錄音切到 paused。

        paused 再次點擊 Pause：維持 paused（Pause 仍保持按下去）。
        """
        try:
            if self._state == "recording":
                self._pause_recording()
            else:
                # idle / paused：恢復 UI 到正確的鎖定狀態
                self._sync_ui()
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

        if self._on_record_start:
            self._on_record_start()

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
                if self._on_record_cancel:
                    self._on_record_cancel()
                return

            # 很短的音訊往往只有環境雜訊，保守加個門檻
            if recorded_seconds <= 0:
                self._on_error("Recorded audio is too short.", "")
                if self._on_record_cancel:
                    self._on_record_cancel()
                return

            self._on_transcribe(audio)

        except Exception as exc:
            self._on_error(str(exc).strip() or exc.__class__.__name__, traceback.format_exc())
            if self._on_record_cancel:
                self._on_record_cancel()


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
