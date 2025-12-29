import os
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedLayout,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QMessageBox
)
from app_config import load_config, save_config
from dialogs import SettingsDialog, TranscriptPopupDialog
from model_manager import ModelManager
from output_utils import format_transcript, write_srt, write_txt
from style import build_error_dialog_stylesheet, build_stylesheet, get_palette
from widgets import BusyArea, DropArea, RecordArea, WaveformBusyIndicator
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

        # 初始模式：File（拖放）
        # - 當按下「Record」模式鍵時切到 RecordArea，按鍵文字會變成「File」
        self._mode = "file"  # "file" / "record"

        # 確保輸出目錄存在（只在需要輸出檔案時建立）
        self.output_dir = Path(self.config.get("output_dir", str(base_dir / "output")))
        if self.config.get("output_txt", True) or self.config.get("output_srt", True):
            self.output_dir.mkdir(exist_ok=True, parents=True)

        # 初始化模型管理器
        self.model_manager = ModelManager(
            self.config.get("model_name", "turbo"),
            self.config.get("model_ttl_seconds", 180),
        )

        self._queue: list[Path] = []
        self._busy = False
        self._current_worker: TranscribeWorker | None = None
        self._current_thread: threading.Thread | None = None

        # 錄音期間模型預載/保活
        self._record_hold_lock = threading.Lock()
        self._record_hold_active = False
        self._record_hold_acquired = False
        self._record_hold_token = 0
        self._record_transcribe_inflight = False

        # 避免 pop-up 被 GC 回收
        self._popup_refs: list[TranscriptPopupDialog] = []

        # 狀態標籤（BusyArea 會把它疊在波形動畫上方）
        self.status_label = QLabel("Ready")
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setObjectName("StatusLabel")

        # 忙碌指示器（檔案處理/轉譯中）
        self.wave_indicator = WaveformBusyIndicator(
            accent=self._pal["accent"],
            bar_width=5,
            bar_gap=5,
            fps=30,
            speed=0.23,
        )

        # 三個主要區域：DropArea / RecordArea / BusyArea
        self.drop_area = DropArea(self.handle_files, self._pal)

        self.record_area = RecordArea(
            self._pal,
            get_input_device=self._get_input_device,
            on_transcribe=self._transcribe_recorded_audio,
            on_error=self._show_error,
            on_record_start=self._on_recording_started,
            on_record_cancel=self._on_recording_canceled,
            asset_dir=(base_dir / "asset"),
        )

        self.busy_area = BusyArea(self._pal, self.wave_indicator, self.status_label)

        # 堆疊佈局切換三個視圖
        # index 0 = DropArea, 1 = RecordArea, 2 = BusyArea
        self._stack = QStackedLayout()
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._stack.addWidget(self.drop_area)
        self._stack.addWidget(self.record_area)
        self._stack.addWidget(self.busy_area)

        stack_container = QWidget()
        stack_container.setLayout(self._stack)

        # 按鈕區域
        button_layout = QHBoxLayout()
        button_layout.setSpacing(8)

        # 模式鍵：Record <-> File（當前在 file 模式時顯示 "Record"）
        self.record_btn = QPushButton("Record")
        self.record_btn.clicked.connect(self._toggle_mode)

        # 打開輸出資料夾按鈕
        self.open_folder_btn = QPushButton("Output Folder")
        self.open_folder_btn.clicked.connect(self._open_output_folder)

        # 設定按鈕
        self.settings_btn = QPushButton("Settings")
        self.settings_btn.clicked.connect(self._open_settings)

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
        self._show_idle_view()

    # -------------------------------------------------------------------------
    # Theme / Mode
    # -------------------------------------------------------------------------

    def _apply_theme(self):
        """應用主題樣式"""
        self.setStyleSheet(build_stylesheet(self._pal))

    def _toggle_mode(self) -> None:
        """切換模式：File（DropArea）<-> Record（RecordArea）"""
        if self._busy:
            return

        if self._mode == "file":
            self._mode = "record"
            self.record_btn.setText("File")
            self._show_idle_view()
        else:
            # 切回檔案模式時，保守停止並清掉錄音（避免背景 stream 留著）
            self.record_area.reset_recording()

            self._mode = "file"
            self.record_btn.setText("Record")
            self._show_idle_view()

    def _show_idle_view(self) -> None:
        """顯示閒置視圖：依模式顯示 DropArea 或 RecordArea。"""
        if self._busy:
            self._stack.setCurrentIndex(2)
            return

        if self._mode == "record":
            self._stack.setCurrentIndex(1)
        else:
            self._stack.setCurrentIndex(0)

    def _show_busy_view(self) -> None:
        """顯示忙碌視圖（BusyArea）"""
        self._stack.setCurrentIndex(2)

    def _set_busy_controls(self, busy: bool) -> None:
        """Busy 時禁用部分控制項，避免狀態競態。"""
        busy = bool(busy)
        self.record_btn.setEnabled(not busy)
        self.settings_btn.setEnabled(not busy)
        self.record_area.set_controls_enabled(not busy)

    # -------------------------------------------------------------------------
    # Settings / Output folder
    # -------------------------------------------------------------------------

    def _open_settings(self):
        """打開設定視窗"""
        dlg = SettingsDialog(self.config, parent=self)
        dlg.settings_changed.connect(self._apply_settings)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _apply_settings(self, new_config: dict):
        """套用新設定"""
        self.config = new_config
        save_config(self.config)

        self._pal = get_palette(self.config.get("theme", "dark"))
        self._apply_theme()

        # 重新建立輸出目錄（只在需要輸出檔案時建立）
        base_dir = Path(__file__).resolve().parent
        self.output_dir = Path(self.config.get("output_dir", str(base_dir / "output")))
        if self.config.get("output_txt", True) or self.config.get("output_srt", True):
            self.output_dir.mkdir(exist_ok=True, parents=True)

        # 更新模型管理器設定
        self.model_manager.update_config(
            self.config.get("model_name", "turbo"),
            self.config.get("model_ttl_seconds", 180),
        )

        # 更新 Busy 指示器顏色
        self.wave_indicator.set_color(self._pal["accent"])

        # 重新建立三個區域（確保 palette/邊框一致）
        self._rebuild_gui()

    def _rebuild_gui(self) -> None:
        """重建面板（Drop/Record/Busy）以刷新 palette。"""
        base_dir = Path(__file__).resolve().parent

        old_drop = self.drop_area
        old_record = self.record_area
        old_busy = self.busy_area
        current_status = self.status_label.text()

        self.drop_area = DropArea(self.handle_files, self._pal)
        self.record_area = RecordArea(
            self._pal,
            get_input_device=self._get_input_device,
            on_transcribe=self._transcribe_recorded_audio,
            on_error=self._show_error,
            on_record_start=self._on_recording_started,
            on_record_cancel=self._on_recording_canceled,
            asset_dir=(base_dir / "asset"),
        )
        self.busy_area = BusyArea(self._pal, self.wave_indicator, self.status_label)

        self.status_label.setText(current_status)
        self.status_label.setVisible(True)
        self.status_label.raise_()

        self._stack.removeWidget(old_drop)
        self._stack.removeWidget(old_record)
        self._stack.removeWidget(old_busy)

        # 依 index 插回去，保持 index 固定：0 drop, 1 record, 2 busy
        self._stack.insertWidget(0, self.drop_area)
        self._stack.insertWidget(1, self.record_area)
        self._stack.insertWidget(2, self.busy_area)

        old_drop.deleteLater()
        old_record.deleteLater()
        old_busy.deleteLater()

        self._show_idle_view()

    def _open_output_folder(self):
        """打開輸出資料夾"""
        folder = str(self.output_dir)
        try:
            if os.name == "nt":
                os.startfile(folder)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", folder], check=False)
            else:
                subprocess.run(["xdg-open", folder], check=False)
        except Exception:
            # 這裡不阻塞主要流程：不一定每個環境都能 open folder
            pass

    def _get_input_device(self) -> int:
        """取得目前設定的麥克風裝置（-1 代表 system default）。"""
        try:
            return int(self.config.get("input_device", -1))
        except Exception:
            return -1

    def _on_recording_started(self) -> None:
        """錄音開始時預載模型，避免錄完才載入。"""
        self._begin_record_hold()

    def _on_recording_canceled(self) -> None:
        """錄音取消/重置時釋放模型保活。"""
        self._record_transcribe_inflight = False
        self._end_record_hold()

    def _begin_record_hold(self) -> None:
        """建立錄音期間的模型保活，並在背景預載。"""
        with self._record_hold_lock:
            if self._record_hold_active:
                return
            self._record_hold_active = True
            self._record_hold_acquired = False
            self._record_hold_token += 1
            token = self._record_hold_token

        threading.Thread(
            target=self._warmup_record_model,
            args=(token,),
            daemon=True,
        ).start()

    def _warmup_record_model(self, token: int) -> None:
        """背景預載模型，並在必要時自動釋放保活。"""
        try:
            self.model_manager.acquire()
        except Exception:
            with self._record_hold_lock:
                if token == self._record_hold_token:
                    self._record_hold_active = False
                    self._record_hold_acquired = False
            return

        release_now = False
        with self._record_hold_lock:
            if token != self._record_hold_token or not self._record_hold_active:
                release_now = True
            else:
                self._record_hold_acquired = True

        if release_now:
            self.model_manager.release()

    def _end_record_hold(self) -> None:
        """結束錄音保活，允許模型正常 TTL 卸載。"""
        release_now = False
        with self._record_hold_lock:
            if not self._record_hold_active:
                return
            self._record_hold_active = False
            release_now = self._record_hold_acquired
            self._record_hold_acquired = False

        if release_now:
            self.model_manager.release()

    # -------------------------------------------------------------------------
    # File drop pipeline
    # -------------------------------------------------------------------------

    def handle_files(self, files: list[str]):
        """處理拖放的檔案"""
        if self._busy:
            QMessageBox.information(self, "Busy", "Currently processing. Please wait.")
            return

        paths = [Path(p) for p in files if p]
        # 只保留存在的檔案
        paths = [p for p in paths if p.exists()]

        if not paths:
            return

        self._queue.extend(paths)
        self._start_next_if_idle()

    def _start_next_if_idle(self):
        """如果閒置就開始處理下一個檔案"""
        if self._busy or not self._queue:
            return

        input_path = self._queue.pop(0)
        self._busy = True
        self._set_busy_controls(True)
        self._show_busy_view()
        self.status_label.setText(f"Queued: {input_path.name}\nStarting...")

        worker = TranscribeWorker(
            input_path=input_path,
            model_manager=self.model_manager,
            language_hint=self.config.get("language_hint", ""),
            display_name=input_path.name,
            output_stem=input_path.stem,
        )
        self._start_worker_thread(worker)

    # -------------------------------------------------------------------------
    # Recording pipeline (in-memory)
    # -------------------------------------------------------------------------

    def _transcribe_recorded_audio(self, audio) -> None:
        """由 RecordArea 呼叫：把錄音波形送進 whisper（不落地）。"""
        if self._busy:
            return

        # 為每次錄音產生唯一輸出檔名，避免覆蓋
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        stem = f"recording_{ts}"

        self._busy = True
        self._set_busy_controls(True)
        self._show_busy_view()
        self.status_label.setText("Transcribing recording...")
        self._record_transcribe_inflight = True

        worker = TranscribeWorker(
            audio=audio,
            model_manager=self.model_manager,
            language_hint=self.config.get("language_hint", ""),
            display_name="Recording",
            output_stem=stem,
        )
        self._start_worker_thread(worker)

    def _start_worker_thread(self, worker: TranscribeWorker) -> None:
        """共用啟動流程：綁定 signal + 啟動執行緒。"""
        worker.progress.connect(self._on_worker_progress)
        worker.finished.connect(self._on_worker_finished)
        worker.error.connect(self._on_worker_error)

        thread = threading.Thread(target=worker.run, daemon=True)
        self._current_worker = worker
        self._current_thread = thread
        thread.start()

    # -------------------------------------------------------------------------
    # Worker callbacks
    # -------------------------------------------------------------------------

    def _on_worker_progress(self, message: str):
        """工作器進度更新"""
        self.status_label.setText(message)

    def _on_worker_finished(self, payload: dict):
        """工作器完成（由主執行緒處理輸出：pop-up / clipboard / txt / srt）"""
        display_name = payload.get("display_name") or ""
        output_stem = payload.get("output_stem") or ""

        input_path_str = payload.get("input_path", "") or ""
        input_path = Path(input_path_str) if input_path_str else Path()

        stem = output_stem or (input_path.stem if input_path.name else "output")
        title_name = display_name or (input_path.name if input_path.name else "Recording")

        raw_text = payload.get("text", "") or ""
        segments = payload.get("segments") or []
        use_smart_format = bool(self.config.get("output_smart_format", True))
        output_text = format_transcript(raw_text, segments) if use_smart_format else raw_text

        # 1) clipboard：直接寫入剪貼簿
        if self.config.get("output_clipboard", False):
            QApplication.clipboard().setText(output_text)

        # 2) pop-up：顯示可選取文字的子視窗
        if self.config.get("output_popup", False):
            dlg = TranscriptPopupDialog(
                title=f"Transcription - {title_name}",
                text=output_text,
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
            saved_paths.append(write_txt(self.output_dir, stem, output_text))
        if self.config.get("output_srt", True):
            saved_paths.append(write_srt(self.output_dir, stem, segments))

        if saved_paths:
            self.status_label.setText("Complete (saved)")
        else:
            self.status_label.setText("Complete")

        self._busy = False
        self._set_busy_controls(False)
        self._current_worker = None
        self._current_thread = None

        if self._record_transcribe_inflight:
            self._record_transcribe_inflight = False
            self._end_record_hold()

        if self._queue:
            self._start_next_if_idle()
        else:
            self._show_idle_view()

    def _on_worker_error(self, message: str, details: str = ""):
        """工作器錯誤"""
        self._show_error(message=message, details=details)

        self._busy = False
        self._set_busy_controls(False)
        self._current_worker = None
        self._current_thread = None

        if self._record_transcribe_inflight:
            self._record_transcribe_inflight = False
            self._end_record_hold()

        if self._queue:
            self._start_next_if_idle()
        else:
            self._show_idle_view()
            self.status_label.setText("Ready")

    # -------------------------------------------------------------------------
    # Model lifecycle
    # -------------------------------------------------------------------------

    def _maybe_unload_model(self):
        """定期檢查是否可以卸載模型以釋放 VRAM"""
        if not self._busy and not self._queue:
            ttl = int(self.config.get("model_ttl_seconds", 180))
            if ttl >= 0:
                self.model_manager.maybe_unload()

    # -------------------------------------------------------------------------
    # Error dialog
    # -------------------------------------------------------------------------

    def _play_error_sound(self) -> None:
        """播放系統錯誤提示音（盡量模擬 QMessageBox 的行為）。

        備註：
        - Windows 優先使用 winsound.MessageBeep（錯誤音效較接近 QMessageBox）
        - 其他平台或失敗時，退回 QApplication.beep()
        """
        try:
            import winsound  # type: ignore

            winsound.MessageBeep(winsound.MB_ICONHAND)
            return
        except Exception:
            pass

        try:
            QApplication.beep()
        except Exception:
            pass

    def _show_error(self, message: str, details: str = "") -> None:
        """顯示可調整大小的錯誤對話框（取代 QMessageBox）。

        設計重點：
        - 主訊息保持精簡，避免與 traceback 重複。
        - traceback 放在可切換的 details 區塊，方便閱讀與複製。
        - 視覺樣式集中到 style.py 統一管理，避免 GUI 檔案塞滿 QSS。
        """
        self._play_error_sound()

        theme = (
            (self.config.get("theme") or "dark")
            if hasattr(self, "config")
            else "dark"
        )
        pal = get_palette(theme)

        dlg = QDialog(self)
        dlg.setWindowTitle("Error")
        dlg.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint)
        dlg.setMinimumSize(400, 400)
        dlg.setSizeGripEnabled(True)
        dlg.setStyleSheet(build_error_dialog_stylesheet(pal))

        root = QVBoxLayout(dlg)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        title = QLabel("Processing failed")
        title.setObjectName("ErrorTitle")
        root.addWidget(title)

        msg_view = QTextEdit()
        msg_view.setObjectName("ErrorMessage")
        msg_view.setReadOnly(True)
        msg_view.setPlainText(message or "Unknown error")
        msg_view.setMinimumHeight(140)
        msg_view.setLineWrapMode(QTextEdit.WidgetWidth)
        root.addWidget(msg_view, 1)

        details_toggle = QCheckBox("Show details")

        details_view = QTextEdit()
        details_view.setObjectName("ErrorDetails")
        details_view.setReadOnly(True)
        details_view.setPlainText(details or "")
        details_view.setVisible(False)
        details_view.setLineWrapMode(QTextEdit.NoWrap)

        if (details or "").strip():
            details_toggle.toggled.connect(details_view.setVisible)
            root.addWidget(details_toggle)
            root.addWidget(details_view, 2)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)

        btn_copy = QPushButton("Copy")
        btn_ok = QPushButton("OK")
        btn_ok.setObjectName("primary")

        def _copy_all() -> None:
            text = msg_view.toPlainText()
            if (details or "").strip():
                text = text + "\n\n" + details_view.toPlainText()
            QApplication.clipboard().setText(text)

        btn_copy.clicked.connect(_copy_all)
        btn_ok.clicked.connect(dlg.accept)

        btn_row.addWidget(btn_copy)
        btn_row.addWidget(btn_ok)
        root.addLayout(btn_row)

        dlg.exec()

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    def closeEvent(self, event):
        """視窗關閉事件：停止錄音 + 強制卸載模型"""
        try:
            self.record_area.shutdown()
        except Exception:
            pass

        self.model_manager.force_unload()
        super().closeEvent(event)


if __name__ == "__main__":
    print("Whisper Transcription Tool (refactor)")
    app = QApplication([])
    win = MainWindow()
    win.show()
    app.exec()
