from __future__ import annotations
import re
from typing import Iterable, List


_BASE_LANGUAGE_CODE_TO_NAME = {
    "af": "afrikaans",
    "am": "amharic",
    "ar": "arabic",
    "as": "assamese",
    "az": "azerbaijani",
    "ba": "bashkir",
    "be": "belarusian",
    "bg": "bulgarian",
    "bn": "bengali",
    "bo": "tibetan",
    "br": "breton",
    "bs": "bosnian",
    "ca": "catalan",
    "cs": "czech",
    "cy": "welsh",
    "da": "danish",
    "de": "german",
    "el": "greek",
    "en": "english",
    "es": "spanish",
    "et": "estonian",
    "eu": "basque",
    "fa": "persian",
    "fi": "finnish",
    "fo": "faroese",
    "fr": "french",
    "gl": "galician",
    "gu": "gujarati",
    "ha": "hausa",
    "haw": "hawaiian",
    "he": "hebrew",
    "hi": "hindi",
    "hr": "croatian",
    "ht": "haitian creole",
    "hu": "hungarian",
    "hy": "armenian",
    "id": "indonesian",
    "is": "icelandic",
    "it": "italian",
    "ja": "japanese",
    "jw": "javanese",
    "ka": "georgian",
    "kk": "kazakh",
    "km": "khmer",
    "kn": "kannada",
    "ko": "korean",
    "la": "latin",
    "lb": "luxembourgish",
    "ln": "lingala",
    "lo": "lao",
    "lt": "lithuanian",
    "lv": "latvian",
    "mg": "malagasy",
    "mi": "maori",
    "mk": "macedonian",
    "ml": "malayalam",
    "mn": "mongolian",
    "mr": "marathi",
    "ms": "malay",
    "mt": "maltese",
    "my": "myanmar",
    "ne": "nepali",
    "nl": "dutch",
    "nn": "nynorsk",
    "no": "norwegian",
    "oc": "occitan",
    "pa": "punjabi",
    "pl": "polish",
    "ps": "pashto",
    "pt": "portuguese",
    "ro": "romanian",
    "ru": "russian",
    "sa": "sanskrit",
    "sd": "sindhi",
    "si": "sinhala",
    "sk": "slovak",
    "sl": "slovenian",
    "sn": "shona",
    "so": "somali",
    "sq": "albanian",
    "sr": "serbian",
    "su": "sundanese",
    "sv": "swedish",
    "sw": "swahili",
    "ta": "tamil",
    "te": "telugu",
    "tg": "tajik",
    "th": "thai",
    "tk": "turkmen",
    "tl": "tagalog",
    "tr": "turkish",
    "tt": "tatar",
    "uk": "ukrainian",
    "ur": "urdu",
    "uz": "uzbek",
    "vi": "vietnamese",
    "yi": "yiddish",
    "yo": "yoruba",
    "zh": "chinese",
    "yue": "cantonese",
}

_LANGUAGE_ALIASES = {
    "mandarin": "zh",
    "cn": "zh",
    "tw": "zh",
    "hk": "zh",
    "pt-br": "pt",
    "pt-pt": "pt",
}

_AUTO_HINTS = {"auto", "auto detect", "auto-detect", "detect"}


def _normalize_language_key(text: str) -> str:
    return " ".join(text.lower().replace("_", " ").replace("-", " ").split())


def _load_supported_codes() -> set[str]:
    try:
        from faster_whisper.tokenizer import _LANGUAGE_CODES as fw_codes
    except Exception:
        return set(_BASE_LANGUAGE_CODE_TO_NAME)
    return set(fw_codes)


_SUPPORTED_CODES = _load_supported_codes()

LANGUAGE_CODE_TO_NAME = {
    code: name
    for code, name in _BASE_LANGUAGE_CODE_TO_NAME.items()
    if code in _SUPPORTED_CODES
}

_LANGUAGE_NAME_TO_CODE = {
    _normalize_language_key(name): code
    for code, name in LANGUAGE_CODE_TO_NAME.items()
}
for alias, code in _LANGUAGE_ALIASES.items():
    if code in _SUPPORTED_CODES:
        _LANGUAGE_NAME_TO_CODE[_normalize_language_key(alias)] = code


def parse_language_hint(text: str) -> List[str]:
    """解析語言提示，回傳語言代碼清單。"""
    raw = (text or "").strip()
    if not raw:
        return []

    tokens = [t.strip() for t in re.split(r"[,\uFF0C]", raw) if t.strip()]
    codes: List[str] = []
    for token in tokens:
        norm = _normalize_language_key(token)
        if not norm or norm in _AUTO_HINTS:
            continue

        if norm in _SUPPORTED_CODES:
            code = norm
        else:
            code = _LANGUAGE_NAME_TO_CODE.get(norm, "")

        if code and code not in codes:
            codes.append(code)

    return codes


def is_auto_language_hint(text: str) -> bool:
    """判斷是否為自動偵測提示。"""
    raw = (text or "").strip()
    if not raw:
        return True

    tokens = [t.strip() for t in re.split(r"[,\uFF0C]", raw) if t.strip()]
    if not tokens:
        return True

    return all(_normalize_language_key(token) in _AUTO_HINTS for token in tokens)


def format_language_hint(codes: Iterable[str]) -> str:
    """將語言代碼清單轉成設定字串。"""
    return ", ".join([c for c in codes if c])


def get_language_name(code: str) -> str:
    """取得語言代碼對應名稱（沒有就回傳空字串）。"""
    return LANGUAGE_CODE_TO_NAME.get((code or "").strip().lower(), "")


def format_language_label(code: str) -> str:
    """輸出可讀的顯示格式。"""
    if not code:
        return ""
    name = get_language_name(code)
    return f"{name} ({code})" if name else code
