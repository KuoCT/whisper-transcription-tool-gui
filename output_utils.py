from __future__ import annotations
from pathlib import Path


SENTENCE_ENDINGS = {"。", "！", "？", "!", "?", "."}
PUNCT_ENDINGS = {"。", "！", "？", "!", "?", ".", "，", ",", "、", "；", ";", "：", ":", "…"}
PAUSE_SENTENCE_THRESHOLD = 0.8


def _is_cjk_char(ch: str) -> bool:
    code = ord(ch)
    return (
        0x4E00 <= code <= 0x9FFF  # CJK Unified Ideographs
        or 0x3400 <= code <= 0x4DBF  # CJK Extension A
        or 0x3040 <= code <= 0x30FF  # Hiragana/Katakana
        or 0xAC00 <= code <= 0xD7AF  # Hangul
    )


def _is_cjk_dominant(text: str) -> bool:
    """判斷文字是否以 CJK 為主，避免英文被錯誤補標點。"""
    if not text:
        return False

    cjk_count = 0
    latin_count = 0
    for ch in text:
        if _is_cjk_char(ch):
            cjk_count += 1
        elif ch.isalpha():
            latin_count += 1

    total = cjk_count + latin_count
    if total <= 0:
        return False
    if cjk_count <= 0:
        return False
    return (cjk_count / total) >= 0.2


def _last_visible_char(text: str) -> str:
    for ch in reversed(text or ""):
        if ch.isspace():
            continue
        return ch
    return ""


def _ends_with_any(text: str, chars: set[str]) -> bool:
    return _last_visible_char(text) in chars


def _normalize_segment_text(text: str) -> str:
    return (text or "").strip()


def _collect_segments(segments: list[dict]) -> list[tuple[str, float, float]]:
    cleaned: list[tuple[str, float, float]] = []
    for seg in segments or []:
        raw_text = _normalize_segment_text(seg.get("text") or "")
        if not raw_text:
            continue
        try:
            start = float(seg.get("start", 0.0))
            end = float(seg.get("end", start))
        except Exception:
            start = 0.0
            end = 0.0
        cleaned.append((raw_text, start, end))
    return cleaned


def format_transcript(text: str, segments: list[dict]) -> str:
    """將轉錄結果做智慧換行/補標點，優先使用 segment 資訊。"""
    cleaned = _collect_segments(segments)
    if not cleaned:
        return text or ""

    sample_text = (text or "") + "".join(seg_text for seg_text, _, _ in cleaned)
    is_cjk = _is_cjk_dominant(sample_text)

    parts: list[str] = []
    for idx, (seg_text, _, end) in enumerate(cleaned):
        next_start = cleaned[idx + 1][1] if idx + 1 < len(cleaned) else None
        gap = (next_start - end) if next_start is not None else 0.0

        has_sentence_punct = _ends_with_any(seg_text, SENTENCE_ENDINGS)
        is_sentence_break = (
            idx == len(cleaned) - 1
            or gap >= PAUSE_SENTENCE_THRESHOLD
            or has_sentence_punct
        )

        if is_cjk and not _ends_with_any(seg_text, PUNCT_ENDINGS):
            seg_text += "。" if is_sentence_break else "，"

        parts.append(seg_text)
        if idx < len(cleaned) - 1:
            if is_sentence_break:
                parts.append("\n")
            else:
                parts.append("" if is_cjk else " ")

    return "".join(parts).strip()


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
