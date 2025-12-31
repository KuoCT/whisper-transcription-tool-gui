import gc
import threading
import time
from pathlib import Path

from cuda_utils import (
    cuda_runtime_available,
    get_cuda_dll_dir,
    has_nvidia_gpu,
    prepare_cuda_dlls,
)


MODEL_REPO_IDS = {
    "tiny": "Systran/faster-whisper-tiny",
    "base": "Systran/faster-whisper-base",
    "small": "Systran/faster-whisper-small",
    "medium": "Systran/faster-whisper-medium",
    "distil-large-v3": "Systran/faster-distil-whisper-large-v3",
    "large-v3": "Systran/faster-whisper-large-v3",
    "large": "Systran/faster-whisper-large-v3",
    "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
    "turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
}


class ModelManager:
    """
    延遲載入 + TTL 自動卸載模型管理器

    重點設計以保持 GUI 響應性：
    - 在執行重操作（import/load model）時不持有鎖
    - 在 GUI 執行緒中，maybe_unload() 永遠不會阻塞等待鎖
    """

    def __init__(
        self,
        model_name: str,
        ttl_seconds: int = 60,
        *,
        auto_cache_ram: bool = True,
        device_preference: str = "auto",
        compute_type: str = "auto",
        cpu_threads: int = 0,
        num_workers: int = 1,
        download_root: Path | None = None,
    ):
        self._model_name = model_name
        self._ttl_seconds = int(ttl_seconds)
        self._auto_cache_ram = bool(auto_cache_ram)
        self._device_preference = (device_preference or "auto").strip().lower()
        self._compute_type = (compute_type or "auto").strip().lower()
        self._cpu_threads = max(0, int(cpu_threads))
        self._num_workers = max(1, int(num_workers))

        base_dir = Path(__file__).resolve().parent
        self._download_root = Path(download_root) if download_root else (base_dir / "cache" / "whisper")

        self._lock = threading.Lock()
        self._model = None
        self._model_device = ""
        self._active_jobs = 0
        self._last_used = 0.0

        self._loading = False
        self._loaded_event = threading.Event()

    def update_config(
        self,
        model_name: str,
        ttl_seconds: int,
        *,
        auto_cache_ram: bool,
        device_preference: str,
        compute_type: str,
        cpu_threads: int,
        num_workers: int,
    ) -> None:
        """更新模型配置（需要重新載入）。"""
        model_to_free = None
        with self._lock:
            updated = False

            if self._model_name != model_name:
                updated = True
                self._model_name = model_name

            ttl_seconds = int(ttl_seconds)
            if self._ttl_seconds != ttl_seconds:
                self._ttl_seconds = ttl_seconds

            auto_cache_ram = bool(auto_cache_ram)
            if self._auto_cache_ram != auto_cache_ram:
                self._auto_cache_ram = auto_cache_ram

            device_preference = (device_preference or "auto").strip().lower()
            if self._device_preference != device_preference:
                updated = True
                self._device_preference = device_preference

            compute_type = (compute_type or "auto").strip().lower()
            if self._compute_type != compute_type:
                updated = True
                self._compute_type = compute_type

            cpu_threads = max(0, int(cpu_threads))
            if self._cpu_threads != cpu_threads:
                updated = True
                self._cpu_threads = cpu_threads

            num_workers = max(1, int(num_workers))
            if self._num_workers != num_workers:
                updated = True
                self._num_workers = num_workers

            if updated and self._model is not None:
                model_to_free = self._model
                self._model = None
                self._model_device = ""

        if model_to_free is not None:
            threading.Thread(
                target=lambda: self._free_model(model_to_free),
                daemon=True,
            ).start()

    def _resolve_device(self) -> str:
        pref = self._device_preference
        if pref not in {"auto", "cpu", "cuda"}:
            pref = "auto"

        if pref == "cpu":
            return "cpu"

        if self._can_use_cuda_for_model():
            return "cuda"

        return "cpu"

    def _resolve_compute_type(self, device: str) -> str:
        compute = self._compute_type
        if compute in {"", "auto", "default"}:
            return "default"

        if device == "cpu" and compute in {"float16", "int8_float16"}:
            return "int8"

        return compute

    def _maybe_download_model(self) -> None:
        repo_id = MODEL_REPO_IDS.get(self._model_name, "")
        if not repo_id:
            return

        cache_dir = self._download_root / f"models--{repo_id.replace('/', '--')}"
        if cache_dir.exists():
            return

        try:
            print(f"Downloading model: {repo_id}")
            from huggingface_hub import snapshot_download

            snapshot_download(
                repo_id=repo_id,
                cache_dir=str(self._download_root),
                resume_download=True,
            )
        except Exception:
            # 下載失敗交給 WhisperModel 自行處理
            pass

    def _can_use_cuda_for_model(self) -> bool:
        dll_dir = get_cuda_dll_dir()
        if not has_nvidia_gpu():
            return False
        if not cuda_runtime_available(dll_dir):
            return False

        return True

    def _free_model(self, model) -> None:
        """釋放模型記憶體。"""
        try:
            del model
        finally:
            gc.collect()

    def _load_model_for_device(self, device: str):
        compute_type = self._resolve_compute_type(device)
        if device == "cuda":
            prepare_cuda_dlls(get_cuda_dll_dir())

        self._maybe_download_model()

        from whisper_hinted import HintedWhisperModel  # 延遲 import，避免啟動時載入過慢

        return HintedWhisperModel(
            self._model_name,
            device=device,
            compute_type=compute_type,
            cpu_threads=self._cpu_threads,
            num_workers=self._num_workers,
            download_root=str(self._download_root),
        )

    def acquire(self):
        """取得模型（如需要會延遲載入）。"""
        need_load = False

        with self._lock:
            self._active_jobs += 1
            self._last_used = time.monotonic()

            if self._model is not None:
                return self._model

            if not self._loading:
                self._loading = True
                self._loaded_event.clear()
                need_load = True

        if need_load:
            try:
                device = self._resolve_device()
                try:
                    model = self._load_model_for_device(device)
                except Exception as exc:
                    if self._device_preference == "auto" and device == "cuda":
                        print(f"CUDA load failed ({exc}); falling back to CPU.")
                        device = "cpu"
                        model = self._load_model_for_device(device)
                    else:
                        raise

            except Exception:
                with self._lock:
                    self._loading = False
                    self._active_jobs = max(0, self._active_jobs - 1)
                    self._last_used = time.monotonic()
                    self._loaded_event.set()
                raise

            with self._lock:
                self._model = model
                self._model_device = device
                self._loading = False
                self._last_used = time.monotonic()
                self._loaded_event.set()
                return self._model

        self._loaded_event.wait()

        with self._lock:
            if self._model is None:
                self._active_jobs = max(0, self._active_jobs - 1)
                self._last_used = time.monotonic()
                raise RuntimeError("Model loading failed or was cancelled.")
            return self._model

    def release(self) -> None:
        """釋放模型使用權。"""
        with self._lock:
            self._active_jobs = max(0, self._active_jobs - 1)
            self._last_used = time.monotonic()

    def maybe_unload(self) -> bool:
        """如果閒置超過 TTL 則卸載模型（非阻塞）。"""
        if self._auto_cache_ram and self._model_device == "cpu":
            return False

        acquired = self._lock.acquire(blocking=False)
        if not acquired:
            return False

        model_to_free = None
        try:
            if self._model is None:
                return False
            if self._loading:
                return False
            if self._ttl_seconds < 0:
                return False

            idle_seconds = time.monotonic() - self._last_used
            if self._active_jobs == 0 and idle_seconds >= self._ttl_seconds:
                model_to_free = self._model
                self._model = None
                self._model_device = ""
        finally:
            self._lock.release()

        if model_to_free is not None:
            self._free_model(model_to_free)
            return True

        return False

    def force_unload(self) -> bool:
        """強制卸載模型。"""
        with self._lock:
            if self._model is None:
                return False
            model_to_free = self._model
            self._model = None
            self._model_device = ""

        self._free_model(model_to_free)
        return True
