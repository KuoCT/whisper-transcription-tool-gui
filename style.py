from __future__ import annotations
from urllib.parse import quote


# =============================================================================
# Theme Palettes
# =============================================================================
# 這個專案的 QSS（Qt Style Sheet）集中放在這個檔案管理：
# - 主視窗（MainWindow）使用 get_palette() + build_stylesheet()
# - Dialog / Settings 等視窗使用 get_dialog_palette() + build_*_dialog_stylesheet()
#
# 這樣可以避免顏色/圓角/按鈕樣式散落在各個檔案中，後續要改 UI 只需改這裡。


def get_palette(theme: str) -> dict[str, str]:
    """根據主題返回主視窗用調色板"""
    if (theme or "").lower() == "light":
        return {
            "window_bg": "#f6f7fb",
            "text": "#121417",
            "panel_bg": "#ffffff",
            "border": "#c7ccd6",
            "hint": "#5a6370",
            "accent": "#ccd9f7",
            "button_bg": "#e8eaed",
            "button_hover": "#d2d5da",
        }

    return {
        "window_bg": "#0f1115",
        "text": "#e6e6e6",
        "panel_bg": "#151923",
        "border": "#3b3f4a",
        "hint": "#a6abb8",
        "accent": "#395191",
        "button_bg": "#1f2329",
        "button_hover": "#2a2f38",
    }


def build_stylesheet(pal: dict[str, str]) -> str:
    """構建主視窗 Qt 樣式表"""
    return f"""
        QWidget {{
            background: {pal["window_bg"]};
            color: {pal["text"]};
            font-size: 14px;
        }}
        QLabel {{
            background: transparent;
        }}
        #DropLabel {{
            font-size: 18px;
            font-weight: 600;
        }}
        #DropHint, #StatusLabel {{
            color: {pal["hint"]};
        }}
        QPushButton {{
            background: {pal["button_bg"]};
            color: {pal["text"]};
            border: 1px solid {pal["border"]};
            border-radius: 6px;
            padding: 8px 16px;
            font-size: 13px;
        }}
        QPushButton:hover {{
            background: {pal["button_hover"]};
        }}
        QPushButton:pressed {{
            background: {pal["border"]};
        }}
        QMessageBox {{
            background: {pal["panel_bg"]};
        }}
        QMessageBox QPushButton {{
            min-width: 80px;
            border: 1px solid {pal["border"]};
            border-radius: 4px;
            padding: 6px 12px;
        }}
    """


# =============================================================================
# Dialog Palettes / Styles
# =============================================================================

def get_dialog_palette(theme: str) -> dict[str, str]:
    """對話框（Settings / Popup 等）使用的調色板。

    注意：
    - 這裡維持原本 dialogs.py 的配色邏輯（避免影響主視窗現有配色）
    - 未來若要更一致，可再把主視窗 get_palette() 與這裡做整合
    """
    if (theme or "").lower() == "light":
        return {
            "bg": "#ffffff",
            "text": "#121417",
            "border": "#c7ccd6",
            "input_bg": "#f6f7fb",
            "hover": "#e8eaed",
            # light theme 原本 primary/selection 色是深色，較符合「現代扁平」按鈕風格
            "accent": "#2a2c30",
            "accent_hover": "#3a3d42",
            "hint": "#5a6370",
        }

    return {
        "bg": "#1a1d23",
        "text": "#e6e6e6",
        "border": "#3b3f4a",
        "input_bg": "#252931",
        "hover": "#2a2f38",
        "accent": "#395191",
        "accent_hover": "#4a6ab5",
        "hint": "#a6abb8",
    }


def _svg_check_mark_data_uri(stroke_hex: str = "#ffffff") -> str:
    """產生 CheckBox 勾勾的 SVG data URI。

    用 data URI 的好處：
    - 不用額外放圖片檔案
    - QSS 可直接使用 image: url(...)
    """
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 12 10'>"
        f"<path d='M1 5l3 3 7-7' fill='none' stroke='{stroke_hex}' "
        "stroke-width='2' stroke-linecap='round' stroke-linejoin='round'/>"

        "</svg>"
    )

    # Data URI 的內容建議做 URL encode，避免 `#`, 空白, `<` 等字元造成解析問題
    encoded = quote(svg, safe="")
    return "data:image/svg+xml;utf8," + encoded


