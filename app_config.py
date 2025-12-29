import json
from pathlib import Path

# 專案資料夾
BASE_DIR = Path(__file__).resolve().parent

# 配置文件路徑
CONFIG_FILE = BASE_DIR / "AppConfig.json"

# 默認配置
DEFAULT_CONFIG = {
    "theme": "light",  # "dark" or "light"
    "model_name": "turbo",  # tiny, base, small, medium, large, turbo
    "model_ttl_seconds": 180,  # 閒置多久後釋放模型 (秒)，-1 表示永不釋放
    "model_cache_in_ram": True,  # Auto Cache in RAM（符合條件才啟用）
    "language_hint": "",  # 語言提示 (留白=自動偵測)

    # 錄音裝置（麥克風）
    # -1 = System Default；其他值為 sounddevice 的 device index
    "input_device": -1,

    "output_dir": str(BASE_DIR / "output"),

    # 輸出選項 (可多選，但至少要選 1 個)
    "output_popup": False,       # 處理完成後彈出視窗顯示結果
    "output_clipboard": False,   # 直接複製到剪貼簿
    "output_txt": True,          # 輸出 .txt
    "output_srt": True,          # 輸出 .srt
    "output_smart_format": True, # 智慧格式（換行/補標點）
}


def load_config() -> dict:
    """載入配置文件"""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
                # 合併默認配置（處理新增的配置項）
                return {**DEFAULT_CONFIG, **(config or {})}
        except Exception as exc:
            print(f"Failed to load config: {exc}")
    return DEFAULT_CONFIG.copy()


def save_config(config: dict) -> None:
    """保存配置文件"""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        print(f"Failed to save config: {exc}")
