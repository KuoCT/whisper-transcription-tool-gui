from __future__ import annotations
import inspect
import sys
import traceback
from pathlib import Path
from PySide6.QtCore import QObject, Signal
from language_utils import format_language_label, parse_language_hint


class TranscribeWorker(QObject):
    """背景工作執行緒的工作器（不落地音訊 → faster-whisper）。

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
        transcribe_options: dict | None = None,
        display_name: str | None = None,
        output_stem: str | None = None,
    ):
        super().__init__()
        self.input_path = input_path
        self.audio = audio
        self.model_manager = model_manager
        self.language_hint = (language_hint or "").strip()
        self.transcribe_options = dict(transcribe_options or {})
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
                # 延遲載入：避免在 GUI 啟動時就因 PyAV/numpy 問題而失敗
                from audio_extract import extract_audio_array

                audio = extract_audio_array(self.input_path, sample_rate=16000, channels=1)

            self.progress.emit("Loading model & transcribing...")
            model = self.model_manager.acquire()
            try:
                language_codes = parse_language_hint(self.language_hint)
                language_hint = language_codes[0] if language_codes else ""

                transcribe_kwargs = {"task": "transcribe"}
                if self.transcribe_options:
                    transcribe_kwargs.update(self.transcribe_options)

                multilingual = bool(transcribe_kwargs.get("multilingual", False))
                if multilingual:
                    transcribe_kwargs["multilingual"] = True
                    transcribe_kwargs.pop("language", None)
                elif language_hint:
                    transcribe_kwargs["language"] = language_hint

                language_for_transcribe = (transcribe_kwargs.get("language") or "").strip()

                # 避免不同 faster-whisper 版本的參數不一致
                try:
                    allowed = set(inspect.signature(model.transcribe).parameters)
                    transcribe_kwargs = {
                        key: value
                        for key, value in transcribe_kwargs.items()
                        if key in allowed
                    }
                except Exception:
                    pass

                segments_iter, info = model.transcribe(
                    audio,
                    **transcribe_kwargs,
                )
            finally:
                self.model_manager.release()

            segments = []
            text_parts = []
            total_seconds = 0.0
            try:
                total_seconds = float(len(audio)) / 16000.0
            except Exception:
                total_seconds = 0.0

            next_threshold = 0
            progress_active = total_seconds > 0
            for seg in segments_iter:
                seg_text = (getattr(seg, "text", "") or "").strip()
                segments.append(
                    {
                        "start": float(getattr(seg, "start", 0.0)),
                        "end": float(getattr(seg, "end", 0.0)),
                        "text": seg_text,
                    }
                )
                text_parts.append(getattr(seg, "text", "") or "")

                if progress_active:
                    try:
                        end_sec = float(getattr(seg, "end", 0.0))
                    except Exception:
                        end_sec = 0.0
                    if total_seconds > 0:
                        percent = int(min(100, (end_sec / total_seconds) * 100))
                        if percent >= next_threshold:
                            self.progress.emit(f"Transcribing... {percent}%")
                            _print_progress(percent)
                            next_threshold = min(100, (int(percent / 5) + 1) * 5)

            if progress_active:
                _print_progress(100)
                sys.stdout.write("\n")
                sys.stdout.flush()

            if not language_for_transcribe:
                _print_detected_language(info, language_codes)

            full_text = "".join(text_parts).strip()

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
                "text": full_text,
                "segments": segments,
            }
            self.finished.emit(payload)
        except Exception as exc:
            # UI 端會把錯誤主訊息與 traceback 分開顯示，避免重複且更好閱讀
            message = str(exc).strip() or exc.__class__.__name__
            tb = traceback.format_exc().strip()
            self.error.emit(message, tb)


def _print_progress(percent: int, *, width: int = 24) -> None:
    """在終端輸出簡易進度條。"""
    try:
        pct = max(0, min(100, int(percent)))
        filled = int(width * (pct / 100))
        bar = "#" * filled + "-" * (width - filled)
        sys.stdout.write(f"\rTranscribing [{bar}] {pct:3d}%")
        sys.stdout.flush()
    except Exception:
        pass


def _print_detected_language(info, hint_codes: list[str] | None = None) -> None:
    """顯示偵測語言"""
    try:
        if info is None:
            return
        code = (getattr(info, "language", "") or "").strip()
        label = format_language_label(code) or code or "unknown"
        prob = getattr(info, "language_probability", None)
        if prob is None:
            sys.stdout.write(f"Detected language: {label}\n")
        else:
            sys.stdout.write(f"Detected language: {label} (p={prob:.2f})\n")
        if hint_codes and len(hint_codes) > 1:
            sys.stdout.write(f"Language hints: {', '.join(hint_codes)}\n")
        sys.stdout.flush()
    except Exception:
        pass

