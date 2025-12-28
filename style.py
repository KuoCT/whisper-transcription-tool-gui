from __future__ import annotations
from urllib.parse import quote


# =============================================================================
# Theme Palettes
# =============================================================================
# 這個專案的 QSS（Qt Style Sheet）集中放在這個檔案管理，避免顏色/圓角/按鈕樣式
# 散落在各個檔案中，後續要改 UI 只需改這裡。
#
# 使用方式：
# - 主視窗（MainWindow）：get_palette() + build_stylesheet()
# - Dialog / Settings / Popup：get_palette() + build_*_dialog_stylesheet()


def get_palette(theme: str) -> dict[str, str]:
    """依照主題回傳調色板。

    這份 palette 同時供主視窗與各種 Dialog 使用。不同元件會取用不同 key：
    - window_bg / panel_bg：視窗背景與卡片/面板背景
    - input_bg：輸入框/文字框背景
    - button_bg / button_hover：一般按鈕背景與 hover 背景
    - check_bg / check_hover：CheckBox 勾選狀態（只有 checkbox 的 hover 會用到）
    """
    if (theme or "").lower() == "light":
        return {
            "window_bg": "#f6f7fb",
            "text": "#121417",
            "panel_bg": "#ffffff",
            "border": "#c7ccd6",
            "hint": "#5a6370",
            "accent": "#ccd9f7",
            "input_bg": "#f6f7fb",
            "button_bg": "#e8eaed",
            "button_hover": "#d2d5da",
            "check_bg": "#2a2c30",
            "check_hover": "#3a3d42",
        }

    return {
        "window_bg": "#0f1115",
        "text": "#e6e6e6",
        "panel_bg": "#151923",
        "border": "#3b3f4a",
        "hint": "#a6abb8",
        "accent": "#395191",
        "input_bg": "#252931",
        "button_bg": "#1f2329",
        "button_hover": "#2a2f38",
        "check_bg": "#6f89d1",
        "check_hover": "#d7ddf0",
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
# Dialog Styles
# =============================================================================

def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """將 #RRGGBB 轉成 (r, g, b)（0-255）。"""
    hex_color = (hex_color or "").lstrip("#")
    if len(hex_color) != 6:
        return 0, 0, 0
    return int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)


def _is_light_color(hex_color: str) -> bool:
    """粗略判斷顏色是否偏亮，用來選擇較適合的前景色。"""
    r, g, b = _hex_to_rgb(hex_color)
    # 使用簡單亮度（HSP/Perceived brightness 變體即可）
    brightness = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
    return brightness >= 0.6


def _on_color(bg_hex: str, *, light: str = "#121417", dark: str = "#ffffff") -> str:
    """依照背景色選擇文字/線條顏色（亮底用深色、暗底用白色）。"""
    return light if _is_light_color(bg_hex) else dark


def _mix_hex(a: str, b: str, t: float) -> str:
    """把兩個 #RRGGBB 做線性混色：a*(1-t) + b*t。"""
    ar, ag, ab = _hex_to_rgb(a)
    br, bg, bb = _hex_to_rgb(b)
    r = round(ar * (1 - t) + br * t)
    g = round(ag * (1 - t) + bg * t)
    b_ = round(ab * (1 - t) + bb * t)
    return f"#{r:02x}{g:02x}{b_:02x}"


def _dialog_primary_colors(pal: dict[str, str]) -> tuple[str, str]:
    """Dialog 內 primary 按鈕用色。

    原本的 dialogs palette 在 light theme 使用深色 primary；dark theme 使用藍色 primary。
    這裡用統一 palette 的值推回同樣的視覺邏輯：
    - light：primary = check_bg / check_hover
    - dark：primary = accent / accent(加亮後作為 hover)
    """
    is_light_theme = _is_light_color(pal["window_bg"])
    if is_light_theme:
        return pal["check_bg"], pal["check_hover"]

    # dark theme：用 accent 作為 primary，hover 讓顏色稍微亮一點
    return pal["accent"], _mix_hex(pal["accent"], "#ffffff", 0.22)


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


def _build_flat_checkbox_qss(
    *,
    border: str,
    unchecked_bg: str,
    disabled_bg: str,
    check_bg: str,
    check_hover: str,
    check_svg: str,
) -> str:
    """生成可復用的扁平化 CheckBox QSS。

    這個專案多處需要一致的 CheckBox 風格（Settings / Error dialog 等），
    因此把樣式集中在 style.py，避免各檔案重複貼 QSS。
    """
    return f"""
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
            border: 1px solid {border};
            background: {unchecked_bg};
        }}
        QCheckBox::indicator:hover {{
            border-color: {check_bg};
        }}
        QCheckBox::indicator:checked {{
            border: 1px solid {check_bg};
            background: {check_bg};
            image: url("{check_svg}");
        }}
        QCheckBox::indicator:checked:hover {{
            border: 1px solid {check_hover};
            background: {check_hover};
        }}
        QCheckBox::indicator:disabled {{
            border: 1px solid {border};
            background: {disabled_bg};
            image: none;
        }}
    """


