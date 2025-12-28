import threading
import time


class ModelManager:
    """
    延遲載入 + TTL 自動卸載模型管理器

    重點設計以保持 GUI 響應性：
    - 在執行重操作（import/load model）時不持有鎖
    - 在 GUI 執行緒中，maybe_unload() 永遠不會阻塞等待鎖
    """

    def __init__(self, model_name: str, ttl_seconds: int = 60):
        self._model_name = model_name
        self._ttl_seconds = ttl_seconds

        self._lock = threading.Lock()
        self._model = None
        self._active_jobs = 0
        self._last_used = 0.0

        self._loading = False
        self._loaded_event = threading.Event()

    def update_config(self, model_name: str, ttl_seconds: int):
        """更新模型配置（需要重新載入）"""
        with self._lock:
            if self._model_name != model_name:
                # 模型名稱改變，強制卸載舊模型
                if self._model is not None:
                    old_model = self._model
                    self._model = None
                    # 在鎖外釋放
                    threading.Thread(
                        target=lambda: self._free_model(old_model), daemon=True
                    ).start()
            self._model_name = model_name
            self._ttl_seconds = ttl_seconds

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
                import whisper  # 本地 import：避免在 GUI 執行緒初始化 torch/whisper
                model = whisper.load_model(self._model_name)
            except Exception:
                with self._lock:
                    self._loading = False
                    self._active_jobs = max(0, self._active_jobs - 1)
                    self._last_used = time.monotonic()
                    self._loaded_event.set()
                raise

            with self._lock:
                self._model = model
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
        try:
            if self._model is None:
                return False
            if self._loading:
                return False

            idle_seconds = time.monotonic() - self._last_used
            if self._active_jobs == 0 and idle_seconds >= self._ttl_seconds:
                model_to_free = self._model
                self._model = None
        finally:
            self._lock.release()

        if model_to_free is not None:
            self._free_model(model_to_free)
            return True

        return False

    def force_unload(self) -> bool:
        """強制卸載模型"""
        with self._lock:
            if self._model is None:
                return False
            model_to_free = self._model
            self._model = None

        self._free_model(model_to_free)
        return True
