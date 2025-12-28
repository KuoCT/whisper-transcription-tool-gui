"""
audio_extract.py
功能說明：
- 統一抽取/轉換音訊（支援輸出成檔案或純記憶體）
- 需求：系統需已安裝 ffmpeg，並加入 PATH

備註：
- 若你要接 Whisper，建議使用 extract_audio_array()（不落地檔案），回傳 float32 waveform。
"""

from __future__ import annotations
import os
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional, Set


# =========================
# ffmpeg 檢查
# =========================

@lru_cache(maxsize=1)
def ensure_ffmpeg_available() -> None:
    """確認 ffmpeg 可用；若不可用則直接拋錯。

    需求：你希望「程式一開始」就檢查，因此本模組載入時就會執行一次。
    """
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        raise RuntimeError(
            "找不到 ffmpeg（系統 PATH 內無 ffmpeg）。"
            "請先安裝 ffmpeg 並加入 PATH 後再重試。"
            "安裝方式參考："
            "- Windows: winget install Gyan.FFmpeg 或 choco install ffmpeg"
            "- macOS  : brew install ffmpeg"
            "- Ubuntu : sudo apt-get update && sudo apt-get install -y ffmpeg"
        )

    # 再做一次可執行性驗證（避免 PATH 有殘影或權限問題）
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        raise RuntimeError(
            "偵測到 ffmpeg 路徑，但執行 ffmpeg -version 失敗。"
            "請確認 ffmpeg 安裝正確、具有執行權限，且 PATH 設定無誤。"
        ) from e


# =========================
# 媒體格式登錄表（Registry）
# =========================

@dataclass(frozen=True)
class MediaFormat:
    """描述一種媒體類型（影片 / 音訊）"""

    kind: str  # "video" | "audio"
    extensions: Set[str]


MEDIA_REGISTRY: Dict[str, MediaFormat] = {
    "video": MediaFormat(kind="video", extensions={"mp4", "mkv", "avi", "mov", "webm"}),
    "audio": MediaFormat(kind="audio", extensions={"mp3", "wav", "m4a", "flac", "aac", "ogg"}),
}


# 建立「副檔名 → 媒體類型」的快速查詢表（O(1)）
EXTENSION_TO_KIND: Dict[str, str] = {
    ext: media.kind
    for media in MEDIA_REGISTRY.values()
    for ext in media.extensions
}


def get_media_kind(ext: str) -> Optional[str]:
    """依副檔名判斷媒體類型

    參數：
        ext: 副檔名（可包含或不包含 '.'）

    回傳：
        "video" | "audio" | None
    """
    return EXTENSION_TO_KIND.get(ext.lower().lstrip("."))


# =========================
# 自訂例外
# =========================

class UnsupportedFormatError(Exception):
    """不支援的媒體格式"""


# =========================
# 共用：執行 ffmpeg
# =========================

def _run_ffmpeg(cmd: list[str]) -> None:
    """執行 ffmpeg 指令（統一錯誤訊息格式）。"""
    # Windows：避免跳出 console 視窗（可選）
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            "ffmpeg 轉檔失敗，錯誤訊息：" + (e.stderr or "<no stderr>")
        ) from e


# =========================
# 對外 API：輸出成檔案
# =========================

def extract_audio(
    input_path: str | Path,
    output_path: str | Path,
    output_format: str = "mp3",
    sample_rate: int = 48000,
    bitrate: str = "192k",
    channels: int = 2,
) -> Path:
    """從影片或音訊檔中抽取音訊，並轉成指定格式（輸出成檔案）。

    參數：
        input_path    : 輸入檔案路徑
        output_path   : 輸出檔案路徑（不含副檔名）
        output_format : "mp3" 或 "wav"
        sample_rate   : 取樣率（預設 48000）
        bitrate       : mp3 位元率（僅 mp3 使用）
        channels      : 聲道數（預設 2；若要接 Whisper 建議 1）

    回傳：
        最終輸出的音訊檔 Path
    """
    ensure_ffmpeg_available()

    input_path = Path(input_path)
    output_path = Path(output_path)

    # 檢查輸入檔案是否存在
    if not input_path.exists():
        raise FileNotFoundError(input_path)

    # 判斷輸入媒體類型
    ext = input_path.suffix.lower().removeprefix(".")
    media_kind = get_media_kind(ext)
    if media_kind is None:
        raise UnsupportedFormatError(f"Unsupported input format: .{ext}")

    # 檢查輸出格式
    if output_format not in {"mp3", "wav"}:
        raise UnsupportedFormatError(f"Unsupported output format: {output_format}")

    # 組合輸出檔案路徑
    output_file = output_path.with_suffix(f".{output_format}")

    # 確保輸出資料夾存在
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # ffmpeg 指令組合
    cmd = [
        "ffmpeg",
        "-y",  # 覆寫輸出檔
        "-loglevel",
        "error",  # 減少噪音，只保留錯誤
        "-i",
        str(input_path),
        "-vn",  # 忽略影像（只取音訊）
        "-ar",
        str(sample_rate),
        "-ac",
        str(channels),
    ]

    if output_format == "mp3":
        # 建議使用 -b:a 指定位元率
        cmd += ["-b:a", bitrate]

    cmd.append(str(output_file))

    _run_ffmpeg(cmd)
    return output_file


