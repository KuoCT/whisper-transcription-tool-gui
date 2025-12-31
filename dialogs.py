from __future__ import annotations
import threading
from pathlib import Path
from PySide6.QtCore import QObject, Qt, Signal, QEvent
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app_config import DEFAULT_CONFIG
from language_utils import format_language_hint, is_auto_language_hint, parse_language_hint
from style import (
    build_settings_dialog_stylesheet,
    build_transcript_popup_stylesheet,
    get_palette,
)


AVAILABLE_MODELS = ["tiny", "base", "small", "medium", "large", "turbo"]
DEVICE_CHOICES = ["auto", "cuda", "cpu"]
COMPUTE_CHOICES = ["auto", "float16", "int8_float16", "int8", "float32"]


class ModelDownloadWorker(QObject):
    """模型下載工作者（背景執行）。"""

    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, model_id: str, cache_dir: Path) -> None:
        super().__init__()
        self.model_id = (model_id or "").strip()
        self.cache_dir = cache_dir

    def run(self) -> None:
        try:
            from model_manager import download_model_snapshot

            download_model_snapshot(self.model_id, self.cache_dir)
            self.finished.emit(self.model_id)
        except Exception as exc:
            message = str(exc).strip() or exc.__class__.__name__
            self.failed.emit(message)


