from __future__ import annotations

import fnmatch
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path


CUDA_DLL_SOURCES = [
    {
        "name": "cublas",
        "url": (
            "https://developer.download.nvidia.com/compute/cuda/redist/"
            "libcublas/windows-x86_64/libcublas-windows-x86_64-12.6.4.1-archive.zip"
        ),
        "dll_globs": [
            "**/cublas64_12.dll",
            "**/cublasLt64_12.dll",
        ],
    },
    {
        "name": "cudart",
        "url": (
            "https://developer.download.nvidia.com/compute/cuda/redist/"
            "cuda_cudart/windows-x86_64/cuda_cudart-windows-x86_64-12.6.77-archive.zip"
        ),
        "dll_globs": [
            "**/cudart64_12.dll",
        ],
    },
    {
        "name": "cudnn",
        "url": (
            "https://developer.download.nvidia.com/compute/cudnn/redist/"
            "cudnn/windows-x86_64/cudnn-windows-x86_64-9.10.2.21_cuda12-archive.zip"
        ),
        "dll_globs": [
            "**/cudnn*.dll",
        ],
    },
]

REQUIRED_DLLS = [
    "cublas64_12.dll",
    "cublasLt64_12.dll",
    "cudart64_12.dll",
    "cudnn64_9.dll",
    "cudnn_ops64_9.dll",
    "cudnn_cnn64_9.dll",
]

_DLL_HANDLES: list[object] = []


def get_base_dir() -> Path:
    return Path(__file__).resolve().parent


def get_cuda_dll_dir(base_dir: Path | None = None) -> Path:
    base = base_dir or get_base_dir()
    return base / "cache" / "dll"


def _find_system_cuda_bins() -> list[Path]:
    candidates: list[Path] = []

    cuda_path = os.environ.get("CUDA_PATH")
    if cuda_path:
        candidates.append(Path(cuda_path) / "bin")

    for key, value in os.environ.items():
        if key.startswith("CUDA_PATH_V") and value:
            candidates.append(Path(value) / "bin")

    seen: set[str] = set()
    bins: list[Path] = []
    for path in candidates:
        resolved = str(path.resolve()) if path.exists() else str(path)
        if resolved in seen:
            continue
        seen.add(resolved)
        bins.append(path)
    return bins


def _has_required_dlls_in_dirs(dirs: list[Path]) -> bool:
    for dll_dir in dirs:
        if all((dll_dir / dll).exists() for dll in REQUIRED_DLLS):
            return True
    return False


def cuda_dlls_present(dll_dir: Path) -> bool:
    """檢查 cache/dll 是否已備齊 CUDA 12 所需 DLL。"""
    return not get_missing_cuda_dlls(dll_dir)


def get_missing_cuda_dlls(dll_dir: Path) -> list[str]:
    """回傳 cache/dll 缺少的 DLL 清單（只檢查 cache）。"""
    if not dll_dir.exists():
        return list(REQUIRED_DLLS)
    _ensure_cudnn_compat_dlls(dll_dir)
    return [name for name in REQUIRED_DLLS if not (dll_dir / name).exists()]


def cuda_runtime_available(dll_dir: Path) -> bool:
    """檢查是否可使用 CUDA（cache/dll 或系統 CUDA）。"""
    if dll_dir.exists():
        _ensure_cudnn_compat_dlls(dll_dir)
    if cuda_dlls_present(dll_dir):
        return True
    return _has_required_dlls_in_dirs(_find_system_cuda_bins())


def prepare_cuda_dlls(dll_dir: Path) -> bool:
    """將 DLL 目錄加入動態載入搜尋路徑（Windows 主要用途）。"""
    if not dll_dir.exists():
        return False

    _ensure_cudnn_compat_dlls(dll_dir)

    dll_path = str(dll_dir.resolve())
    if sys.platform == "win32":
        try:
            handle = os.add_dll_directory(dll_path)
            _DLL_HANDLES.append(handle)
        except Exception:
            pass

        current = os.environ.get("PATH", "")
        if dll_path not in current.split(os.pathsep):
            os.environ["PATH"] = dll_path + os.pathsep + current
        return True

    env_key = "LD_LIBRARY_PATH"
    current = os.environ.get(env_key, "")
    if dll_path not in current.split(os.pathsep):
        os.environ[env_key] = dll_path + os.pathsep + current
    return True


def _download_file(
    url: str,
    dest: Path,
    *,
    label: str = "",
    progress_callback=None,
) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=60) as resp, open(dest, "wb") as f:
        total = 0
        try:
            total = int(resp.headers.get("Content-Length") or 0)
        except Exception:
            total = 0

        downloaded = 0
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)
            downloaded += len(chunk)
            if progress_callback:
                progress_callback(label, downloaded, total)


def _extract_dlls(zip_path: Path, dll_dir: Path, patterns: list[str]) -> list[Path]:
    extracted: list[Path] = []
    normalized = [p.replace("\\", "/").lower() for p in patterns]

    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            norm = member.replace("\\", "/").lower()
            if not any(fnmatch.fnmatch(norm, pat) for pat in normalized):
                continue
            target = dll_dir / Path(member).name
            with zf.open(member) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            extracted.append(target)
    return extracted


def download_cuda_dlls(dll_dir: Path, *, progress_callback=None) -> list[Path]:
    """下載並抽出 CUDA 12 DLL 到 cache/dll。"""
    dll_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix="cuda_dlls_"))
    extracted: list[Path] = []

    try:
        for bundle in CUDA_DLL_SOURCES:
            if progress_callback:
                progress_callback(f"Downloading {bundle['name']}", 0, 0)
            zip_path = temp_dir / f"{bundle['name']}.zip"
            _download_file(
                bundle["url"],
                zip_path,
                label=f"Downloading {bundle['name']}",
                progress_callback=progress_callback,
            )
            if progress_callback:
                progress_callback(f"Extracting {bundle['name']}", 0, 0)
            extracted.extend(_extract_dlls(zip_path, dll_dir, bundle["dll_globs"]))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    _ensure_cudnn_compat_dlls(dll_dir)
    return extracted


def _ensure_cudnn_compat_dlls(dll_dir: Path) -> None:
    """補齊舊版命名的 cuDNN DLL，避免相依性問題。"""
    compat_map = {
        "cudnn_ops64_9.dll": "cudnn_ops_infer64_9.dll",
        "cudnn_cnn64_9.dll": "cudnn_cnn_infer64_9.dll",
    }

    for target, source in compat_map.items():
        target_path = dll_dir / target
        source_path = dll_dir / source
        if target_path.exists():
            continue
        if not source_path.exists():
            continue
        try:
            shutil.copy2(source_path, target_path)
        except Exception:
            pass


def query_nvidia_gpus() -> list[dict]:
    """使用 nvidia-smi 查詢 GPU 資訊。"""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return []

    if result.returncode != 0:
        return []

    gpus: list[dict] = []
    for line in (result.stdout or "").splitlines():
        raw = line.strip()
        if not raw:
            continue
        parts = [p.strip() for p in raw.split(",")]
        if len(parts) < 2:
            continue
        name = parts[0]
        try:
            mem_mb = int(float(parts[1]))
        except Exception:
            mem_mb = 0
        gpus.append({"name": name, "memory_mb": mem_mb})

    return gpus


def get_max_vram_gb() -> float:
    gpus = query_nvidia_gpus()
    if not gpus:
        return 0.0
    max_mb = max(gpu.get("memory_mb", 0) for gpu in gpus)
    return max_mb / 1024.0


def has_nvidia_gpu() -> bool:
    return bool(query_nvidia_gpus())
