import json
import math
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import Qt, QObject, Signal, QTimer, QRectF
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

# 把模型快取移到專案資料夾
BASE_DIR = Path(__file__).resolve().parent
os.environ["XDG_CACHE_HOME"] = str(BASE_DIR / "cache")

from audio_extract import extract_audio

# 配置文件路徑
CONFIG_FILE = BASE_DIR / "AppConfig.json"

# 默認配置
DEFAULT_CONFIG = {
    "theme": "dark",  # "dark" or "light"
    "model_name": "large",  # tiny, base, small, medium, large, turbo
    "model_ttl_seconds": 60,
    "output_dir": str(BASE_DIR / "output"),
}

WINDOW_WIDTH = 400
WINDOW_HEIGHT = 180

# 可選模型列表
AVAILABLE_MODELS = ["tiny", "base", "small", "medium", "large", "turbo"]


def load_config() -> dict:
    """載入配置文件"""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
                # 合併默認配置（處理新增的配置項）
                return {**DEFAULT_CONFIG, **config}
        except Exception as e:
            print(f"Failed to load config: {e}")
    return DEFAULT_CONFIG.copy()


def save_config(config: dict):
    """保存配置文件"""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Failed to save config: {e}")


def _get_palette(theme: str) -> dict[str, str]:
    """根據主題返回調色板"""
    if theme.lower() == "light":
        return {
            "window_bg": "#f6f7fb",
            "text": "#121417",
            "panel_bg": "#ffffff",
            "border": "#c7ccd6",
            "hint": "#5a6370",
            "accent": "#ccd9f7",
            "button_bg": "#e8eaed",
            "button_hover": "#d2d5da",
        }
    return {
        "window_bg": "#0f1115",
        "text": "#e6e6e6",
        "panel_bg": "#151923",
        "border": "#3b3f4a",
        "hint": "#a6abb8",
        "accent": "#395191",
        "button_bg": "#1f2329",
        "button_hover": "#2a2f38",
    }


def _build_stylesheet(pal: dict[str, str]) -> str:
    """構建 Qt 樣式表"""
    return f"""
        QWidget {{
            background: {pal["window_bg"]};
            color: {pal["text"]};
            font-size: 14px;
        }}
        QLabel {{
            background: transparent;
        }}
        #DropLabel {{
            font-size: 18px;
            font-weight: 600;
        }}
        #DropHint, #StatusLabel {{
            color: {pal["hint"]};
        }}
        QPushButton {{
            background: {pal["button_bg"]};
            color: {pal["text"]};
            border: 1px solid {pal["border"]};
            border-radius: 6px;
            padding: 8px 16px;
            font-size: 13px;
        }}
        QPushButton:hover {{
            background: {pal["button_hover"]};
        }}
        QPushButton:pressed {{
            background: {pal["border"]};
        }}
        QMessageBox {{
            background: {pal["panel_bg"]};
        }}
        QMessageBox QPushButton {{
            min-width: 80px;
            border: 1px solid {pal["border"]};
            border-radius: 4px;
            padding: 6px 12px;
        }}
    """


