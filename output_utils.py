from __future__ import annotations

from pathlib import Path


def format_srt_time(t: float) -> str:
    """將時間戳轉換為 SRT 格式"""
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int((t - int(t)) * 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def write_txt(output_dir: Path, stem: str, text: str) -> Path:
    """輸出 txt"""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{stem}.txt"
    path.write_text(text or "", encoding="utf-8")
    return path


def write_srt(output_dir: Path, stem: str, segments: list[dict]) -> Path:
    """輸出 srt"""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{stem}.srt"

    srt_lines: list[str] = []
    for i, seg in enumerate(segments or [], 1):
        start = format_srt_time(float(seg.get("start", 0.0)))
        end = format_srt_time(float(seg.get("end", 0.0)))
        text = (seg.get("text") or "").strip()
        srt_lines.append(f"{i}\n{start} --> {end}\n{text}\n")

    content = "\n".join(srt_lines).strip()
    if content:
        content += "\n"
    path.write_text(content, encoding="utf-8")
    return path
