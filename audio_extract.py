"""
audio_extract.py
功能說明:
- 統一抽取/轉換音訊（支援輸出檔案或記憶體）
- 使用 PyAV（bundled FFmpeg）避免系統額外安裝

備註:
- 若要接 Whisper，建議使用 extract_audio_array()（不落地檔案），回傳 float32 waveform
"""

from __future__ import annotations
import gc
import io
import itertools
import threading
import wave
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional, Set

try:
    import av
except Exception:  # pragma: no cover - 缺少 PyAV 時直接報錯
    av = None


# -------------------------------------------------------------------------
# PyAV 檢查
# -------------------------------------------------------------------------

@lru_cache(maxsize=1)
def ensure_pyav_available() -> None:
    """確認 PyAV 可用；若未安裝，直接提示。"""
    if av is None:
        raise RuntimeError(
            "PyAV is required but not installed. "
            "Please install PyAV (e.g., `uv pip install av`)."
        )


# -------------------------------------------------------------------------
# 媒體格式註冊表
# -------------------------------------------------------------------------

@dataclass(frozen=True)
class MediaFormat:
    """描述一種媒體格式（影片 / 音訊）。"""

    kind: str  # "video" | "audio"
    extensions: Set[str]


MEDIA_REGISTRY: Dict[str, MediaFormat] = {
    "video": MediaFormat(kind="video", extensions={"mp4", "mkv", "avi", "mov", "webm"}),
    "audio": MediaFormat(kind="audio", extensions={"mp3", "wav", "m4a", "flac", "aac", "ogg"}),
}


# 建立副檔名 -> 媒體類型的快速查詢表（O(1)）
EXTENSION_TO_KIND: Dict[str, str] = {
    ext: media.kind
    for media in MEDIA_REGISTRY.values()
    for ext in media.extensions
}


def get_media_kind(ext: str) -> Optional[str]:
    """依副檔名判斷媒體類型。"""
    return EXTENSION_TO_KIND.get(ext.lower().lstrip("."))


class UnsupportedFormatError(Exception):
    """不支援的媒體格式。"""


# -------------------------------------------------------------------------
# 共用：PyAV 解碼/重取樣
# -------------------------------------------------------------------------

def _validate_audio_params(sample_rate: int, channels: int) -> None:
    if sample_rate <= 0:
        raise ValueError("sample_rate must be a positive integer.")
    if channels not in {1, 2}:
        raise ValueError("channels must be 1 or 2.")


def _ensure_input_file(input_path: Path) -> None:
    if not input_path.exists():
        raise FileNotFoundError(input_path)

    ext = input_path.suffix.lower().removeprefix(".")
    if get_media_kind(ext) is None:
        raise UnsupportedFormatError(f"Unsupported input format: .{ext}")


def _ignore_invalid_frames(frames):
    iterator = iter(frames)

    while True:
        try:
            yield next(iterator)
        except StopIteration:
            break
        except av.error.InvalidDataError:
            continue


def _group_frames(frames, num_samples=None):
    fifo = av.audio.fifo.AudioFifo()

    for frame in frames:
        frame.pts = None  # 忽略 timestamp 檢查
        fifo.write(frame)

        if num_samples is not None and fifo.samples >= num_samples:
            yield fifo.read()

    if fifo.samples > 0:
        yield fifo.read()


def _resample_frames(frames, resampler):
    for frame in itertools.chain(frames, [None]):
        yield from resampler.resample(frame)


def _iter_audio_frames(
    input_path: Path,
    *,
    sample_rate: int,
    channels: int,
    sample_format: str,
):
    """以 PyAV 解碼並重取樣，產出 AudioFrame 迭代器。"""
    ensure_pyav_available()
    layout = "mono" if channels == 1 else "stereo"
    resampler = av.audio.resampler.AudioResampler(
        format=sample_format,
        layout=layout,
        rate=sample_rate,
    )
    try:
        with av.open(str(input_path), mode="r", metadata_errors="ignore") as container:
            if not container.streams.audio:
                raise RuntimeError("Input has no audio stream.")

            frames = container.decode(audio=0)
            frames = _ignore_invalid_frames(frames)
            frames = _group_frames(frames, 500000)
            yield from _resample_frames(frames, resampler)
    finally:
        del resampler
        gc.collect()