class TranscriptPopupDialog(QDialog):
    """轉譯結果 Pop-up（可編輯 + 縮放按鈕 + Copy 按鈕）"""

    def __init__(self, title: str, text: str, theme: str = "dark", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint)
        self.setMinimumSize(500, 400)

        # 由 style.py 統一管理顏色與 QSS，避免 dialogs.py 出現大量風格代碼
        pal = get_palette(theme)
        self.setStyleSheet(build_transcript_popup_stylesheet(pal))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(False)  # 允許編輯
        self.text_edit.setAcceptRichText(False)  # 只接受純文字（避免貼上 rich text 造成字體不一致）
        self.text_edit.setPlainText(text or "")
        
        # 啟用滾動條（預設就是啟用的，但明確設置以確保）
        self.text_edit.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.text_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        # 記錄初始字體大小（QSS 可能會影響實際顯示字體大小）
        # - 若 pointSize <= 0（例如只被 px QSS 控制），就退回 12
        self._base_font_size = self.text_edit.font().pointSize() or 12
        self._current_font_size = int(self._base_font_size)
        self._apply_font_size(self._current_font_size)

        # 支援 Ctrl + 滾輪縮放字體：用 eventFilter 避免改到其他滾動行為
        self.text_edit.installEventFilter(self)
        
        layout.addWidget(self.text_edit, 1)

        # 按鈕列：縮放按鈕在左側，Close/Copy 在右側
        row = QHBoxLayout()
        row.setSpacing(8)
        
        # 取得 asset 目錄路徑
        from pathlib import Path
        asset_dir = Path(__file__).resolve().parent / "asset"

        # Zoom In 按鈕（放大）
        self.btn_zoom_in = self._make_icon_button(
            icon_path=asset_dir / "add.png",
            tooltip="Zoom In",
            fallback_text="+"
        )
        self.btn_zoom_in.clicked.connect(self._zoom_in)
        
        # Zoom Out 按鈕（縮小）
        self.btn_zoom_out = self._make_icon_button(
            icon_path=asset_dir / "sub.png",
            tooltip="Zoom Out",
            fallback_text="-"
        )
        self.btn_zoom_out.clicked.connect(self._zoom_out)
        
        row.addWidget(self.btn_zoom_out)
        row.addWidget(self.btn_zoom_in)
        row.addStretch(1)

        self.btn_copy = QPushButton("Copy")
        self.btn_copy.setObjectName("primary")
        self.btn_copy.setFixedWidth(90)
        self.btn_copy.setFocusPolicy(Qt.NoFocus)  # Copy 按鈕不要搶焦點
        self.btn_copy.clicked.connect(self._copy_all)

        self.btn_close = QPushButton("Close")
        self.btn_close.setFixedWidth(90)
        self.btn_close.clicked.connect(self.close)

        row.addWidget(self.btn_close)
        row.addWidget(self.btn_copy)
        layout.addLayout(row)

        # 讓 Zoom 按鈕與 Copy/Close 等高（square button），提升對齊與一致性
        self._sync_zoom_button_size()

    def _make_icon_button(
        self,
        icon_path,
        tooltip: str,
        fallback_text: str = "",
    ) -> QPushButton:
        """建立純圖示按鈕（統一尺寸與行為）。
        
        外觀（背景透明/外框/hover）由 style.py 的 QPushButton#IconButton 統一控制。
        """
        from pathlib import Path
        from PySide6.QtGui import QIcon
        from PySide6.QtCore import QSize
        
        btn = QPushButton("")
        btn.setObjectName("IconButton")
        btn.setToolTip(tooltip)
        # 實際尺寸會在 _sync_zoom_button_size() 統一調整
        btn.setFixedSize(28, 28)
        btn.setIconSize(QSize(20, 20))
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setAutoDefault(False)
        btn.setCursor(Qt.PointingHandCursor)
        
        # 載入圖示
        icon_path = Path(icon_path)
        if icon_path.exists():
            btn.setText("")
            btn.setIcon(QIcon(str(icon_path)))
            btn.setIconSize(QSize(20, 20))
        else:
            # 若沒有圖示檔案，先用字母代替，避免 UI 空白
            btn.setIcon(QIcon())
            btn.setText(fallback_text)
        
        return btn

    # -------------------------------------------------------------------------
    # Font scaling
    # -------------------------------------------------------------------------

    def showEvent(self, event) -> None:  # noqa: N802
        """視窗顯示後再同步一次按鈕尺寸，避免平台/DPI 差異造成高度不一致。"""
        super().showEvent(event)
        self._sync_zoom_button_size()

    def eventFilter(self, obj, event):  # noqa: N802
        """攔截 QTextEdit 的 Ctrl+Wheel，做字體縮放。"""
        if obj is self.text_edit and event.type() == QEvent.Wheel:
            # Ctrl + 滾輪：縮放；一般滾輪：維持正常捲動
            if event.modifiers() & Qt.ControlModifier:
                delta_y = event.angleDelta().y()
                if delta_y > 0:
                    self._zoom_in()
                elif delta_y < 0:
                    self._zoom_out()
                return True

        return super().eventFilter(obj, event)

    def _zoom_in(self):
        """放大文字"""
        self._current_font_size = min(self._current_font_size + 1, 32)  # 最大 32
        self._apply_font_size(self._current_font_size)

    def _zoom_out(self):
        """縮小文字"""
        self._current_font_size = max(self._current_font_size - 1, 8)  # 最小 8
        self._apply_font_size(self._current_font_size)

    def _apply_font_size(self, point_size: int) -> None:
        """套用字體大小到整份文件（確保「已存在文字」也會跟著變）。

        為什麼不用 QTextEdit.setFont()？
        - setFont() 主要影響「之後輸入的文字」與預設字型。
        - 若文件內容已有既定格式（例如先 setText() 造成的格式），可能看起來「沒反應」。
        - 這裡用 QTextCursor 選取整份文件後 mergeCharFormat，確保可見效果一致。
        """
        from PySide6.QtGui import QTextCharFormat, QTextCursor

        size = int(point_size)
        if size <= 0:
            return

        # 保留游標/選取範圍，避免縮放後使用者編輯位置跳走
        old_cursor = self.text_edit.textCursor()
        old_pos = old_cursor.position()
        old_anchor = old_cursor.anchor()

        doc = self.text_edit.document()

        # 1) 設定文件預設字體（影響後續輸入）
        base_font = doc.defaultFont()
        base_font.setPointSize(size)
        doc.setDefaultFont(base_font)

        # 2) 強制套用到目前文件全部文字（影響已存在內容）
        cursor = QTextCursor(doc)
        cursor.select(QTextCursor.Document)
        fmt = QTextCharFormat()
        fmt.setFontPointSize(size)
        cursor.mergeCharFormat(fmt)

        # 3) 還原游標/選取
        restored = self.text_edit.textCursor()
        restored.setPosition(old_anchor)
        if old_pos != old_anchor:
            restored.setPosition(old_pos, QTextCursor.KeepAnchor)
        else:
            restored.setPosition(old_pos, QTextCursor.MoveAnchor)
        self.text_edit.setTextCursor(restored)

    def _sync_zoom_button_size(self) -> None:
        """讓 Zoom 按鈕與 Copy/Close 等高，並同步 icon size。"""
        from PySide6.QtCore import QSize

        # sizeHint 會受 QSS 影響，取最大值確保一致
        target_h = max(self.btn_copy.sizeHint().height(), self.btn_close.sizeHint().height())
        if target_h <= 0:
            target_h = 34

        # Zoom 按鈕做成方形，視覺上會更像工具按鈕
        self.btn_zoom_in.setFixedSize(target_h, target_h)
        self.btn_zoom_out.setFixedSize(target_h, target_h)

        # icon 留一點 padding
        icon_side = max(16, int(target_h * 0.58))
        self.btn_zoom_in.setIconSize(QSize(icon_side, icon_side))
        self.btn_zoom_out.setIconSize(QSize(icon_side, icon_side))

    def _copy_all(self) -> None:
        """全選複製

        備註：
        - 在 Qt 中，剪貼簿要由 GUI thread 操作
        """
        from PySide6.QtWidgets import QApplication

        # 全選 + 反白 + 複製
        self.text_edit.setFocus(Qt.OtherFocusReason)  # 確保反白顯示
        self.text_edit.selectAll()                    # 反白（全選）
        QApplication.clipboard().setText(self.text_edit.toPlainText())


