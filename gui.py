import os
import subprocess
import sys
import threading
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from app_config import load_config, save_config
from dialogs import SettingsDialog, TranscriptPopupDialog
from model_manager import ModelManager
from output_utils import write_srt, write_txt
from style import build_stylesheet, get_palette
from widgets import BusyArea, DropArea, WaveformBusyIndicator
from worker import TranscribeWorker


WINDOW_WIDTH = 400
WINDOW_HEIGHT = 180


class MainWindow(QWidget):
    """主視窗"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Whisper Transcription Tool")
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)

        # 載入配置
        self.config = load_config()

        # 把模型快取移到專案資料夾
        base_dir = Path(__file__).resolve().parent
        os.environ["XDG_CACHE_HOME"] = str(base_dir / "cache")

        self._pal = get_palette(self.config.get("theme", "dark"))

        # 確保輸出目錄存在（只在需要輸出檔案時建立）
        self.output_dir = Path(self.config.get("output_dir", str(base_dir / "output")))
        if self.config.get("output_txt", True) or self.config.get("output_srt", True):
            self.output_dir.mkdir(exist_ok=True, parents=True)

        # 初始化模型管理器
        self.model_manager = ModelManager(
            self.config.get("model_name", "large"),
            self.config.get("model_ttl_seconds", 60),
        )

        self._queue: list[Path] = []
        self._busy = False
        self._current_worker: TranscribeWorker | None = None
        self._current_thread: threading.Thread | None = None

        # 避免 pop-up 被 GC 回收
        self._popup_refs: list[TranscriptPopupDialog] = []

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
        self.setStyleSheet(build_stylesheet(self._pal))

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
        old_theme = self.config.get("theme", "dark")
        self.config = new_config
        save_config(new_config)

        # 更新輸出目錄
        self.output_dir = Path(self.config.get("output_dir", "output"))
        if self.config.get("output_txt", True) or self.config.get("output_srt", True):
            self.output_dir.mkdir(exist_ok=True, parents=True)

        # 更新模型管理器配置
        self.model_manager.update_config(
            self.config.get("model_name", "large"),
            self.config.get("model_ttl_seconds", 60),
        )

        # 如果主題改變，重新創建整個 GUI
        if old_theme != self.config.get("theme", "dark"):
            self._rebuild_gui()

    def _rebuild_gui(self):
        """重新構建整個 GUI（用於主題切換）"""
        was_busy = self._busy
        current_queue = self._queue.copy()
        current_status = self.status_label.text()

        self._pal = get_palette(self.config.get("theme", "dark"))

        self._apply_theme()
        self.wave_indicator.set_color(self._pal["accent"])

        old_drop = self.drop_area
        old_busy = self.busy_area

        self.drop_area = DropArea(self.handle_files, self._pal)
        self.busy_area = BusyArea(self._pal, self.wave_indicator, self.status_label)

        self.status_label.setText(current_status)
        self.status_label.setVisible(True)
        self.status_label.raise_()

        self._stack.removeWidget(old_drop)
        self._stack.removeWidget(old_busy)
        self._stack.insertWidget(0, self.drop_area)
        self._stack.insertWidget(1, self.busy_area)

        old_drop.deleteLater()
        old_busy.deleteLater()

        if was_busy:
            self._show_busy_view()
        else:
            self._show_idle_view()

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
            self._show_error("File not found:\n" + "\n".join(invalid_files))

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

        worker = TranscribeWorker(
            input_path=input_path,
            model_manager=self.model_manager,
            language_hint=self.config.get("language_hint", ""),
        )
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

    def _on_worker_finished(self, payload: dict):
        """工作器完成（由主執行緒處理輸出：pop-up / clipboard / txt / srt）"""
        input_path = Path(payload.get("input_path", ""))
        stem = input_path.stem if input_path.name else "output"
        text = payload.get("text", "") or ""
        segments = payload.get("segments") or []

        # 1) clipboard：直接寫入剪貼簿
        if self.config.get("output_clipboard", False):
            QApplication.clipboard().setText(text)

        # 2) pop-up：顯示可選取文字的子視窗
        if self.config.get("output_popup", False):
            dlg = TranscriptPopupDialog(
                title=f"Transcription - {input_path.name}",
                text=text,
                theme=self.config.get("theme", "dark"),
                parent=self,
            )
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
            self._popup_refs.append(dlg)

        # 3) 檔案輸出
        saved_paths: list[Path] = []
        if self.config.get("output_txt", True):
            saved_paths.append(write_txt(self.output_dir, stem, text))
        if self.config.get("output_srt", True):
            saved_paths.append(write_srt(self.output_dir, stem, segments))

        if saved_paths:
            self.status_label.setText("Complete (saved)")
        else:
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
            ttl = int(self.config.get("model_ttl_seconds", 60))
            if ttl >= 0:
                self.model_manager.maybe_unload()

    def _show_error(self, message: str):
        """顯示錯誤訊息（平面風格）"""
        QMessageBox.critical(self, "Error", message)

    def closeEvent(self, event):
        """視窗關閉事件：強制卸載模型"""
        self.model_manager.force_unload()
        super().closeEvent(event)


if __name__ == "__main__":
    print("Whisper Transcription Tool (refactor)")
    app = QApplication([])
    win = MainWindow()
    win.show()
    app.exec()