def build_error_dialog_stylesheet(pal: dict[str, str]) -> str:
    """Error dialog（可 resize 的 QDialog）樣式。

    這裡沿用主 palette，使 error dialog 與主視窗維持一致的視覺語言；
    同時復用 Settings 相同的 CheckBox 外觀。
    """
    check_svg = _svg_check_mark_data_uri(_on_color(pal["check_bg"]))
    checkbox_qss = _build_flat_checkbox_qss(
        border=pal["border"],
        unchecked_bg=pal["input_bg"],
        disabled_bg=pal["button_hover"],
        check_bg=pal["check_bg"],
        check_hover=pal["check_hover"],
        check_svg=check_svg,
    )
    primary_text = _on_color(pal["accent"], light=pal["text"])

    return f"""
        QDialog {{
            background: {pal["panel_bg"]};
            color: {pal["text"]};
            font-size: 13px;
        }}

        QLabel {{
            background: transparent;
        }}
        QLabel#ErrorTitle {{
            font-size: 15px;
            font-weight: 700;
        }}

        QTextEdit {{
            background: {pal["input_bg"]};
            border: 1px solid {pal["border"]};
            border-radius: 8px;
            padding: 10px;
            color: {pal["text"]};
        }}
        QTextEdit#ErrorDetails {{
            font-family: Consolas, 'Courier New', monospace;
            font-size: 12px;
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
        QPushButton#primary {{
            background: {pal["accent"]};
            color: {primary_text};
            border-color: {pal["accent"]};
            font-weight: 600;
        }}
        QPushButton#primary:hover {{
            background: {pal["button_hover"]};
        }}

        {checkbox_qss}
    """


def build_transcript_popup_stylesheet(pal: dict[str, str]) -> str:
    """TranscriptPopupDialog 的樣式"""
    primary_bg, primary_hover = _dialog_primary_colors(pal)
    primary_text = _on_color(primary_bg, light=pal["text"])
    hover_bg = pal["button_hover"]

    return f"""
        QDialog {{
            background: {pal["panel_bg"]};
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
            background: {pal["button_bg"]};
            border: 1px solid {pal["border"]};
            border-radius: 6px;
            padding: 8px 12px;
            color: {pal["text"]};
        }}
        QPushButton:hover {{
            border-color: {pal["accent"]};
            background: {hover_bg};
        }}
        QPushButton:pressed {{
            background: {primary_bg};
            color: {primary_text};
        }}
        QPushButton#primary {{
            background: {primary_bg};
            color: {primary_text};
            font-weight: 600;
            border-color: {primary_bg};
        }}
        QPushButton#primary:hover {{
            background: {primary_hover};
            border-color: {primary_hover};
        }}
        QLabel {{
            background: transparent;
        }}
    """


def build_settings_dialog_stylesheet(pal: dict[str, str]) -> str:
    """SettingsDialog 的樣式（含扁平化 CheckBox）"""
    primary_bg, primary_hover = _dialog_primary_colors(pal)
    primary_text = _on_color(primary_bg, light=pal["text"])
    hover_bg = pal["button_hover"]

    check_svg = _svg_check_mark_data_uri(_on_color(pal["check_bg"]))
    checkbox_qss = _build_flat_checkbox_qss(
        border=pal["border"],
        unchecked_bg=pal["input_bg"],
        disabled_bg=hover_bg,
        check_bg=pal["check_bg"],
        check_hover=pal["check_hover"],
        check_svg=check_svg,
    )

    return f"""
        QWidget {{
            background: {pal["panel_bg"]};
            color: {pal["text"]};
            font-size: 13px;
        }}

        /* --- Base controls --- */
        QLabel {{
            background: transparent;
            border: none;
            padding: 2px;
        }}

        QComboBox, QLineEdit {{
            background: {pal["input_bg"]};
            border: 1px solid {pal["border"]};
            border-radius: 6px;
            padding: 8px 12px;
        }}
        QPushButton {{
            background: {pal["button_bg"]};
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
            background: {hover_bg};
        }}
        QLineEdit:focus {{
            border-color: {pal["accent"]};
        }}

        QPushButton:pressed {{
            background: {primary_bg};
            color: {primary_text};
        }}
        QPushButton#primary {{
            background: {primary_bg};
            color: {primary_text};
            font-weight: 600;
            border-color: {primary_bg};
        }}
        QPushButton#primary:hover {{
            background: {primary_hover};
            border-color: {primary_hover};
        }}

        QComboBox::drop-down {{
            border: none;
            width: 0px;  /* keep original flat look (no arrow) */
        }}
        QComboBox QAbstractItemView {{
            background: {pal["input_bg"]};
            border: 1px solid {pal["border"]};
            selection-background-color: {primary_bg};
            selection-color: {primary_text};
        }}

        {checkbox_qss}
    """
