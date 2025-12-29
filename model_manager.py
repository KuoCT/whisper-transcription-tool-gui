import threading
import time


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
        cache_ram_ratio: float = 1.5,
    ):
        self._model_name = model_name
        self._ttl_seconds = ttl_seconds
        self._auto_cache_ram = bool(auto_cache_ram)
        self._cache_ram_ratio = float(cache_ram_ratio)

        self._lock = threading.Lock()
        self._model = None
        self._model_size_bytes = 0
        self._cached_cpu = False
        self._active_jobs = 0
        self._last_used = 0.0

        self._loading = False
        self._loaded_event = threading.Event()

    def update_config(self, model_name: str, ttl_seconds: int, *, auto_cache_ram: bool):
        """更新模型配置（需要重新載入）"""
        model_to_free = None
        with self._lock:
            if self._model_name != model_name:
                # 模型名稱改變，強制卸載舊模型
                if self._model is not None:
                    model_to_free = self._model
                    self._model = None
                    self._cached_cpu = False
                    self._model_size_bytes = 0
            self._model_name = model_name
            self._ttl_seconds = ttl_seconds
            self._auto_cache_ram = bool(auto_cache_ram)

            if (not self._auto_cache_ram) and self._cached_cpu and self._model is not None:
                model_to_free = self._model
                self._model = None
                self._cached_cpu = False
                self._model_size_bytes = 0

        if model_to_free is not None:
            threading.Thread(
                target=lambda: self._free_model(model_to_free), daemon=True
            ).start()

    def _is_cuda_available(self) -> bool:
        try:
            import torch
            return torch.cuda.is_available()
        except Exception:
            return False

    def _preferred_device(self) -> str:
        return "cuda" if self._is_cuda_available() else "cpu"

    def _estimate_model_bytes(self, model) -> int:
        """估算模型佔用的權重大小（用於 RAM 快取判斷）。"""
        total = 0
        try:
            for param in model.parameters():
                total += param.numel() * param.element_size()
            for buf in model.buffers():
                total += buf.numel() * buf.element_size()
        except Exception:
            return 0
        return int(total)

    def _can_cache_in_ram(self) -> bool:
        if not self._auto_cache_ram:
            return False
        if not self._is_cuda_available():
            return False
        if self._model_size_bytes <= 0:
            return False
        try:
            import psutil
            available = int(psutil.virtual_memory().available)
        except Exception:
            return False
        required = int(self._model_size_bytes * self._cache_ram_ratio)
        return available >= required

    def _move_model_to_cpu(self, model) -> None:
        try:
            import torch
            model.to("cpu")
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    def _move_model_to_cuda(self, model) -> bool:
        try:
            import torch
            if not torch.cuda.is_available():
                return False
            model.to("cuda")
            return True
        except Exception:
            return False

    def _free_model(self, model):
        """釋放模型資源"""
        del model
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    def acquire(self):
        """取得模型（如需要會延遲載入）"""
        need_load = False
        need_promote = False
        model_ref = None

        with self._lock:
            self._active_jobs += 1
            self._last_used = time.monotonic()

            if self._model is not None:
                if self._cached_cpu:
                    if not self._loading:
                        self._loading = True
                        self._loaded_event.clear()
                        need_promote = True
                        model_ref = self._model
                else:
                    return self._model

            if self._model is None and not self._loading:
                self._loading = True
                self._loaded_event.clear()
                need_load = True

        if need_promote and model_ref is not None:
            promoted = self._move_model_to_cuda(model_ref)
            with self._lock:
                if self._model is model_ref:
                    self._cached_cpu = not promoted
                self._loading = False
                self._last_used = time.monotonic()
                self._loaded_event.set()
                if self._model is not None:
                    return self._model

        if need_load:
            try:
                import whisper  # 本地 import：避免在 GUI 執行緒初始化 torch/whisper
                model = whisper.load_model(self._model_name, device=self._preferred_device())
                model_size = self._estimate_model_bytes(model)
            except Exception:
                with self._lock:
                    self._loading = False
                    self._active_jobs = max(0, self._active_jobs - 1)
                    self._last_used = time.monotonic()
                    self._loaded_event.set()
                raise

            with self._lock:
                self._model = model
                self._model_size_bytes = model_size
                self._cached_cpu = False
                self._loading = False
                self._last_used = time.monotonic()
                self._loaded_event.set()
                return self._model

        self._loaded_event.wait()

        model_ref = None
        with self._lock:
            if self._model is None:
                self._active_jobs = max(0, self._active_jobs - 1)
                self._last_used = time.monotonic()
                raise RuntimeError("Model loading failed or was cancelled.")
            if self._cached_cpu and not self._loading:
                self._loading = True
                self._loaded_event.clear()
                model_ref = self._model
            else:
                return self._model

        if model_ref is not None:
            promoted = self._move_model_to_cuda(model_ref)
            with self._lock:
                if self._model is model_ref:
                    self._cached_cpu = not promoted
                self._loading = False
                self._last_used = time.monotonic()
                self._loaded_event.set()
                if self._model is None:
                    self._active_jobs = max(0, self._active_jobs - 1)
                    self._last_used = time.monotonic()
                    raise RuntimeError("Model loading failed or was cancelled.")
                return self._model

    def release(self):
        """釋放模型使用權"""
        with self._lock:
            self._active_jobs = max(0, self._active_jobs - 1)
            self._last_used = time.monotonic()

    def maybe_unload(self) -> bool:
        """如果閒置超過 TTL 則卸載模型（非阻塞）"""
        acquired = self._lock.acquire(blocking=False)
        if not acquired:
            return False

        model_to_free = None
        model_to_cpu = None
        should_demote = False
        try:
            if self._model is None:
                return False
            if self._loading:
                return False
            if self._ttl_seconds < 0:
                return False

            idle_seconds = time.monotonic() - self._last_used
            if self._active_jobs == 0 and idle_seconds >= self._ttl_seconds:
                if self._cached_cpu:
                    if not self._can_cache_in_ram():
                        model_to_free = self._model
                        self._model = None
                        self._cached_cpu = False
                        self._model_size_bytes = 0
                else:
                    if self._can_cache_in_ram():
                        if not self._loading:
                            self._loading = True
                            self._loaded_event.clear()
                            self._cached_cpu = True
                            model_to_cpu = self._model
                            should_demote = True
                    else:
                        model_to_free = self._model
                        self._model = None
                        self._cached_cpu = False
                        self._model_size_bytes = 0
        finally:
            self._lock.release()

        if should_demote and model_to_cpu is not None:
            threading.Thread(
                target=self._finish_demote_to_cpu,
                args=(model_to_cpu,),
                daemon=True,
            ).start()
            return True

        if model_to_free is not None:
            self._free_model(model_to_free)
            return True

        return False

    def _finish_demote_to_cpu(self, model) -> None:
        """在背景執行 CPU demote，避免阻塞 GUI。"""
        self._move_model_to_cpu(model)
        with self._lock:
            self._loading = False
            self._loaded_event.set()

    def force_unload(self) -> bool:
        """強制卸載模型"""
        with self._lock:
            if self._model is None:
                return False
            model_to_free = self._model
            self._model = None
            self._cached_cpu = False
            self._model_size_bytes = 0

        self._free_model(model_to_free)
        return True