# =========================
# 對外 API：純記憶體（不落地檔案）
# =========================

def extract_audio_bytes(
    input_path: str | Path,
    output_format: str = "wav",
    sample_rate: int = 16000,
    channels: int = 1,
    bitrate: str = "192k",
) -> bytes:
    """抽取音訊並以 bytes 回傳（不落地檔案）。

    建議用途：
    - 若你想自己處理音訊 bytes（例如傳給其他 API / 存 DB / 傳網路）

    參數：
        output_format: "wav" 或 "mp3"

    回傳：
        音訊 bytes
    """
    ensure_ffmpeg_available()

    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(input_path)

    ext = input_path.suffix.lower().removeprefix(".")
    if get_media_kind(ext) is None:
        raise UnsupportedFormatError(f"Unsupported input format: .{ext}")

    if output_format not in {"wav", "mp3"}:
        raise UnsupportedFormatError(f"Unsupported output format: {output_format}")

    # 透過 pipe:1 把輸出寫到 stdout
    cmd: list[str] = [
        "ffmpeg",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-vn",
        "-ar",
        str(sample_rate),
        "-ac",
        str(channels),
    ]

    if output_format == "wav":
        cmd += ["-f", "wav", "pipe:1"]
    else:
        cmd += ["-f", "mp3", "-b:a", bitrate, "pipe:1"]

    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        p = subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creationflags,
        )
        return p.stdout
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else "<no stderr>"
        raise RuntimeError("ffmpeg 抽取音訊失敗，錯誤訊息：" + stderr) from e


def extract_audio_array(
    input_path: str | Path,
    sample_rate: int = 16000,
    channels: int = 1,
):
    """抽取音訊並回傳為 numpy float32 waveform（不落地檔案）。

    這個函式特別適合接 Whisper：
    - Whisper 的 transcribe 可直接吃 1D float32 waveform（範圍約 -1 ~ 1）。

    回傳：
        np.ndarray (float32), shape=(n_samples,)
    """
    ensure_ffmpeg_available()

    # 延遲載入：避免不需要 numpy 的人也被迫安裝
    try:
        import numpy as np
    except Exception as e:
        raise RuntimeError("使用 extract_audio_array 需要安裝 numpy。") from e

    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(input_path)

    ext = input_path.suffix.lower().removeprefix(".")
    if get_media_kind(ext) is None:
        raise UnsupportedFormatError(f"Unsupported input format: .{ext}")

    # 直接輸出 raw PCM（s16le）到 stdout，避免還要依賴 soundfile/pydub 解析 wav
    cmd = [
        "ffmpeg",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-vn",
        "-ar",
        str(sample_rate),
        "-ac",
        str(channels),
        "-f",
        "s16le",
        "pipe:1",
    ]

    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        p = subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creationflags,
        )
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else "<no stderr>"
        raise RuntimeError("ffmpeg 抽取音訊失敗，錯誤訊息：" + stderr) from e

    # bytes -> int16 -> float32 (-1 ~ 1)
    audio_i16 = np.frombuffer(p.stdout, dtype=np.int16)
    if audio_i16.size == 0:
        raise RuntimeError("ffmpeg 回傳空音訊（可能是輸入檔無音軌或解碼失敗）。")

    if channels > 1:
        # (n_frames, channels) -> 取平均成 mono
        audio_i16 = audio_i16.reshape(-1, channels).mean(axis=1).astype(np.int16)

    audio_f32 = audio_i16.astype(np.float32) / 32768.0
    return audio_f32


# =========================
# 模組載入時就先檢查（符合「程式一開始就檢查」的需求）
# =========================

ensure_ffmpeg_available()


# =========================
# CLI 入口
# =========================