class ModelManager:
    """
    延遲載入 + TTL 自動卸載模型管理器
    
    重點設計以保持 GUI 響應性：
    - 在執行重操作（import/load model）時不持有鎖
    - 在 GUI 執行緒中，maybe_unload() 永遠不會阻塞等待鎖
    """

    def __init__(self, model_name: str, ttl_seconds: int = 60):
        self._model_name = model_name
        self._ttl_seconds = ttl_seconds

        self._lock = threading.Lock()
        self._model = None
        self._active_jobs = 0
        self._last_used = 0.0

        self._loading = False
        self._loaded_event = threading.Event()

    def update_config(self, model_name: str, ttl_seconds: int):
        """更新模型配置（需要重新載入）"""
        with self._lock:
            if self._model_name != model_name:
                # 模型名稱改變，強制卸載舊模型
                if self._model is not None:
                    old_model = self._model
                    self._model = None
                    # 在鎖外釋放
                    threading.Thread(
                        target=lambda: self._free_model(old_model), daemon=True
                    ).start()
            self._model_name = model_name
            self._ttl_seconds = ttl_seconds

    def _free_model(self, model):
        """釋放模型資源"""
        del model
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    def acquire(self):
        """取得模型（如需要會延遲載入）"""
        need_load = False

        with self._lock:
            self._active_jobs += 1
            self._last_used = time.monotonic()

            if self._model is not None:
                return self._model

            if not self._loading:
                self._loading = True
                self._loaded_event.clear()
                need_load = True

        if need_load:
            try:
                import whisper  # 本地 import：避免在 GUI 執行緒初始化 torch/whisper
                model = whisper.load_model(self._model_name)
            except Exception:
                with self._lock:
                    self._loading = False
                    self._active_jobs = max(0, self._active_jobs - 1)
                    self._last_used = time.monotonic()
                    self._loaded_event.set()
                raise

            with self._lock:
                self._model = model
                self._loading = False
                self._last_used = time.monotonic()
                self._loaded_event.set()
                return self._model

        self._loaded_event.wait()

        with self._lock:
            if self._model is None:
                self._active_jobs = max(0, self._active_jobs - 1)
                self._last_used = time.monotonic()
                raise RuntimeError("Model loading failed or was cancelled.")
            return self._model

    def release(self):
        """釋放模型使用權"""
        with self._lock:
            self._active_jobs = max(0, self._active_jobs - 1)
            self._last_used = time.monotonic()

    def maybe_unload(self) -> bool:
        """如果閒置超過 TTL 則卸載模型（非阻塞）"""
        acquired = self._lock.acquire(blocking=False)
        if not acquired:
            return False

        model_to_free = None
        try:
            if self._model is None:
                return False
            if self._loading:
                return False

            idle_seconds = time.monotonic() - self._last_used
            if self._active_jobs == 0 and idle_seconds >= self._ttl_seconds:
                model_to_free = self._model
                self._model = None
        finally:
            self._lock.release()

        if model_to_free is not None:
            self._free_model(model_to_free)
            return True

        return False

    def force_unload(self) -> bool:
        """強制卸載模型"""
        with self._lock:
            if self._model is None:
                return False
            model_to_free = self._model
            self._model = None

        self._free_model(model_to_free)
        return True