def _decode_pcm_bytes(
    input_path: Path,
    *,
    sample_rate: int,
    channels: int,
) -> bytes:
    raw_buffer = io.BytesIO()
    has_frames = False
    for frame in _iter_audio_frames(
        input_path,
        sample_rate=sample_rate,
        channels=channels,
        sample_format="s16",
    ):
        has_frames = True
        raw_buffer.write(frame.to_ndarray().tobytes())

    if not has_frames:
        raise RuntimeError("No audio frames were decoded.")

    return raw_buffer.getvalue()


def _parse_bitrate(bitrate: str) -> int:
    text = (bitrate or "").strip().lower()
    if not text:
        return 0

    scale = 1
    if text.endswith("k"):
        scale = 1000
        text = text[:-1]

    try:
        value = float(text) * scale
    except ValueError:
        return 0

    return int(value) if value > 0 else 0


def _write_wav_bytes(
    output_target,
    *,
    pcm_bytes: bytes,
    sample_rate: int,
    channels: int,
) -> None:
    with wave.open(output_target, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)  # int16
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)


def _encode_mp3(
    input_path: Path,
    output_target,
    *,
    sample_rate: int,
    channels: int,
    bitrate: str,
) -> None:
    ensure_pyav_available()
    layout = "mono" if channels == 1 else "stereo"
    with av.open(output_target, mode="w", format="mp3") as output:
        stream = output.add_stream("mp3", rate=sample_rate)
        stream.layout = layout

        bit_rate = _parse_bitrate(bitrate)
        if bit_rate:
            stream.bit_rate = bit_rate

        try:
            stream.codec_context.format = "s16p"
        except Exception:
            pass

        target_format = stream.codec_context.format
        resampler = av.audio.resampler.AudioResampler(
            format=target_format.name if target_format else "s16p",
            layout=stream.layout.name if stream.layout else layout,
            rate=sample_rate,
        )
        try:
            with av.open(str(input_path), mode="r", metadata_errors="ignore") as container:
                if not container.streams.audio:
                    raise RuntimeError("Input has no audio stream.")

                frames = container.decode(audio=0)
                frames = _ignore_invalid_frames(frames)
                frames = _group_frames(frames, 500000)
                for frame in _resample_frames(frames, resampler):
                    for packet in stream.encode(frame):
                        output.mux(packet)
                for packet in stream.encode(None):
                    output.mux(packet)
        finally:
            del resampler
            gc.collect()


# -------------------------------------------------------------------------
# 對外 API：輸出檔案
# -------------------------------------------------------------------------

def extract_audio(
    input_path: str | Path,
    output_path: str | Path,
    output_format: str = "mp3",
    sample_rate: int = 48000,
    bitrate: str = "192k",
    channels: int = 2,
) -> Path:
    """從影片/音訊檔抽取音訊並轉檔成指定格式（輸出檔案）。"""
    input_path = Path(input_path)
    output_path = Path(output_path)

    ensure_pyav_available()
    _validate_audio_params(sample_rate, channels)
    _ensure_input_file(input_path)

    output_format = output_format.lower()
    if output_format not in {"mp3", "wav"}:
        raise UnsupportedFormatError(f"Unsupported output format: {output_format}")

    output_file = output_path.with_suffix(f".{output_format}")
    output_file.parent.mkdir(parents=True, exist_ok=True)

    if output_format == "wav":
        pcm_bytes = _decode_pcm_bytes(
            input_path,
            sample_rate=sample_rate,
            channels=channels,
        )
        _write_wav_bytes(
            str(output_file),
            pcm_bytes=pcm_bytes,
            sample_rate=sample_rate,
            channels=channels,
        )
    else:
        _encode_mp3(
            input_path,
            str(output_file),
            sample_rate=sample_rate,
            channels=channels,
            bitrate=bitrate,
        )

    return output_file


