"""
audio_extract.py
功能說明： 統一轉檔成 mp3 或 wav
需求：系統需已安裝 ffmpeg，並加入 PATH
"""
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, Set, Optional

# 媒體格式登錄表（Registry）
@dataclass(frozen=True)
class MediaFormat:
    """
    描述一種媒體類型（影片 / 音訊）
    """
    kind: str               # "video" | "audio"
    extensions: Set[str]    # {"mp4", "mkv", "mp3", ...}


MEDIA_REGISTRY: Dict[str, MediaFormat] = {
    "video": MediaFormat(
        kind="video",
        extensions={
            "mp4", "mkv", "avi", "mov", "webm"
        }
    ),
    "audio": MediaFormat(
        kind="audio",
        extensions={
            "mp3", "wav", "m4a", "flac", "aac", "ogg"
        }
    ),
}


# 建立「副檔名 → 媒體類型」的快速查詢表（O(1)）
EXTENSION_TO_KIND: Dict[str, str] = {
    ext: media.kind
    for media in MEDIA_REGISTRY.values()
    for ext in media.extensions
}


def get_media_kind(ext: str) -> Optional[str]:
    """
    依副檔名判斷媒體類型

    參數：
        ext: 副檔名（可包含或不包含 '.'）

    回傳：
        "video" | "audio" | None
    """
    return EXTENSION_TO_KIND.get(ext.lower().lstrip("."))

# 自訂例外
class UnsupportedFormatError(Exception):
    """不支援的媒體格式"""
    pass

# ffmpeg 抽取音訊主函式

def extract_audio(
    input_path: str | Path,
    output_path: str | Path,
    output_format: str = "mp3",
    sample_rate: int = 48000,
    bitrate: str = "192k",
) -> Path:
    """
    從影片或音訊檔中抽取音訊，並轉成指定格式

    參數：
    - input_path   : 輸入檔案路徑
    - output_path  : 輸出檔案路徑（不含副檔名）
    - output_format: "mp3" 或 "wav"
    - sample_rate  : 取樣率（預設 48000）
    - bitrate      : mp3 位元率（僅 mp3 使用）

    回傳：最終輸出的音訊檔 Path
    """
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
        "-y",                         # 覆寫輸出檔
        "-i", str(input_path),        # 輸入檔
        "-vn",                        # 忽略影像（只取音訊）
        "-ar", str(sample_rate),      # sample rate
    ]

    if output_format == "mp3":
        cmd += ["-ab", bitrate]

    cmd.append(str(output_file))

    # 執行 ffmpeg，並保留 stderr 以利除錯
    try:
        subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE
            # text=True,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"ffmpeg 轉檔失敗，錯誤訊息：\n{e.stderr}"
        ) from e

    return output_file

if __name__ == "__main__":
    import os
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

    # 輸出檔案（與輸入檔同名，不同副檔名）
    input_path = Path(input_file)
    output_base = input_path.with_suffix("")

    def open_folder(path: Path) -> None:
        """
        跨平台開啟資料夾
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
            subprocess.run(["open", path])
        else:
            subprocess.run(["xdg-open", path])

    # 執行音訊抽取
    try: 
        output_audio = extract_audio(
            input_path=input_path,
            output_path=output_base
        )
        open_folder(output_audio.parent)
    except Exception as e:
        print(f"錯誤: {e}")
        raise SystemExit(0)