from __future__ import annotations
import threading
from collections import deque
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
    - 只列出穩定可用的設備（MME 或 DirectSound API）。
    - 優先使用 MME 以避免重複，若 MME 不可用則使用 DirectSound。
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

    # 取得 Host API 資訊
    hostapis = sd.query_hostapis()
    
    # 找出 MME 和 DirectSound 的 Host API ID
    mme_id = None
    directsound_id = None
    
    for idx, api in enumerate(hostapis):
        api_name = api.get("name", "").lower()
        if "mme" in api_name:
            mme_id = idx
        elif "directsound" in api_name:
            directsound_id = idx
    
    # 優先使用 MME（通常更穩定），若不存在則使用 DirectSound
    preferred_hostapi = mme_id if mme_id is not None else directsound_id
    
    inputs: list[InputDevice] = []

    # 先放一個「System Default」讓使用者好選
    default_name = "System Default"
    if isinstance(default_in, int) and 0 <= default_in < len(devices):
        default_dev_name = devices[default_in].get('name', '')
        if default_dev_name:
            default_name = f"System Default ({default_dev_name})"
    inputs.append(InputDevice(device_id=-1, name=default_name, is_default=True))

    # 用來記錄已添加的設備名稱（去重複）
    seen_names: set[str] = set()

    for idx, dev in enumerate(devices):
        # 過濾條件 1：必須有輸入通道
        if int(dev.get("max_input_channels", 0)) <= 0:
            continue
        
        # 過濾條件 2：只接受指定的 Host API（MME 或 DirectSound）
        hostapi = dev.get("hostapi", -1)
        if preferred_hostapi is not None and hostapi != preferred_hostapi:
            continue
        
        # 過濾條件 3：檢查設備基本資訊是否有效
        default_sr = dev.get("default_samplerate", 0)
        if hostapi < 0 or default_sr <= 0:
            continue
        
        # 取得設備名稱並去重複
        name = str(dev.get("name", f"Input {idx}"))
        
        # 去除重複的設備名稱（同一個物理設備可能有多個 ID）
        if name in seen_names:
            continue
        seen_names.add(name)
        
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
        self._level = 0.0
        self._recent_seconds = 0.6
        self._recent_max_samples = int(self.sample_rate * self._recent_seconds)
        self._recent: deque[Any] = deque()
        self._recent_samples = 0

    @property
    def is_recording(self) -> bool:
        """是否正在錄音（包含 paused 狀態的 stream）。"""
        return self._stream is not None

    @property
    def is_paused(self) -> bool:
        """是否處於暫停狀態。"""
        return bool(self._paused)

    @property
    def level(self) -> float:
        """最近一次音量強度（0.0 ~ 1.0）。"""
        with self._lock:
            return float(self._level)

    def get_recent_samples(self, max_samples: int):
        """取得最近錄音片段（用於即時波形顯示）。"""
        import numpy as np

        with self._lock:
            if not self._recent:
                return np.zeros((0,), dtype=np.float32)
            samples = np.concatenate(list(self._recent), axis=0)

        if max_samples > 0 and samples.size > max_samples:
            samples = samples[-max_samples:]
        return samples.astype(np.float32, copy=False)

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

        import numpy as np

        def _callback(indata, _frames, _time, status):  # noqa: ANN001
            # status 可能包含 under/over run 等訊息；此處不強制拋出
            if self._paused:
                return
            try:
                rms = float(np.sqrt(np.mean(np.square(indata))))
            except Exception:
                rms = 0.0
            if rms < 0.0:
                rms = 0.0
            elif rms > 1.0:
                rms = 1.0
            if indata.ndim == 2:
                mono = indata.mean(axis=1)
            else:
                mono = indata
            with self._lock:
                # 一律 copy：避免 PortAudio buffer 後續被覆寫
                self._chunks.append(indata.copy())
                self._recent.append(mono.copy())
                self._recent_samples += int(mono.shape[0])
                while self._recent_samples > self._recent_max_samples and self._recent:
                    removed = self._recent.popleft()
                    self._recent_samples -= int(removed.shape[0])
                # 簡單平滑，讓 UI 顯示更穩定
                self._level = self._level * 0.65 + rms * 0.35

        self._chunks = []
        self._paused = False
        with self._lock:
            self._level = 0.0
            self._recent.clear()
            self._recent_samples = 0

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
        with self._lock:
            self._level = 0.0

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
                self._level = 0.0
                self._recent.clear()
                self._recent_samples = 0
                return np.zeros((0,), dtype=np.float32)

            audio = np.concatenate(self._chunks, axis=0)
            self._chunks = []
            self._level = 0.0
            self._recent.clear()
            self._recent_samples = 0

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
                self._level = 0.0
                self._recent.clear()
                self._recent_samples = 0
            self._paused = True

if __name__ == "__main__":
    import sounddevice as sd
    
    devices = sd.query_devices()
    default_in, _ = sd.default.device
    
    print("測試哪些設備可以實際開啟錄音...")
    print("=" * 80)
    
    working_devices = []
    
    for idx, dev in enumerate(devices):
        max_in = int(dev.get("max_input_channels", 0))
        if max_in <= 0:
            continue
            
        name = dev.get('name', 'N/A')
        hostapi = dev.get('hostapi', -1)
        
        try:
            hostapi_info = sd.query_hostapis(hostapi)
            hostapi_name = hostapi_info.get('name', 'Unknown')
        except:
            hostapi_name = 'Unknown'
        
        # 測試是否可以開啟
        try:
            test_stream = sd.InputStream(
                device=idx,
                channels=1,
                samplerate=16000,
                blocksize=1024,
            )
            test_stream.close()
            status = "✓ 可用"
            working_devices.append((idx, name, hostapi_name))
        except Exception as e:
            status = f"✗ 失敗: {str(e)[:50]}"
        
        is_default = " [預設]" if idx == default_in else ""
        print(f"{idx:3d} | {hostapi_name:20s} | {status:30s} | {name[:40]}{is_default}")
    
    print("\n" + "=" * 80)
    print(f"總共測試: {sum(1 for d in devices if d.get('max_input_channels', 0) > 0)} 個設備")
    print(f"可用設備: {len(working_devices)} 個")
    print("\n建議只顯示這些可用的設備:")
    for idx, name, api in working_devices:
        print(f"  {idx}: [{api}] {name}")
