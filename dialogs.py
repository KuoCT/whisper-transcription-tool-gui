from __future__ import annotations
from PySide6.QtCore import Qt, Signal, QEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app_config import DEFAULT_CONFIG
from style import (
    build_settings_dialog_stylesheet,
    build_transcript_popup_stylesheet,
    get_palette,
)


AVAILABLE_MODELS = ["tiny", "base", "small", "medium", "large", "turbo"]


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
        """解析語言輸入（支持 en / english），無效則回傳空字串表示自動偵測"""
        raw = (user_input or "").strip()
        if not raw:
            return ""

        norm = " ".join(raw.lower().replace("_", " ").replace("-", " ").split())

        try:
            # 本地 import：避免在沒有 whisper 時造成啟動失敗
            from whisper.tokenizer import LANGUAGES
        except Exception:
            return ""

        # 直接匹配代碼（例如 en / zh）
        if norm in LANGUAGES:
            return norm

        # 匹配完整語言名稱（例如 english / chinese）
        name_to_code = {
            " ".join(v.lower().replace("_", " ").replace("-", " ").split()): k
            for k, v in LANGUAGES.items()
        }
        return name_to_code.get(norm, "")

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
        self.model_combo = self._create_combo(AVAILABLE_MODELS, self.config["model_name"])
        model_row.addWidget(model_label)
        model_row.addWidget(self.model_combo)
        layout.addLayout(model_row)

        # 語言提示
        lang_row = QHBoxLayout()
        lang_row.setSpacing(12)
        lang_label = QLabel("Language")
        lang_label.setFixedWidth(140)
        self.lang_input = QLineEdit()
        self.lang_input.setPlaceholderText("auto-detect")
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
        self.config["model_name"] = self.model_combo.currentText()

        # 語言提示：空白=自動偵測；指定語言可略過前 30 秒語言偵測
        raw_lang = (self.lang_input.text() or "").strip() if hasattr(self, "lang_input") else ""
        resolved_lang = self._resolve_language_hint(raw_lang)
        if raw_lang and not resolved_lang:
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