# -------------------------------------------------------------------------
# 對外 API：記憶體 bytes
# -------------------------------------------------------------------------

def extract_audio_bytes(
    input_path: str | Path,
    output_format: str = "wav",
    sample_rate: int = 16000,
    channels: int = 1,
    bitrate: str = "192k",
) -> bytes:
    """抽取音訊並回傳 bytes（不落地檔案）。"""
    input_path = Path(input_path)

    ensure_pyav_available()
    _validate_audio_params(sample_rate, channels)
    _ensure_input_file(input_path)

    output_format = output_format.lower()
    if output_format not in {"wav", "mp3"}:
        raise UnsupportedFormatError(f"Unsupported output format: {output_format}")

    if output_format == "wav":
        pcm_bytes = _decode_pcm_bytes(
            input_path,
            sample_rate=sample_rate,
            channels=channels,
        )
        buffer = io.BytesIO()
        _write_wav_bytes(
            buffer,
            pcm_bytes=pcm_bytes,
            sample_rate=sample_rate,
            channels=channels,
        )
        return buffer.getvalue()

    buffer = io.BytesIO()
    _encode_mp3(
        input_path,
        buffer,
        sample_rate=sample_rate,
        channels=channels,
        bitrate=bitrate,
    )
    return buffer.getvalue()


# -------------------------------------------------------------------------
# 對外 API：numpy float32 waveform
# -------------------------------------------------------------------------

def extract_audio_array(
    input_path: str | Path,
    sample_rate: int = 16000,
    channels: int = 1,
):
    """抽取音訊並回傳 numpy float32 waveform（mono）。"""
    ensure_pyav_available()

    try:
        import numpy as np
    except Exception as e:
        raise RuntimeError("使用 extract_audio_array 需要安裝 numpy。") from e

    input_path = Path(input_path)
    _validate_audio_params(sample_rate, channels)
    _ensure_input_file(input_path)

    pcm_bytes = _decode_pcm_bytes(
        input_path,
        sample_rate=sample_rate,
        channels=channels,
    )
    audio_i16 = np.frombuffer(pcm_bytes, dtype=np.int16)
    if audio_i16.size == 0:
        raise RuntimeError("PyAV returned empty audio (the input may have no audio track).")

    if channels > 1:
        frame_count = audio_i16.size // channels
        audio_i16 = audio_i16[: frame_count * channels].reshape(-1, channels).mean(axis=1)

    audio_f32 = audio_i16.astype(np.float32) / 32768.0
    return audio_f32


# -------------------------------------------------------------------------
# CLI 入口
# -------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    from PySide6.QtCore import QObject, Qt, QUrl, Signal, Slot
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
        """背景轉檔工作。"""

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

        @Slot()
        def run(self) -> None:
            try:
                extract_audio(
                    input_path=self.input_path,
                    output_path=self.output_file,
                    output_format=self.output_format,
                    sample_rate=self.sample_rate,
                    bitrate=self.bitrate,
                    channels=self.channels,
                )
                self.finished.emit(self.output_file)
            except Exception as e:
                self.failed.emit(str(e))

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
            self.output_btn = QPushButton("Browse")
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
            self.bitrate_combo.setEnabled(fmt == "mp3")

        def _maybe_update_output_by_format(self, fmt: str) -> None:
            if self._output_customized:
                return
            self.output_edit.setText(str(_default_output_file(self.input_path, fmt)))

        def _browse_output(self) -> None:
            fmt = self.format_combo.currentText()
            suggested = self.output_edit.text().strip() or str(_default_output_file(self.input_path, fmt))
            file_filter = f"{fmt.upper()} (*.{fmt});;All files (*)"
            out_path, _ = QFileDialog.getSaveFileName(self, "Save output as", suggested, file_filter)
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

            progress = QProgressDialog("Converting...", "Cancel", 0, 0, self)
            progress.setWindowTitle("Please wait")
            progress.setWindowModality(Qt.ApplicationModal)
            progress.setCancelButton(None)  # 這裡不支援取消
            progress.show()

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
            threading.Thread(target=self.worker.run, daemon=True).start()

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
