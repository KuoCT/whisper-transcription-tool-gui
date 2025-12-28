from __future__ import annotations
import traceback
from pathlib import Path
from PySide6.QtCore import QObject, Signal


class TranscribeWorker(QObject):
    """背景工作執行緒的工作器（不落地音訊 → whisper）"""

    progress = Signal(str)
    finished = Signal(dict)
    error = Signal(str, str)

    def __init__(self, input_path: Path, model_manager, language_hint: str = ""):
        super().__init__()
        self.input_path = input_path
        self.model_manager = model_manager
        self.language_hint = (language_hint or "").strip()

    def run(self):
        """執行轉錄流程"""
        try:
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

            payload = {
                "input_path": str(self.input_path),
                "text": (result.get("text") or ""),
                "segments": result.get("segments") or [],
            }
            self.finished.emit(payload)
        except Exception as exc:
            # UI 端會把錯誤主訊息與 traceback 分開顯示，避免重複且更好閱讀
            message = str(exc).strip() or exc.__class__.__name__
            tb = traceback.format_exc().strip()
            self.error.emit(message, tb)