class Worker(QObject):
    """背景工作執行緒的工作器"""
    progress = Signal(str)
    finished = Signal(str, str)
    error = Signal(str)

    def __init__(self, input_path: Path, output_dir: Path, model_manager):
        super().__init__()
        self.input_path = input_path
        self.output_dir = output_dir
        self.model_manager = model_manager

    @staticmethod
    def _format_srt_time(t: float) -> str:
        """將時間戳轉換為 SRT 格式"""
        h = int(t // 3600)
        m = int((t % 3600) // 60)
        s = int(t % 60)
        ms = int((t - int(t)) * 1000)
        return f"{h:02}:{m:02}:{s:02},{ms:03}"

    def run(self):
        """執行轉錄流程"""
        filename = self.input_path.stem

        try:
            self.progress.emit("Extracting audio...")
            audio_path = extract_audio(
                self.input_path,
                self.output_dir / filename,
                output_format="mp3",
            )

            self.progress.emit("Loading model & transcribing...")
            model = self.model_manager.acquire()
            try:
                result = model.transcribe(
                    str(audio_path),
                    task="transcribe",
                    verbose=False,
                )
            finally:
                self.model_manager.release()

            self.progress.emit("Writing outputs...")
            txt_path = self.output_dir / f"{filename}.txt"
            srt_path = self.output_dir / f"{filename}.srt"

            txt_path.write_text(result.get("text", ""), encoding="utf-8")

            segments = result.get("segments", []) or []
            srt_lines: list[str] = []
            for i, seg in enumerate(segments, 1):
                start = self._format_srt_time(float(seg["start"]))
                end = self._format_srt_time(float(seg["end"]))
                text = (seg.get("text") or "").strip()
                srt_lines.append(f"{i}\n{start} --> {end}\n{text}\n")

            srt_path.write_text("\n".join(srt_lines).strip() + "\n", encoding="utf-8")

            self.finished.emit(str(txt_path), str(srt_path))
        except Exception as exc:
            self.error.emit(str(exc))


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
    
    可調參數：
    - bar_width: 每條垂直條的粗細 (px)
    - bar_gap: 條之間的間距 (px)
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


class SettingsDialog(QWidget):
    """設定對話框"""
    settings_changed = Signal(dict)
    
    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.config = config.copy()
        self.setWindowTitle("Settings")
        
        # 設置為獨立視窗（彈出對話框）
        self.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint)
        self.setWindowModality(Qt.ApplicationModal)
        
        # 根據主題設置顏色
        theme = config.get("theme", "dark")
        if theme == "light":
            self.bg = "#ffffff"
            self.text = "#121417"
            self.border = "#c7ccd6"
            self.input_bg = "#f6f7fb"
            self.accent = "#2a2c30"
            self.hover = "#e8eaed"
        else:
            self.bg = "#1a1d23"
            self.text = "#e6e6e6"
            self.border = "#3b3f4a"
            self.input_bg = "#252931"
            self.accent = "#395191"
            self.hover = "#2a2f38"
        
        self._build_ui()
        self.adjustSize() # 強制初始化佈局並設置合適的大小
    
    def _build_ui(self):
        """構建 UI"""
        # 統一的現代化平面樣式
        self.setStyleSheet(f"""
            QWidget {{
                background: {self.bg};
                color: {self.text};
                font-size: 13px;
            }}
            QLabel, QComboBox, QPushButton {{
                background: {self.input_bg};
                border: 1px solid {self.border};
                border-radius: 6px;
                padding: 8px 12px;
            }}
            QLabel {{
                background: transparent;
                border: none;
                padding: 2px;
            }}
            QLabel#pathLabel {{
                background: {self.input_bg};
                border: 1px solid {self.border};
                padding: 10px 12px;
            }}
            QComboBox:hover, QPushButton:hover {{
                border-color: {self.accent};
                background: {self.hover};
            }}
            QPushButton:pressed {{
                background: {self.accent};
                color: #ffffff;
            }}
            QPushButton#primary {{
                background: {self.accent};
                color: #ffffff;
                font-weight: 600;
                border-color: {self.accent};
            }}
            QPushButton#primary:hover {{
                background: #4a6ab5;
            }}
            QComboBox::drop-down {{
                border: none;
                width: 0px;
            }}
            QComboBox QAbstractItemView {{
                background: {self.input_bg};
                border: 1px solid {self.border};
                selection-background-color: {self.accent};
            }}
        """)
        
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        
        # Theme
        theme_row = QHBoxLayout()
        theme_row.setSpacing(12)
        theme_label = QLabel("Theme")
        theme_label.setFixedWidth(140)
        self.theme_combo = self._create_combo(["dark", "light"], self.config["theme"])
        theme_row.addWidget(theme_label)
        theme_row.addWidget(self.theme_combo)
        layout.addLayout(theme_row)
        
        # Model
        model_row = QHBoxLayout()
        model_row.setSpacing(12)
        model_label = QLabel("Model")
        model_label.setFixedWidth(140)
        self.model_combo = self._create_combo(AVAILABLE_MODELS, self.config["model_name"])
        model_row.addWidget(model_label)
        model_row.addWidget(self.model_combo)
        layout.addLayout(model_row)
        
        # VRAM Release Time
        ttl_row = QHBoxLayout()
        ttl_row.setSpacing(12)
        ttl_label = QLabel("VRAM Release Time")
        ttl_label.setFixedWidth(140)
        ttl_value = self.config["model_ttl_seconds"]
        ttl_str = "Never" if ttl_value < 0 else str(ttl_value)
        self.ttl_combo = self._create_combo(
            ["30", "60", "120", "300", "600", "Never"],
            ttl_str
        )
        ttl_row.addWidget(ttl_label)
        ttl_row.addWidget(self.ttl_combo)
        layout.addLayout(ttl_row)
        
        # 分隔線
        line2 = QLabel()
        line2.setFixedHeight(1)
        line2.setStyleSheet(f"background: {self.border};")
        layout.addWidget(line2)
        
        # 輸出路徑
        output_row = QHBoxLayout()
        output_row.setSpacing(12)
        output_label = QLabel("Output Folder")
        output_label.setFixedWidth(140)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_output)

        output_row.addWidget(output_label)
        output_row.addWidget(browse_btn)

        layout.addLayout(output_row)
        
        self.output_path_label = QLabel(self.config["output_dir"])
        self.output_path_label.setObjectName("pathLabel")
        self.output_path_label.setWordWrap(True)
        layout.addWidget(self.output_path_label)
        
        layout.addStretch()
        
        # 按鈕
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedWidth(90)
        cancel_btn.clicked.connect(self.close)
        
        save_btn = QPushButton("Save")
        save_btn.setObjectName("primary")
        save_btn.setFixedWidth(90)
        save_btn.clicked.connect(self._save_settings)
        
        button_layout.addWidget(cancel_btn)
        button_layout.addStretch()
        button_layout.addWidget(save_btn)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)
    
    def _create_combo(self, items, current):
        """創建下拉選單"""
        combo = QComboBox()
        combo.addItems(items)
        combo.setCurrentText(str(current))
        return combo
    
    def _browse_output(self):
        """瀏覽輸出資料夾"""
        dir_path = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if dir_path:
            self.output_path_label.setText(dir_path)
    
    def _save_settings(self):
        """保存設定"""
        self.config["theme"] = self.theme_combo.currentText()
        self.config["model_name"] = self.model_combo.currentText()
        
        ttl_text = self.ttl_combo.currentText()
        self.config["model_ttl_seconds"] = -1 if ttl_text == "Never" else int(ttl_text)
        
        self.config["output_dir"] = self.output_path_label.text()
        
        self.settings_changed.emit(self.config)
        self.close()


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


