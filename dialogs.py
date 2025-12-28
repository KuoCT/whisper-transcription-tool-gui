from __future__ import annotations
from PySide6.QtCore import Qt, Signal
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
    get_dialog_palette,
)


AVAILABLE_MODELS = ["tiny", "base", "small", "medium", "large", "turbo"]


class TranscriptPopupDialog(QDialog):
    """轉譯結果 Pop-up（可選取文字 + Copy 按鈕）"""

    def __init__(self, title: str, text: str, theme: str = "dark", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint)
        self.setMinimumSize(560, 420)

        # 由 style.py 統一管理顏色與 QSS，避免 dialogs.py 出現大量風格代碼
        pal = get_dialog_palette(theme)
        self.setStyleSheet(build_transcript_popup_stylesheet(pal))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setText(text or "")
        layout.addWidget(self.text_edit, 1)

        row = QHBoxLayout()
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
        pal = get_dialog_palette(theme)
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

        # VRAM Release 時間設定
        ttl_row = QHBoxLayout()
        ttl_row.setSpacing(12)
        ttl_label = QLabel("VRAM Release Time")
        ttl_label.setFixedWidth(140)
        ttl_value = self.config["model_ttl_seconds"]
        ttl_str = "Never" if ttl_value < 0 else str(ttl_value)
        self.ttl_combo = self._create_combo(
            ["30", "60", "120", "300", "600", "Never"],
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

        out_hint = QLabel("Select at least one")
        out_hint.setObjectName("hintLabel")

        out_title_row.addWidget(out_label)
        out_title_row.addWidget(out_hint)
        out_title_row.addStretch(1)
        layout.addLayout(out_title_row)

        out_row = QHBoxLayout()
        out_row.setSpacing(12)

        self.ck_popup = QCheckBox("Pop-up")
        self.ck_clipboard = QCheckBox("Clipboard")
        self.ck_txt = QCheckBox(".txt")
        self.ck_srt = QCheckBox(".srt")

        self.ck_popup.setChecked(bool(self.config.get("output_popup", False)))
        self.ck_clipboard.setChecked(bool(self.config.get("output_clipboard", False)))
        self.ck_txt.setChecked(bool(self.config.get("output_txt", True)))
        self.ck_srt.setChecked(bool(self.config.get("output_srt", True)))

        out_row.addWidget(self.ck_popup)
        out_row.addWidget(self.ck_clipboard)
        out_row.addWidget(self.ck_txt)
        out_row.addWidget(self.ck_srt)
        out_row.addStretch(1)
        layout.addLayout(out_row)

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

        ttl_text = self.ttl_combo.currentText()
        self.config["model_ttl_seconds"] = -1 if ttl_text == "Never" else int(ttl_text)

        # 輸出選項（至少選一個）
        self.config["output_popup"] = bool(self.ck_popup.isChecked())
        self.config["output_clipboard"] = bool(self.ck_clipboard.isChecked())
        self.config["output_txt"] = bool(self.ck_txt.isChecked())
        self.config["output_srt"] = bool(self.ck_srt.isChecked())

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
