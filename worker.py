from __future__ import annotations
import traceback
from pathlib import Path
from PySide6.QtCore import QObject, Signal


class TranscribeWorker(QObject):
    """背景工作執行緒的工作器（不落地音訊 → whisper）。

    支援兩種輸入來源：
    1) input_path：從檔案抽取音訊（audio_extract.py）
    2) audio：直接給 numpy float32 waveform（例如錄音功能）
    """

    progress = Signal(str)
    finished = Signal(dict)
    error = Signal(str, str)

    def __init__(
        self,
        *,
        input_path: Path | None = None,
        audio=None,
        model_manager=None,
        language_hint: str = "",
        display_name: str | None = None,
        output_stem: str | None = None,
    ):
        super().__init__()
        self.input_path = input_path
        self.audio = audio
        self.model_manager = model_manager
        self.language_hint = (language_hint or "").strip()
        self.display_name = (display_name or "").strip() or None
        self.output_stem = (output_stem or "").strip() or None

        if self.input_path is None and self.audio is None:
            raise ValueError("TranscribeWorker requires either input_path or audio.")

    def run(self):
        """執行轉錄流程"""
        try:
            audio = self.audio

            if audio is None:
                if self.input_path is None:
                    raise ValueError("input_path is missing.")
                self.progress.emit("Extracting audio...")

                # 不落地抽取：直接產生 float32 waveform
                # 延遲載入：避免在 GUI 啟動時就因 ffmpeg/numpy 問題而失敗
                from audio_extract import extract_audio_array

                audio = extract_audio_array(self.input_path, sample_rate=16000, channels=1)

            self.progress.emit("Loading model & transcribing...")
            model = self.model_manager.acquire()
            try:
                transcribe_kwargs = {
                    "task": "transcribe",
                    "verbose": False,
                }
                if self.language_hint:
                    transcribe_kwargs["language"] = self.language_hint

                result = model.transcribe(
                    audio,
                    **transcribe_kwargs,
                )
            finally:
                self.model_manager.release()

            input_path_str = str(self.input_path) if self.input_path else ""
            display_name = self.display_name
            if not display_name:
                display_name = self.input_path.name if self.input_path else "Recording"

            output_stem = self.output_stem
            if not output_stem:
                output_stem = self.input_path.stem if self.input_path else "recording"

            payload = {
                "input_path": input_path_str,
                "display_name": display_name,
                "output_stem": output_stem,
                "text": (result.get("text") or ""),
                "segments": result.get("segments") or [],
            }
            self.finished.emit(payload)
        except Exception as exc:
            # UI 端會把錯誤主訊息與 traceback 分開顯示，避免重複且更好閱讀
            message = str(exc).strip() or exc.__class__.__name__
            tb = traceback.format_exc().strip()
            self.error.emit(message, tb)