if __name__ == "__main__":
    import sys
    from pathlib import Path

    from PySide6.QtCore import QObject, Qt, QUrl, Signal, Slot, QProcess
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QFileDialog,
        QFormLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMessageBox,
        QPushButton,
        QProgressDialog,
        QSpinBox,
        QVBoxLayout,
    )

    def _build_media_filter() -> str:
        video_exts = sorted(MEDIA_REGISTRY["video"].extensions)
        audio_exts = sorted(MEDIA_REGISTRY["audio"].extensions)
        all_exts = sorted(set(video_exts) | set(audio_exts))
        media_patterns = " ".join([f"*.{ext}" for ext in all_exts])
        return f"Media files ({media_patterns});;All files (*)"

    def _default_output_file(input_path: Path, fmt: str) -> Path:
        return input_path.with_suffix(f".{fmt}")

    class ConvertWorker(QObject):
        """使用 QProcess 執行 ffmpeg，不會阻塞事件循環"""
        finished = Signal(object)  # Path
        failed = Signal(str)

        def __init__(
            self,
            input_path: Path,
            output_file: Path,
            output_format: str,
            sample_rate: int,
            bitrate: str,
            channels: int,
        ) -> None:
            super().__init__()
            self.input_path = input_path
            self.output_file = output_file
            self.output_format = output_format
            self.sample_rate = sample_rate
            self.bitrate = bitrate
            self.channels = channels
            self.process = None

        @Slot()
        def run(self) -> None:
            """組裝 ffmpeg 指令並用 QProcess 執行"""
            try:
                # 確保輸出目錄存在
                self.output_file.parent.mkdir(parents=True, exist_ok=True)

                # 組裝指令
                cmd = [
                    "ffmpeg",
                    "-y",
                    "-loglevel", "error",
                    "-i", str(self.input_path),
                    "-vn",
                    "-ar", str(self.sample_rate),
                    "-ac", str(self.channels),
                ]

                if self.output_format == "mp3":
                    cmd += ["-b:a", self.bitrate]

                cmd.append(str(self.output_file))

                # 使用 QProcess
                self.process = QProcess()
                self.process.finished.connect(self._on_finished)
                self.process.errorOccurred.connect(self._on_error)
                
                # 啟動 ffmpeg
                self.process.start(cmd[0], cmd[1:])
                
            except Exception as e:
                self.failed.emit(f"準備轉檔時發生錯誤：{e}")

        @Slot(int, QProcess.ExitStatus)
        def _on_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
            """ffmpeg 執行完畢"""
            if exit_code == 0 and exit_status == QProcess.ExitStatus.NormalExit:
                self.finished.emit(self.output_file)
            else:
                stderr = self.process.readAllStandardError().data().decode('utf-8', errors='replace')
                self.failed.emit(f"ffmpeg 轉檔失敗 (exit code: {exit_code})\n{stderr}")
            
            self.process.deleteLater()
            self.process = None

        @Slot(QProcess.ProcessError)
        def _on_error(self, error: QProcess.ProcessError) -> None:
            """QProcess 發生錯誤"""
            error_msg = f"QProcess 錯誤：{error}"
            if self.process:
                stderr = self.process.readAllStandardError().data().decode('utf-8', errors='replace')
                if stderr:
                    error_msg += f"\n{stderr}"
            self.failed.emit(error_msg)

    class ConvertDialog(QDialog):
        def __init__(self, input_path: Path, parent=None) -> None:
            super().__init__(parent)
            self.setWindowTitle("Audio Convert")

            self.input_path = input_path
            self._output_customized = False
            self.worker = None

            layout = QVBoxLayout(self)
            layout.addWidget(QLabel(f"Input: {input_path}"))

            form = QFormLayout()

            self.format_combo = QComboBox()
            self.format_combo.addItems(["mp3", "wav"])
            form.addRow("Format", self.format_combo)

            self.sr_spin = QSpinBox()
            self.sr_spin.setRange(8000, 192000)
            self.sr_spin.setSingleStep(1000)
            self.sr_spin.setValue(48000)
            form.addRow("Sample rate (Hz)", self.sr_spin)

            self.channels_combo = QComboBox()
            self.channels_combo.addItems(["1 (mono)", "2 (stereo)"])
            self.channels_combo.setCurrentIndex(1)
            form.addRow("Channels", self.channels_combo)

            self.bitrate_combo = QComboBox()
            self.bitrate_combo.addItems(["96k", "128k", "160k", "192k", "256k", "320k"])
            self.bitrate_combo.setCurrentText("192k")
            form.addRow("Bitrate (mp3)", self.bitrate_combo)

            out_row = QHBoxLayout()
            self.output_edit = QLineEdit()
            self.output_edit.setText(str(_default_output_file(input_path, "mp3")))
            self.output_btn = QPushButton("Browse…")
            self.output_btn.setFocusPolicy(Qt.NoFocus)
            out_row.addWidget(self.output_edit, 1)
            out_row.addWidget(self.output_btn)
            form.addRow("Output file", out_row)

            self.open_dir_chk = QCheckBox("Open output folder when done")
            self.open_dir_chk.setChecked(True)
            form.addRow("", self.open_dir_chk)

            layout.addLayout(form)

            self.buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
            self.convert_btn = QPushButton("Convert")
            self.convert_btn.setDefault(True)
            self.buttons.addButton(self.convert_btn, QDialogButtonBox.AcceptRole)
            layout.addWidget(self.buttons)

            self.buttons.rejected.connect(self.reject)
            self.convert_btn.clicked.connect(self._on_convert)
            self.output_btn.clicked.connect(self._browse_output)
            self.output_edit.textEdited.connect(self._mark_output_customized)
            self.format_combo.currentTextChanged.connect(self._sync_widgets_by_format)
            self.format_combo.currentTextChanged.connect(self._maybe_update_output_by_format)

            self._sync_widgets_by_format(self.format_combo.currentText())

        def _mark_output_customized(self) -> None:
            self._output_customized = True

        def _sync_widgets_by_format(self, fmt: str) -> None:
            is_mp3 = fmt == "mp3"
            self.bitrate_combo.setEnabled(is_mp3)

        def _maybe_update_output_by_format(self, fmt: str) -> None:
            if self._output_customized:
                return
            self.output_edit.setText(str(_default_output_file(self.input_path, fmt)))

        def _browse_output(self) -> None:
            fmt = self.format_combo.currentText()
            suggested = self.output_edit.text().strip() or str(_default_output_file(self.input_path, fmt))
            file_filter = f"{fmt.upper()} (*.{fmt});;All files (*)"
            out_path, _ = QFileDialog.getSaveFileName(self, "Save output as…", suggested, file_filter)
            if out_path:
                self._output_customized = True
                self.output_edit.setText(out_path)

        def _read_params(self) -> tuple[Path, str, int, str, int, bool]:
            fmt = self.format_combo.currentText()
            sr = int(self.sr_spin.value())
            channels = 1 if self.channels_combo.currentIndex() == 0 else 2
            bitrate = self.bitrate_combo.currentText()

            output_text = self.output_edit.text().strip()
            if not output_text:
                output_file = _default_output_file(self.input_path, fmt)
            else:
                output_file = Path(output_text)

            if output_file.suffix.lower() != f".{fmt}":
                output_file = output_file.with_suffix(f".{fmt}")

            if sr <= 0:
                raise ValueError("Sample rate must be a positive integer.")
            if channels not in {1, 2}:
                raise ValueError("Channels must be 1 or 2.")

            open_dir = self.open_dir_chk.isChecked()
            return output_file, fmt, sr, bitrate, channels, open_dir

        def _on_convert(self) -> None:
            try:
                output_file, fmt, sr, bitrate, channels, open_dir = self._read_params()
            except Exception as e:
                QMessageBox.critical(self, "Invalid settings", str(e))
                return

            self.convert_btn.setEnabled(False)

            progress = QProgressDialog("Converting…", "Cancel", 0, 0, self)
            progress.setWindowTitle("Please wait")
            progress.setWindowModality(Qt.ApplicationModal)
            progress.setCancelButton(None)  # 暫時不支援取消
            progress.show()

            # 建立 Worker（不需要 QThread，QProcess 本身就是非阻塞的）
            self.worker = ConvertWorker(
                input_path=self.input_path,
                output_file=output_file,
                output_format=fmt,
                sample_rate=sr,
                bitrate=bitrate,
                channels=channels,
            )

            @Slot(object)
            def _done(out_path_obj) -> None:
                progress.close()
                self.convert_btn.setEnabled(True)
                out_path = Path(out_path_obj)
                QMessageBox.information(self, "Done", f"Output:\n{out_path}")
                if open_dir:
                    QDesktopServices.openUrl(QUrl.fromLocalFile(str(out_path.parent)))
                self.accept()

            @Slot(str)
            def _fail(msg: str) -> None:
                progress.close()
                self.convert_btn.setEnabled(True)
                QMessageBox.critical(self, "Failed", msg)

            self.worker.finished.connect(_done)
            self.worker.failed.connect(_fail)
            self.worker.run()

    app = QApplication(sys.argv)

    media_filter = _build_media_filter()
    input_file, _ = QFileDialog.getOpenFileName(
        None,
        "Select a video or audio file",
        "",
        media_filter,
    )
    if not input_file:
        raise SystemExit(0)

    dlg = ConvertDialog(Path(input_file))
    dlg.exec()

    raise SystemExit(0)