class MainWindow(QWidget):
    """主視窗"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Whisper Transcription Tool")
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)

        # 載入配置
        self.config = load_config()
        self._pal = _get_palette(self.config["theme"])
        
        # 確保輸出目錄存在
        self.output_dir = Path(self.config["output_dir"])
        self.output_dir.mkdir(exist_ok=True)
        
        # 初始化模型管理器
        self.model_manager = ModelManager(
            self.config["model_name"],
            self.config["model_ttl_seconds"]
        )

        self._queue: list[Path] = []
        self._busy = False
        self._current_worker: Worker | None = None
        self._current_thread: threading.Thread | None = None

        # 狀態標籤
        self.status_label = QLabel("Ready")
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setObjectName("StatusLabel")

        # 波形指示器
        self.wave_indicator = WaveformBusyIndicator(
            accent=self._pal["accent"],
            bar_width=5,
            bar_gap=5,
            fps=30,
            speed=0.23,
        )

        # 拖放區域和忙碌區域
        self.drop_area = DropArea(self.handle_files, self._pal)
        self.busy_area = BusyArea(self._pal, self.wave_indicator, self.status_label)

        # 堆疊佈局切換兩個視圖
        self._stack = QStackedLayout()
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._stack.addWidget(self.drop_area)
        self._stack.addWidget(self.busy_area)

        stack_container = QWidget()
        stack_container.setLayout(self._stack)

        # 按鈕區域
        button_layout = QHBoxLayout()
        button_layout.setSpacing(8)
        
        # 設定按鈕
        self.settings_btn = QPushButton("Settings")
        self.settings_btn.clicked.connect(self._open_settings)
        
        # 錄音按鈕（預留）
        self.record_btn = QPushButton("Record")
        self.record_btn.clicked.connect(self._start_recording)
        self.record_btn.setEnabled(False)  # 暫時禁用
        self.record_btn.setToolTip("Coming soon")
        
        # 打開輸出資料夾按鈕
        self.open_folder_btn = QPushButton("Output Folder")
        self.open_folder_btn.clicked.connect(self._open_output_folder)

        button_layout.addWidget(self.record_btn)
        button_layout.addWidget(self.open_folder_btn)
        button_layout.addStretch()
        button_layout.addWidget(self.settings_btn)

        root = QVBoxLayout()
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        root.addWidget(stack_container)
        root.addLayout(button_layout)
        self.setLayout(root)

        # 閒置定時器：定期檢查是否可以卸載模型
        self._idle_timer = QTimer(self)
        self._idle_timer.setInterval(5_000)
        self._idle_timer.timeout.connect(self._maybe_unload_model)
        self._idle_timer.start()

        self._apply_theme()

    def _apply_theme(self):
        """應用主題樣式"""
        self.setStyleSheet(_build_stylesheet(self._pal))

    def _show_idle_view(self):
        """顯示閒置視圖（拖放區域）"""
        self._stack.setCurrentIndex(0)

    def _show_busy_view(self):
        """顯示忙碌視圖（波形動畫）"""
        self._stack.setCurrentIndex(1)

    def _open_settings(self):
        """打開設定對話框"""
        dialog = SettingsDialog(self.config, self)
        dialog.settings_changed.connect(self._apply_settings)
        dialog.show()

    def _apply_settings(self, new_config: dict):
        """應用新設定並重繪 GUI"""
        old_theme = self.config["theme"]
        self.config = new_config
        save_config(new_config)
        
        # 更新輸出目錄
        self.output_dir = Path(self.config["output_dir"])
        self.output_dir.mkdir(exist_ok=True)
        
        # 更新模型管理器配置
        self.model_manager.update_config(
            self.config["model_name"],
            self.config["model_ttl_seconds"]
        )
        
        # 如果主題改變，重新創建整個 GUI
        if old_theme != self.config["theme"]:
            self._rebuild_gui()
    
    def _rebuild_gui(self):
        """重新構建整個 GUI（用於主題切換）"""
        # 保存當前狀態
        was_busy = self._busy
        current_queue = self._queue.copy()
        
        # 更新調色板
        self._pal = _get_palette(self.config["theme"])
        
        # 重新應用主題樣式
        self._apply_theme()
        
        # 更新波形指示器顏色
        self.wave_indicator.set_color(self._pal["accent"])
        
        # 重新創建面板以更新顏色
        old_drop = self.drop_area
        old_busy = self.busy_area
        
        self.drop_area = DropArea(self.handle_files, self._pal)
        self.busy_area = BusyArea(self._pal, self.wave_indicator, self.status_label)
        
        # 更新堆疊佈局
        self._stack.removeWidget(old_drop)
        self._stack.removeWidget(old_busy)
        self._stack.insertWidget(0, self.drop_area)
        self._stack.insertWidget(1, self.busy_area)
        
        # 刪除舊組件
        old_drop.deleteLater()
        old_busy.deleteLater()
        
        # 恢復視圖狀態
        if was_busy:
            self._show_busy_view()
        else:
            self._show_idle_view()
        
        # 恢復隊列
        self._queue = current_queue

    def _start_recording(self):
        """開始錄音（預留功能）"""
        QMessageBox.information(self, "Coming Soon", "Recording feature is under development.")

    def _open_output_folder(self):
        """打開輸出資料夾"""
        output_path = str(self.output_dir.resolve())
        
        if sys.platform == "win32":
            os.startfile(output_path)
        elif sys.platform == "darwin":
            subprocess.run(["open", output_path])
        else:
            subprocess.run(["xdg-open", output_path])

    def handle_files(self, files: list[str]):
        """處理拖放的檔案（只在閒置狀態接受）"""
        added = 0
        invalid_files = []
        
        for raw in files:
            path = Path(raw)
            if not path.exists():
                invalid_files.append(path.name)
                continue
            self._queue.append(path)
            added += 1

        if invalid_files:
            self._show_error(f"File not found:\n" + "\n".join(invalid_files))
        
        if added > 0:
            self._start_next_if_idle()

    def _start_next_if_idle(self):
        """如果閒置則開始處理下一個檔案"""
        if self._busy:
            return
        if not self._queue:
            self._show_idle_view()
            self.status_label.setText("Ready")
            return

        input_path = self._queue.pop(0)
        self._busy = True
        self._show_busy_view()
        self.status_label.setText(f"Processing: {input_path.name}")

        worker = Worker(input_path, self.output_dir, self.model_manager)
        worker.progress.connect(self._on_worker_progress)
        worker.finished.connect(self._on_worker_finished)
        worker.error.connect(self._on_worker_error)

        thread = threading.Thread(target=worker.run, daemon=True)
        self._current_worker = worker
        self._current_thread = thread
        thread.start()

    def _on_worker_progress(self, message: str):
        """工作器進度更新"""
        self.status_label.setText(message)

    def _on_worker_finished(self, txt_path: str, srt_path: str):
        """工作器完成"""
        self.status_label.setText("Complete")
        self._busy = False
        self._current_worker = None
        self._current_thread = None

        if self._queue:
            self._start_next_if_idle()
        else:
            self._show_idle_view()

    def _on_worker_error(self, message: str):
        """工作器錯誤"""
        self._show_error(f"Processing failed:\n{message}")
        self._busy = False
        self._current_worker = None
        self._current_thread = None

        if self._queue:
            self._start_next_if_idle()
        else:
            self._show_idle_view()
            self.status_label.setText("Ready")

    def _maybe_unload_model(self):
        """定期檢查是否可以卸載模型以釋放 VRAM"""
        if not self._busy and not self._queue:
            # 檢查是否設定為 Never (-1)
            if self.config["model_ttl_seconds"] >= 0:
                self.model_manager.maybe_unload()

    def _show_error(self, message: str):
        """顯示錯誤訊息（平面風格）"""
        QMessageBox.critical(self, "Error", message)

    def closeEvent(self, event):
        """視窗關閉事件：強制卸載模型"""
        self.model_manager.force_unload()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication([])
    win = MainWindow()
    win.show()
    app.exec()