class SettingsDialog(QWidget):
    """設定對話框"""

    settings_changed = Signal(dict)

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        self._model_cache_dir = Path(__file__).resolve().parent / "cache" / "whisper"
        self._download_busy = False
        raw_custom_models = [m for m in (self.config.get("custom_models") or []) if m]
        self._custom_models = self._filter_cached_custom_models(raw_custom_models)
        self.setWindowTitle("Settings")

        # 設置為獨立視窗（彈出對話框）
        self.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint)
        self.setWindowModality(Qt.ApplicationModal)

        theme = self.config.get("theme", "dark")
        pal = get_palette(theme)
        self.setStyleSheet(build_settings_dialog_stylesheet(pal))

        self._build_ui()
        self.adjustSize()

    @staticmethod
    def _resolve_language_hint(user_input: str) -> str:
        """匹配語言提示(e.g. en/english)"""
        codes = parse_language_hint(user_input)
        return format_language_hint(codes)

    def _filter_cached_custom_models(self, model_ids: list[str]) -> list[str]:
        """開啟設定時同步清理已被刪除的自訂模型。"""
        filtered: list[str] = []
        for model_id in model_ids:
            if self._is_model_cached(model_id):
                filtered.append(model_id)
        return filtered

    def _build_ui(self) -> None:
        """構建 UI"""
        layout = QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # 主題
        theme_row = QHBoxLayout()
        theme_row.setSpacing(12)
        theme_label = QLabel("Theme")
        theme_label.setFixedWidth(140)
        self.theme_combo = self._create_combo(["dark", "light"], self.config["theme"])
        theme_row.addWidget(theme_label)
        theme_row.addWidget(self.theme_combo)
        layout.addLayout(theme_row)

        # 模型選擇
        model_row = QHBoxLayout()
        model_row.setSpacing(12)
        model_label = QLabel("Model")
        model_label.setFixedWidth(140)
        current_model = (self.config.get("model_name") or "").strip()
        custom_models = list(self._custom_models)
        if current_model and current_model not in AVAILABLE_MODELS and current_model not in custom_models:
            if self._is_model_cached(current_model):
                custom_models.append(current_model)
        self._custom_models = custom_models
        model_items = AVAILABLE_MODELS + [m for m in custom_models if m not in AVAILABLE_MODELS]
        base_model = current_model if current_model in model_items else (model_items[0] if model_items else "")
        self._current_model_name = current_model
        self.model_combo = self._create_combo(model_items, base_model)
        self.model_download_btn = QPushButton("Download")
        self.model_download_btn.setObjectName("DownloadButton")
        self.model_download_btn.clicked.connect(self._download_selected_model)
        model_row.addWidget(model_label)
        model_row.addWidget(self.model_combo)
        model_row.addWidget(self.model_download_btn)
        layout.addLayout(model_row)
        self.model_combo.currentTextChanged.connect(self._sync_model_download_state)
        self._sync_model_download_state()

        # 語言提示
        lang_row = QHBoxLayout()
        lang_row.setSpacing(12)
        lang_label = QLabel("Language")
        lang_label.setFixedWidth(140)
        self.lang_input = QLineEdit()
        self.lang_input.setPlaceholderText("auto-detect (e.g. en, zh)")
        self.lang_input.setText(self.config.get("language_hint", "") or "")
        lang_row.addWidget(lang_label)
        lang_row.addWidget(self.lang_input)
        layout.addLayout(lang_row)

        # 麥克風（輸入裝置）
        mic_row = QHBoxLayout()
        mic_row.setSpacing(12)
        mic_label = QLabel("Input Microphone")
        mic_label.setFixedWidth(140)

        self.mic_combo = QComboBox()

        self.mic_combo.setMinimumContentsLength(30)  # 顯示大約 n 個字寬
        self.mic_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)

        # 延遲 import：避免在沒有 sounddevice 的環境讓 Settings 無法開啟
        try:
            from recorder import list_input_devices
            devices = list_input_devices()
        except Exception:
            devices = []

        if not devices:
            # 退化：至少提供 System Default，讓功能不至於整個消失
            self.mic_combo.addItem("System Default", -1)
        else:
            for dev in devices:
                label = dev.name
                if dev.is_default and dev.device_id != -1:
                    label = f"{label} (default)"
                self.mic_combo.addItem(label, dev.device_id)

        current_device = int(self.config.get("input_device", -1))
        idx = self.mic_combo.findData(current_device)
        if idx >= 0:
            self.mic_combo.setCurrentIndex(idx)
        else:
            # 若配置值已不存在，退回 System Default
            idx2 = self.mic_combo.findData(-1)
            if idx2 >= 0:
                self.mic_combo.setCurrentIndex(idx2)

        mic_row.addWidget(mic_label)
        mic_row.addWidget(self.mic_combo)
        layout.addLayout(mic_row)

        # VRAM Release 時間設定
        ttl_row = QHBoxLayout()
        ttl_row.setSpacing(12)
        ttl_label = QLabel("VRAM Release Time")
        ttl_label.setFixedWidth(140)
        ttl_value = self.config["model_ttl_seconds"]
        ttl_str = "Never" if ttl_value < 0 else str(ttl_value)
        self.ttl_combo = self._create_combo(
            ["60", "120", "180", "300", "600", "Never"],
            ttl_str,
        )
        ttl_row.addWidget(ttl_label)
        ttl_row.addWidget(self.ttl_combo)
        layout.addLayout(ttl_row)

        # Auto Cache in RAM（可視情況保留 CPU 模型，加速喚醒）
        cache_row = QHBoxLayout()
        cache_row.setSpacing(12)
        cache_label = QLabel("Auto Cache in RAM")
        cache_label.setFixedWidth(140)

        self.ck_model_cache = QCheckBox("Enable")
        self.ck_model_cache.setChecked(bool(self.config.get("model_cache_in_ram", True)))

        cache_row.addWidget(cache_label)
        cache_row.addWidget(self.ck_model_cache)
        cache_row.addStretch(1)
        layout.addLayout(cache_row)

        # 分隔線
        line_adv = QLabel()
        line_adv.setObjectName("separatorLine")
        line_adv.setFixedHeight(1)
        layout.addWidget(line_adv)

        # Advanced settings（按鈕展開）
        adv_row = QHBoxLayout()
        adv_row.setSpacing(12)
        adv_label = QLabel("Advanced")
        adv_label.setFixedWidth(140)
        self.adv_toggle = QPushButton("Show")
        self.adv_toggle.setCheckable(True)
        self.adv_toggle.toggled.connect(self._toggle_advanced)
        adv_row.addWidget(adv_label)
        adv_row.addWidget(self.adv_toggle)
        adv_row.addStretch(1)
        layout.addLayout(adv_row)

        self.adv_container = QWidget()
        adv_layout = QVBoxLayout(self.adv_container)
        adv_layout.setContentsMargins(0, 0, 0, 0)
        adv_layout.setSpacing(8)
        self.adv_container.setVisible(False)

        # Custom Model
        custom_row = QHBoxLayout()
        custom_row.setSpacing(12)
        custom_label = QLabel("Custom Model")
        custom_label.setFixedWidth(140)
        self.custom_model_input = QLineEdit()
        self.custom_model_input.setPlaceholderText("Custom model (e.g. Systran/faster-whisper-large-v3)")
        custom_value = ""
        if self._current_model_name and self._current_model_name not in AVAILABLE_MODELS:
            custom_value = self._current_model_name
        self.custom_model_input.setText(custom_value)
        self.custom_download_btn = QPushButton("Download")
        self.custom_download_btn.setObjectName("DownloadButton")
        self.custom_download_btn.clicked.connect(self._download_custom_model)
        custom_row.addWidget(custom_label)
        custom_row.addWidget(self.custom_model_input)
        custom_row.addWidget(self.custom_download_btn)
        adv_layout.addLayout(custom_row)
        self.custom_model_input.textChanged.connect(self._sync_custom_download_state)
        self._sync_custom_download_state()

        # Device
        device_row = QHBoxLayout()
        device_row.setSpacing(12)
        device_label = QLabel("Device")
        device_label.setFixedWidth(140)
        self.device_combo = self._create_combo(
            DEVICE_CHOICES,
            self.config.get("fw_device", "auto"),
        )
        device_row.addWidget(device_label)
        device_row.addWidget(self.device_combo)
        adv_layout.addLayout(device_row)

        # Compute Type
        compute_row = QHBoxLayout()
        compute_row.setSpacing(12)
        compute_label = QLabel("Compute Type")
        compute_label.setFixedWidth(140)
        self.compute_combo = self._create_combo(
            COMPUTE_CHOICES,
            self.config.get("fw_compute_type", "auto"),
        )
        compute_row.addWidget(compute_label)
        compute_row.addWidget(self.compute_combo)
        adv_layout.addLayout(compute_row)

        # Batch Size
        batch_row = QHBoxLayout()
        batch_row.setSpacing(12)
        batch_label = QLabel("Batch Size")
        batch_label.setFixedWidth(140)
        self.batch_input = QLineEdit()
        self.batch_input.setValidator(QIntValidator(1, 256))
        self.batch_input.setText(str(self.config.get("fw_batch_size", 8)))
        batch_row.addWidget(batch_label)
        batch_row.addWidget(self.batch_input)
        adv_layout.addLayout(batch_row)

        # Beam Size
        beam_row = QHBoxLayout()
        beam_row.setSpacing(12)
        beam_label = QLabel("Beam Size")
        beam_label.setFixedWidth(140)
        self.beam_input = QLineEdit()
        self.beam_input.setValidator(QIntValidator(1, 10))
        self.beam_input.setText(str(self.config.get("fw_beam_size", 5)))
        beam_row.addWidget(beam_label)
        beam_row.addWidget(self.beam_input)
        adv_layout.addLayout(beam_row)

        # VAD Filter
        vad_row = QHBoxLayout()
        vad_row.setSpacing(12)
        vad_label = QLabel("VAD Filter")
        vad_label.setFixedWidth(140)
        self.ck_vad_filter = QCheckBox("Enable")
        self.ck_vad_filter.setChecked(bool(self.config.get("fw_vad_filter", False)))
        vad_row.addWidget(vad_label)
        vad_row.addWidget(self.ck_vad_filter)
        vad_row.addStretch(1)
        adv_layout.addLayout(vad_row)

        # CUDA 檢查
        cuda_row = QHBoxLayout()
        cuda_row.setSpacing(12)
        cuda_label = QLabel("Check CUDA on Start")
        cuda_label.setFixedWidth(140)
        self.ck_cuda_check = QCheckBox("Enable")
        self.ck_cuda_check.setChecked(bool(self.config.get("cuda_check_enabled", True)))
        cuda_row.addWidget(cuda_label)
        cuda_row.addWidget(self.ck_cuda_check)
        cuda_row.addStretch(1)
        adv_layout.addLayout(cuda_row)

        layout.addWidget(self.adv_container)

        # 分隔線（樣式由 QSS 統一控制）
        line = QLabel()
        line.setObjectName("separatorLine")
        line.setFixedHeight(1)
        layout.addWidget(line)

        # 輸出選項（可多選，但至少要選 1 個）
        out_title_row = QHBoxLayout()
        out_title_row.setSpacing(12)
        out_label = QLabel("Output")
        out_label.setFixedWidth(140)

        self.ck_popup = QCheckBox("Pop-up")
        self.ck_clipboard = QCheckBox("Clipboard")
        self.ck_txt = QCheckBox(".txt")
        self.ck_srt = QCheckBox(".srt")
        self.ck_smart_format = QCheckBox("Smart Format")

        self.ck_popup.setChecked(bool(self.config.get("output_popup", False)))
        self.ck_clipboard.setChecked(bool(self.config.get("output_clipboard", False)))
        self.ck_txt.setChecked(bool(self.config.get("output_txt", True)))
        self.ck_srt.setChecked(bool(self.config.get("output_srt", True)))
        self.ck_smart_format.setChecked(bool(self.config.get("output_smart_format", True)))

        out_title_row.addWidget(out_label)
        out_title_row.addWidget(self.ck_popup)
        out_title_row.addWidget(self.ck_clipboard)
        out_title_row.addWidget(self.ck_txt)
        out_title_row.addWidget(self.ck_srt)
        out_title_row.addStretch(1)
        layout.addLayout(out_title_row)

        format_row = QHBoxLayout()
        format_row.setSpacing(12)

        format_label = QLabel("Formatting")
        format_label.setFixedWidth(140)

        format_row.addWidget(format_label)
        format_row.addWidget(self.ck_smart_format)
        format_row.addStretch(1)
        layout.addLayout(format_row)

        # 分隔線
        line2 = QLabel()
        line2.setObjectName("separatorLine")
        line2.setFixedHeight(1)
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
        self._sync_download_button_size()

    def _resolve_download_model_id(self, model_id: str) -> str:
        """整理模型 ID（去除空白）。"""
        return (model_id or "").strip()

    def _is_model_cached(self, model_id: str) -> bool:
        """檢查模型是否已快取。"""
        model_id = (model_id or "").strip()
        if not model_id:
            return False
        if not self._model_cache_dir.exists():
            return False
        try:
            from faster_whisper.utils import download_model

            download_model(
                model_id,
                cache_dir=str(self._model_cache_dir),
                local_files_only=True,
            )
            return True
        except Exception:
            return False

    def _add_custom_model(self, model_id: str) -> None:
        """新增自訂模型到清單。"""
        model_id = (model_id or "").strip()
        if not model_id:
            return
        if model_id in AVAILABLE_MODELS or model_id in self._custom_models:
            return
        self._custom_models.append(model_id)
        if hasattr(self, "model_combo"):
            self.model_combo.addItem(model_id)

    def _sync_model_download_state(self) -> None:
        """同步預設模型下載按鈕狀態。"""
        if not hasattr(self, "model_download_btn"):
            return
        if self._download_busy:
            self.model_download_btn.setEnabled(False)
            return
        model_id = self.model_combo.currentText().strip()
        cached = self._is_model_cached(model_id)
        self.model_download_btn.setEnabled(bool(model_id) and not cached)

    def _sync_custom_download_state(self) -> None:
        """同步自訂模型下載按鈕狀態。"""
        if not hasattr(self, "custom_download_btn") or not hasattr(self, "custom_model_input"):
            return
        if self._download_busy:
            self.custom_download_btn.setEnabled(False)
            return
        model_id = (self.custom_model_input.text() or "").strip()
        cached = self._is_model_cached(model_id)
        if cached:
            self._add_custom_model(model_id)
        self.custom_download_btn.setEnabled(bool(model_id) and not cached)

    @staticmethod
    def _tune_busy_progress_dialog(progress: QProgressDialog) -> None:
        """調整忙碌進度條的置中與顯示。"""
        bar = progress.findChild(QProgressBar)
        if bar is None:
            return
        bar.setTextVisible(False)
        layout = progress.layout()
        if layout is not None:
            layout.setAlignment(bar, Qt.AlignHCenter)

    def _start_model_download(self, model_id: str, *, is_custom: bool) -> None:
        """啟動模型下載流程。"""
        model_id = self._resolve_download_model_id(model_id)
        if not model_id:
            return
        if self._download_busy:
            return

        if self._is_model_cached(model_id):
            self._sync_model_download_state()
            self._sync_custom_download_state()
            return

        self._download_busy = True
        self._sync_model_download_state()
        self._sync_custom_download_state()

        progress = QProgressDialog(f"Downloading model: {model_id}", "", 0, 0, self)
        progress.setWindowTitle("Please wait")
        progress.setWindowModality(Qt.ApplicationModal)
        progress.setCancelButton(None)
        progress.show()
        self._tune_busy_progress_dialog(progress)

        self._download_worker = ModelDownloadWorker(model_id, self._model_cache_dir)

        def _done(model_name: str) -> None:
            progress.close()
            self._download_busy = False
            if is_custom:
                self._add_custom_model(model_name)
                QMessageBox.information(
                    self,
                    "Download",
                    "Custom model downloaded. Select it from the Model list to use it.",
                )
            else:
                QMessageBox.information(self, "Download", "Model downloaded successfully.")
            self._sync_model_download_state()
            self._sync_custom_download_state()

        def _fail(msg: str) -> None:
            progress.close()
            self._download_busy = False
            self._sync_model_download_state()
            self._sync_custom_download_state()
            QMessageBox.critical(self, "Download failed", msg)

        self._download_worker.finished.connect(_done)
        self._download_worker.failed.connect(_fail)
        threading.Thread(target=self._download_worker.run, daemon=True).start()

    def _download_selected_model(self) -> None:
        """下載目前選擇的模型。"""
        model_id = self.model_combo.currentText().strip()
        if not model_id:
            return
        self._start_model_download(model_id, is_custom=False)

    def _download_custom_model(self) -> None:
        """下載自訂模型。"""
        model_id = (self.custom_model_input.text() or "").strip()
        if not model_id:
            QMessageBox.warning(self, "Custom Model", "Please enter a model ID first.")
            return
        self._start_model_download(model_id, is_custom=True)

    def _toggle_advanced(self, checked: bool) -> None:
        """展開/收合進階設定區塊。"""
        checked = bool(checked)
        if hasattr(self, "adv_container"):
            self.adv_container.setVisible(checked)
        if hasattr(self, "adv_toggle"):
            self.adv_toggle.setText("Hide" if checked else "Show")
        self.adjustSize()

    def _sync_download_button_size(self) -> None:
        """同步兩個下載按鈕尺寸，避免顯示不一致。"""
        if not hasattr(self, "model_download_btn") or not hasattr(self, "custom_download_btn"):
            return
        model_hint = self.model_download_btn.sizeHint()
        custom_hint = self.custom_download_btn.sizeHint()
        target_w = max(model_hint.width(), custom_hint.width())
        target_h = max(model_hint.height(), custom_hint.height())
        if target_w <= 0:
            target_w = 92
        if target_h <= 0:
            target_h = 28
        self.model_download_btn.setFixedSize(target_w, target_h)
        self.custom_download_btn.setFixedSize(target_w, target_h)

    def _create_combo(self, items, current):
        """創建下拉選單"""
        combo = QComboBox()
        combo.addItems(items)
        combo.setCurrentText(str(current))
        return combo

    def _browse_output(self) -> None:
        """瀏覽輸出資料夾"""
        dir_path = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if dir_path:
            self.output_path_label.setText(dir_path)

    def _save_settings(self) -> None:
        """保存設定"""
        self.config["theme"] = self.theme_combo.currentText()
        model_name = self.model_combo.currentText().strip()
        self.config["model_name"] = model_name

        self.config["custom_models"] = list(self._custom_models)

        # 語言提示：空白=自動偵測；指定語言可略過前 30 秒語言偵測
        raw_lang = (self.lang_input.text() or "").strip() if hasattr(self, "lang_input") else ""
        resolved_lang = self._resolve_language_hint(raw_lang)
        if raw_lang and not resolved_lang and not is_auto_language_hint(raw_lang):
            QMessageBox.warning(
                self,
                "Language",
                "Unsupported language. Using auto-detect.",
            )
            if hasattr(self, "lang_input"):
                self.lang_input.setText("")
        self.config["language_hint"] = resolved_lang

        # 麥克風輸入裝置（-1 = System Default）
        if hasattr(self, "mic_combo"):
            try:
                self.config["input_device"] = int(self.mic_combo.currentData())
            except Exception:
                self.config["input_device"] = -1

        ttl_text = self.ttl_combo.currentText()
        self.config["model_ttl_seconds"] = -1 if ttl_text == "Never" else int(ttl_text)
        self.config["model_cache_in_ram"] = bool(self.ck_model_cache.isChecked())
        self.config["fw_device"] = self.device_combo.currentText()
        self.config["fw_compute_type"] = self.compute_combo.currentText()

        batch_text = (self.batch_input.text() or "").strip()
        self.config["fw_batch_size"] = int(batch_text) if batch_text.isdigit() else 8

        beam_text = (self.beam_input.text() or "").strip()
        self.config["fw_beam_size"] = int(beam_text) if beam_text.isdigit() else 5

        self.config["fw_vad_filter"] = bool(self.ck_vad_filter.isChecked())
        self.config["cuda_check_enabled"] = bool(self.ck_cuda_check.isChecked())

        # 輸出選項（至少選一個）
        self.config["output_popup"] = bool(self.ck_popup.isChecked())
        self.config["output_clipboard"] = bool(self.ck_clipboard.isChecked())
        self.config["output_txt"] = bool(self.ck_txt.isChecked())
        self.config["output_srt"] = bool(self.ck_srt.isChecked())
        self.config["output_smart_format"] = bool(self.ck_smart_format.isChecked())

        if not any([
            self.config["output_popup"],
            self.config["output_clipboard"],
            self.config["output_txt"],
            self.config["output_srt"],
        ]):
            QMessageBox.warning(
                self,
                "Output",
                "Please select at least one output option.",
            )
            return

        self.config["output_dir"] = self.output_path_label.text()

        # 如果需要輸出檔案但沒有資料夾，提醒一下
        if (self.config["output_txt"] or self.config["output_srt"]) and not self.config["output_dir"].strip():
            QMessageBox.warning(
                self,
                "Output Folder",
                "Output folder is empty. Please select a folder.",
            )
            return

        self.settings_changed.emit(self.config)
        self.close()
