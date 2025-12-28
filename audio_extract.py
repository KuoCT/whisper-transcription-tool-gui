"""
audio_extract.py
功能說明：
- 統一抽取/轉換音訊（支援輸出成檔案或純記憶體）
- 需求：系統需已安裝 ffmpeg，並加入 PATH

備註：
- 若你要接 Whisper，建議使用 extract_audio_array()（不落地檔案），回傳 float32 waveform。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional, Set


# =========================
# ffmpeg 檢查
# =========================

@lru_cache(maxsize=1)
def ensure_ffmpeg_available() -> None:
    """確認 ffmpeg 可用；若不可用則直接拋錯。

    需求：你希望「程式一開始」就檢查，因此本模組載入時就會執行一次。
    """
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        raise RuntimeError(
            "找不到 ffmpeg（系統 PATH 內無 ffmpeg）。"
            "請先安裝 ffmpeg 並加入 PATH 後再重試。"
            "安裝方式參考："
            "- Windows: winget install Gyan.FFmpeg 或 choco install ffmpeg"
            "- macOS  : brew install ffmpeg"
            "- Ubuntu : sudo apt-get update && sudo apt-get install -y ffmpeg"
        )

    # 再做一次可執行性驗證（避免 PATH 有殘影或權限問題）
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        raise RuntimeError(
            "偵測到 ffmpeg 路徑，但執行 ffmpeg -version 失敗。"
            "請確認 ffmpeg 安裝正確、具有執行權限，且 PATH 設定無誤。"
        ) from e


# =========================
# 媒體格式登錄表（Registry）
# =========================

@dataclass(frozen=True)
class MediaFormat:
    """描述一種媒體類型（影片 / 音訊）"""

    kind: str  # "video" | "audio"
    extensions: Set[str]


MEDIA_REGISTRY: Dict[str, MediaFormat] = {
    "video": MediaFormat(kind="video", extensions={"mp4", "mkv", "avi", "mov", "webm"}),
    "audio": MediaFormat(kind="audio", extensions={"mp3", "wav", "m4a", "flac", "aac", "ogg"}),
}


# 建立「副檔名 → 媒體類型」的快速查詢表（O(1)）
EXTENSION_TO_KIND: Dict[str, str] = {
    ext: media.kind
    for media in MEDIA_REGISTRY.values()
    for ext in media.extensions
}


def get_media_kind(ext: str) -> Optional[str]:
    """依副檔名判斷媒體類型

    參數：
        ext: 副檔名（可包含或不包含 '.'）

    回傳：
        "video" | "audio" | None
    """
    return EXTENSION_TO_KIND.get(ext.lower().lstrip("."))


# =========================
# 自訂例外
# =========================

class UnsupportedFormatError(Exception):
    """不支援的媒體格式"""


# =========================
# 共用：執行 ffmpeg
# =========================

def _run_ffmpeg(cmd: list[str]) -> None:
    """執行 ffmpeg 指令（統一錯誤訊息格式）。"""
    # Windows：避免跳出 console 視窗（可選）
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            "ffmpeg 轉檔失敗，錯誤訊息：" + (e.stderr or "<no stderr>")
        ) from e


# =========================
# 對外 API：輸出成檔案
# =========================

def extract_audio(
    input_path: str | Path,
    output_path: str | Path,
    output_format: str = "mp3",
    sample_rate: int = 48000,
    bitrate: str = "192k",
    channels: int = 2,
) -> Path:
    """從影片或音訊檔中抽取音訊，並轉成指定格式（輸出成檔案）。

    參數：
        input_path    : 輸入檔案路徑
        output_path   : 輸出檔案路徑（不含副檔名）
        output_format : "mp3" 或 "wav"
        sample_rate   : 取樣率（預設 48000）
        bitrate       : mp3 位元率（僅 mp3 使用）
        channels      : 聲道數（預設 2；若要接 Whisper 建議 1）

    回傳：
        最終輸出的音訊檔 Path
    """
    ensure_ffmpeg_available()

    input_path = Path(input_path)
    output_path = Path(output_path)

    # 檢查輸入檔案是否存在
    if not input_path.exists():
        raise FileNotFoundError(input_path)

    # 判斷輸入媒體類型
    ext = input_path.suffix.lower().removeprefix(".")
    media_kind = get_media_kind(ext)
    if media_kind is None:
        raise UnsupportedFormatError(f"Unsupported input format: .{ext}")

    # 檢查輸出格式
    if output_format not in {"mp3", "wav"}:
        raise UnsupportedFormatError(f"Unsupported output format: {output_format}")

    # 組合輸出檔案路徑
    output_file = output_path.with_suffix(f".{output_format}")

    # 確保輸出資料夾存在
    output_file.parent.mkdir(parents=True, exist_ok=True)

    # ffmpeg 指令組合
    cmd = [
        "ffmpeg",
        "-y",  # 覆寫輸出檔
        "-loglevel",
        "error",  # 減少噪音，只保留錯誤
        "-i",
        str(input_path),
        "-vn",  # 忽略影像（只取音訊）
        "-ar",
        str(sample_rate),
        "-ac",
        str(channels),
    ]

    if output_format == "mp3":
        # 建議使用 -b:a 指定位元率
        cmd += ["-b:a", bitrate]

    cmd.append(str(output_file))

    _run_ffmpeg(cmd)
    return output_file


# =========================
# 對外 API：純記憶體（不落地檔案）
# =========================

def extract_audio_bytes(
    input_path: str | Path,
    output_format: str = "wav",
    sample_rate: int = 16000,
    channels: int = 1,
    bitrate: str = "192k",
) -> bytes:
    """抽取音訊並以 bytes 回傳（不落地檔案）。

    建議用途：
    - 若你想自己處理音訊 bytes（例如傳給其他 API / 存 DB / 傳網路）

    參數：
        output_format: "wav" 或 "mp3"

    回傳：
        音訊 bytes
    """
    ensure_ffmpeg_available()

    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(input_path)

    ext = input_path.suffix.lower().removeprefix(".")
    if get_media_kind(ext) is None:
        raise UnsupportedFormatError(f"Unsupported input format: .{ext}")

    if output_format not in {"wav", "mp3"}:
        raise UnsupportedFormatError(f"Unsupported output format: {output_format}")

    # 透過 pipe:1 把輸出寫到 stdout
    cmd: list[str] = [
        "ffmpeg",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-vn",
        "-ar",
        str(sample_rate),
        "-ac",
        str(channels),
    ]

    if output_format == "wav":
        cmd += ["-f", "wav", "pipe:1"]
    else:
        cmd += ["-f", "mp3", "-b:a", bitrate, "pipe:1"]

    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        p = subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creationflags,
        )
        return p.stdout
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else "<no stderr>"
        raise RuntimeError("ffmpeg 抽取音訊失敗，錯誤訊息：" + stderr) from e


def extract_audio_array(
    input_path: str | Path,
    sample_rate: int = 16000,
    channels: int = 1,
):
    """抽取音訊並回傳為 numpy float32 waveform（不落地檔案）。

    這個函式特別適合接 Whisper：
    - Whisper 的 transcribe 可直接吃 1D float32 waveform（範圍約 -1 ~ 1）。

    回傳：
        np.ndarray (float32), shape=(n_samples,)
    """
    ensure_ffmpeg_available()

    # 延遲載入：避免不需要 numpy 的人也被迫安裝
    try:
        import numpy as np
    except Exception as e:
        raise RuntimeError("使用 extract_audio_array 需要安裝 numpy。") from e

    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(input_path)

    ext = input_path.suffix.lower().removeprefix(".")
    if get_media_kind(ext) is None:
        raise UnsupportedFormatError(f"Unsupported input format: .{ext}")

    # 直接輸出 raw PCM（s16le）到 stdout，避免還要依賴 soundfile/pydub 解析 wav
    cmd = [
        "ffmpeg",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-vn",
        "-ar",
        str(sample_rate),
        "-ac",
        str(channels),
        "-f",
        "s16le",
        "pipe:1",
    ]

    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        p = subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creationflags,
        )
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else "<no stderr>"
        raise RuntimeError("ffmpeg 抽取音訊失敗，錯誤訊息：" + stderr) from e

    # bytes -> int16 -> float32 (-1 ~ 1)
    audio_i16 = np.frombuffer(p.stdout, dtype=np.int16)
    if audio_i16.size == 0:
        raise RuntimeError("ffmpeg 回傳空音訊（可能是輸入檔無音軌或解碼失敗）。")

    if channels > 1:
        # (n_frames, channels) -> 取平均成 mono
        audio_i16 = audio_i16.reshape(-1, channels).mean(axis=1).astype(np.int16)

    audio_f32 = audio_i16.astype(np.float32) / 32768.0
    return audio_f32


# =========================
# 模組載入時就先檢查（符合「程式一開始就檢查」的需求）
# =========================

ensure_ffmpeg_available()


# =========================
# CLI 測試入口
# =========================

if __name__ == "__main__":
    import sys
    import tkinter as tk
    from tkinter import filedialog

    # 建立 tkinter root，但不顯示主視窗
    root = tk.Tk()
    root.withdraw()

    # 從 registry 動態產生檔案過濾條件
    video_exts = MEDIA_REGISTRY["video"].extensions
    audio_exts = MEDIA_REGISTRY["audio"].extensions
    all_exts = sorted(video_exts | audio_exts)

    filetypes = [
        ("Media files", [f"*.{ext}" for ext in all_exts]),
        ("All files", "*.*"),
    ]

    # 開啟檔案選擇視窗
    input_file = filedialog.askopenfilename(
        title="選擇影片或音樂檔",
        filetypes=filetypes,
    )

    # 使用者取消
    if not input_file:
        print("未選擇任何檔案，程式結束")
        raise SystemExit(0)

    input_path = Path(input_file)
    output_base = input_path.with_suffix("")

    def open_folder(path: Path) -> None:
        """跨平台開啟資料夾
        - Windows  : Explorer
        - macOS    : Finder
        - Linux    : xdg-open
        """
        path = path.resolve()
        if not path.exists():
            raise FileNotFoundError(path)

        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)])
        else:
            subprocess.run(["xdg-open", str(path)])

    # 執行音訊抽取（輸出成檔案）
    try:
        output_audio = extract_audio(
            input_path=input_path,
            output_path=output_base,
            output_format="mp3",
        )
        open_folder(output_audio.parent)
        print(f"完成：{output_audio}")
    except Exception as e:
        print(f"錯誤: {e}")
        raise SystemExit(1)