def build_transcript_popup_stylesheet(pal: dict[str, str]) -> str:
    """TranscriptPopupDialog 的樣式"""
    return f"""
        QDialog {{
            background: {pal["bg"]};
            color: {pal["text"]};
            font-size: 13px;
        }}
        QTextEdit {{
            background: {pal["input_bg"]};
            border: 1px solid {pal["border"]};
            border-radius: 8px;
            padding: 10px;
            color: {pal["text"]};
            font-family: Consolas, 'Courier New', monospace;
            font-size: 12px;
        }}
        QPushButton {{
            background: {pal["input_bg"]};
            border: 1px solid {pal["border"]};
            border-radius: 6px;
            padding: 8px 12px;
            color: {pal["text"]};
        }}
        QPushButton:hover {{
            border-color: {pal["accent"]};
            background: {pal["hover"]};
        }}
        QPushButton:pressed {{
            background: {pal["accent"]};
            color: #ffffff;
        }}
        QPushButton#primary {{
            background: {pal["accent"]};
            color: #ffffff;
            font-weight: 600;
            border-color: {pal["accent"]};
        }}
        QPushButton#primary:hover {{
            background: {pal["accent_hover"]};
        }}
        QLabel {{
            background: transparent;
        }}
    """


def build_settings_dialog_stylesheet(pal: dict[str, str]) -> str:
    """SettingsDialog 的樣式（含扁平化 CheckBox）"""
    check_svg = _svg_check_mark_data_uri("#ffffff")

    return f"""
        QWidget {{
            background: {pal["bg"]};
            color: {pal["text"]};
            font-size: 13px;
        }}

        /* --- Base controls --- */
        QLabel {{
            background: transparent;
            border: none;
            padding: 2px;
        }}
        QComboBox, QLineEdit, QPushButton {{
            background: {pal["input_bg"]};
            border: 1px solid {pal["border"]};
            border-radius: 6px;
            padding: 8px 12px;
        }}

        QLabel#pathLabel {{
            background: {pal["input_bg"]};
            border: 1px solid {pal["border"]};
            border-radius: 6px;
            padding: 10px 12px;
        }}

        QLabel#separatorLine {{
            background: {pal["border"]};
            border: none;
            padding: 1px;
        }}

        QLabel#hintLabel {{
            color: {pal["hint"]};
        }}

        QComboBox:hover, QLineEdit:hover, QPushButton:hover {{
            border-color: {pal["accent"]};
            background: {pal["hover"]};
        }}
        QLineEdit:focus {{
            border-color: {pal["accent"]};
        }}

        QPushButton:pressed {{
            background: {pal["accent"]};
            color: #ffffff;
        }}
        QPushButton#primary {{
            background: {pal["accent"]};
            color: #ffffff;
            font-weight: 600;
            border-color: {pal["accent"]};
        }}
        QPushButton#primary:hover {{
            background: {pal["accent_hover"]};
        }}

        QComboBox::drop-down {{
            border: none;
            width: 0px;  /* keep original flat look (no arrow) */
        }}
        QComboBox QAbstractItemView {{
            background: {pal["input_bg"]};
            border: 1px solid {pal["border"]};
            selection-background-color: {pal["accent"]};
            selection-color: #ffffff;
        }}

        /* --- Flat checkbox --- */
        QCheckBox {{
            background: transparent;
            spacing: 8px;
            padding: 4px 0px;
        }}
        QCheckBox::indicator {{
            width: 16px;
            height: 16px;
            border-radius: 4px;
            border: 1px solid {pal["border"]};
            background: {pal["input_bg"]};
        }}
        QCheckBox::indicator:hover {{
            border-color: {pal["accent"]};
        }}
        QCheckBox::indicator:checked {{
            border: 1px solid {pal["accent"]};
            background: {pal["accent"]};
            image: url("{check_svg}");
        }}
        QCheckBox::indicator:checked:hover {{
            border: 1px solid {pal["accent_hover"]};
            background: {pal["accent_hover"]};
        }}
        QCheckBox::indicator:disabled {{
            border: 1px solid {pal["border"]};
            background: {pal["hover"]};
            image: none;
        }}
    """
