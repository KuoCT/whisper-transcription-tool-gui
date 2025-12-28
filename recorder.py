from __future__ import annotations
import threading
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class InputDevice:
    """輸入裝置資訊（給 GUI 下拉選單用）。"""

    device_id: int
    name: str
    is_default: bool = False


def list_input_devices() -> list[InputDevice]:
    """列出可用的「輸入」音訊裝置（麥克風）。

    備註：
    - 這裡使用 sounddevice（PortAudio）列舉裝置。
    - 若 sounddevice 不存在或列舉失敗，會拋出例外，讓上層決定如何降級顯示。
    """
    try:
        import sounddevice as sd  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "Microphone support requires the `sounddevice` package. "
            "Install it with: pip install sounddevice"
        ) from exc

    devices = sd.query_devices()
    default_in, _default_out = sd.default.device

    inputs: list[InputDevice] = []

    # 先放一個「System Default」讓使用者好選
    default_name = "System Default"
    if isinstance(default_in, int) and 0 <= default_in < len(devices):
        default_name = f"System Default ({devices[default_in]['name']})"
    inputs.append(InputDevice(device_id=-1, name=default_name, is_default=True))

    for idx, dev in enumerate(devices):
        if int(dev.get("max_input_channels", 0)) <= 0:
            continue
        name = str(dev.get("name", f"Input {idx}"))
        is_default = (idx == default_in)
        inputs.append(InputDevice(device_id=int(idx), name=name, is_default=is_default))

    return inputs


class AudioRecorder:
    """以「不落地」方式錄音，回傳 float32 waveform（mono）。

    設計重點：
    - 錄音資料只存在記憶體（numpy float32）。
    - 支援 pause/resume：pause 時不再收集 chunk，但 stream 不需要重建。
    - start/stop/reset 皆具備「可重入」保護：避免 UI 多次點擊造成狀態錯亂。
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        blocksize: int = 1024,
    ):
        self.sample_rate = int(sample_rate)
        self.channels = int(channels)
        self.blocksize = int(blocksize)

        self._stream: Any | None = None
        self._chunks: list[Any] = []
        self._paused = True
        self._lock = threading.Lock()

    @property
    def is_recording(self) -> bool:
        """是否正在錄音（包含 paused 狀態的 stream）。"""
        return self._stream is not None

    @property
    def is_paused(self) -> bool:
        """是否處於暫停狀態。"""
        return bool(self._paused)

    def start(self, device_id: int = -1) -> None:
        """開始錄音。

        Args:
            device_id:
                -1 表示使用系統預設輸入裝置；其他值為 sounddevice 的裝置 index。
        """
        if self._stream is not None:
            # 已經有 stream：視為「重新開始」前先 reset
            self.reset()

        # 延遲 import：避免在 GUI 啟動時就因系統音訊/portaudio 問題而失敗
        try:
            import sounddevice as sd  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(
                "Microphone support requires the `sounddevice` package. "
                "Install it with: pip install sounddevice"
            ) from exc

        def _callback(indata, _frames, _time, status):  # noqa: ANN001
            # status 可能包含 under/over run 等訊息；此處不強制拋出
            if self._paused:
                return
            with self._lock:
                # 一律 copy：避免 PortAudio buffer 後續被覆寫
                self._chunks.append(indata.copy())

        self._chunks = []
        self._paused = False

        device = None if int(device_id) < 0 else int(device_id)

        stream = sd.InputStream(
            device=device,
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="float32",
            blocksize=self.blocksize,
            callback=_callback,
        )
        stream.start()
        self._stream = stream

    def pause(self) -> None:
        """暫停錄音（不停止 stream，只停止收集）。"""
        if self._stream is None:
            return
        self._paused = True

    def resume(self) -> None:
        """繼續錄音。"""
        if self._stream is None:
            return
        self._paused = False

    def stop(self):
        """停止錄音並回傳 waveform（numpy float32, shape=(n,)）。"""
        if self._stream is None:
            return None

        stream = self._stream
        self._stream = None
        self._paused = True

        try:
            stream.stop()
        finally:
            try:
                stream.close()
            except Exception:
                pass

        # 延遲 import：避免在 GUI 啟動時就因 numpy 缺失而失敗（雖然專案目前已依賴 numpy）
        import numpy as np

        with self._lock:
            if not self._chunks:
                self._chunks = []
                return np.zeros((0,), dtype=np.float32)

            audio = np.concatenate(self._chunks, axis=0)
            self._chunks = []

        # 若 channels > 1，先做平均到 mono（避免送進 whisper 的形狀不一致）
        if audio.ndim == 2:
            audio = audio.mean(axis=1)

        return audio.astype(np.float32, copy=False)

    def reset(self) -> None:
        """停止並清空當前錄音資料。"""
        try:
            self.stop()
        finally:
            with self._lock:
                self._chunks = []
            self._paused = True
