from __future__ import annotations


# Theme Palettes
# 這個專案的 QSS（Qt Style Sheet）集中放在這個檔案管理，避免顏色/圓角/按鈕樣式
# 散落在各個檔案中，後續要改 UI 只需改這裡。
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
            "panel_bg": "#edf2fa",
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


# -------------------------------------------------------------------------
# QSS Helpers
# -------------------------------------------------------------------------

def _qss_block(selector: str, props: dict[str, str | int | None]) -> str:
    """組合 QSS 區塊，集中管理屬性內容。"""
    lines = [f"{selector} {{"]
    for key, value in props.items():
        if value is None:
            continue
        lines.append(f"    {key}: {value};")
    lines.append("}")
    return "\n".join(lines)


def _build_dialog_base_qss(selector: str, pal: dict[str, str], *, font_size: int = 13) -> str:
    """Dialog/面板基底樣式（背景、字色、字級）。"""
    return _qss_block(
        selector,
        {
            "background": pal["panel_bg"],
            "color": pal["text"],
            "font-size": f"{font_size}px",
        },
    )


def _build_button_base_qss(
    *,
    bg: str,
    text: str | None,
    border: str,
    radius: int,
    padding: str,
    font_size: int | None = None,
    selector: str = "QPushButton",
) -> str:
    """通用按鈕基底樣式（依不同場景調整 padding/字級）。"""
    return _qss_block(
        selector,
        {
            "background": bg,
            "color": text,
            "border": f"1px solid {border}",
            "border-radius": f"{radius}px",
            "padding": padding,
            "font-size": f"{font_size}px" if font_size is not None else None,
        },
    )


def _build_button_primary_qss(
    *,
    bg: str,
    text: str,
    border: str,
    hover_bg: str | None = None,
    hover_border: str | None = None,
    selector: str = "QPushButton#primary",
) -> str:
    """Dialog 內 primary 按鈕樣式（可選 hover）。"""
    blocks = [
        _qss_block(
            selector,
            {
                "background": bg,
                "color": text,
                "border-color": border,
                "font-weight": 600,
            },
        )
    ]
    if hover_bg is not None or hover_border is not None:
        blocks.append(
            _qss_block(
                f"{selector}:hover",
                {
                    "background": hover_bg,
                    "border-color": hover_border,
                },
            )
        )
    return "\n".join(blocks)


def _build_input_base_qss(
    *,
    selectors: str,
    bg: str,
    border: str,
    radius: int,
    padding: str,
) -> str:
    """輸入元件（ComboBox/LineEdit）基底樣式。"""
    return _qss_block(
        selectors,
        {
            "background": bg,
            "border": f"1px solid {border}",
            "border-radius": f"{radius}px",
            "padding": padding,
        },
    )


def _build_text_edit_base_qss(
    *,
    bg: str,
    text: str,
    border: str,
    radius: int = 8,
    padding: str = "10px",
) -> str:
    """TextEdit 基底樣式，供 Error/Popup 共用。"""
    return _qss_block(
        "QTextEdit",
        {
            "background": bg,
            "border": f"1px solid {border}",
            "border-radius": f"{radius}px",
            "padding": padding,
            "color": text,
        },
    )


def _build_text_edit_mono_qss(selector: str, *, font_size: int = 12) -> str:
    """TextEdit 等寬字體設定（mono/font-size）。"""
    return _qss_block(
        selector,
        {
            "font-family": "Consolas, 'Courier New', monospace",
            "font-size": f"{font_size}px",
        },
    )


def build_stylesheet(pal: dict[str, str]) -> str:
    """構建主視窗 Qt 樣式表。

    原則：
    - widgets.py 只負責「結構與行為」，外觀一律由 QSS 控制，避免 style 分散。
    - IconButton 預設背景透明，但保留外框；hover / pressed / checked 用外框變化呈現回饋。
    """
    icon_button_qss = "\n".join(
        [
            _qss_block(
                "QPushButton#IconButton",
                {
                    "background": "transparent",
                    "color": pal["text"],
                    "border": f"1px solid {pal['border']}",
                    "border-radius": "10px",
                    "padding": "0px",
                    "min-width": "42px",
                    "min-height": "42px",
                },
            ),
            _qss_block(
                "QPushButton#IconButton:hover",
                {
                    "background": "transparent",
                    "border-color": pal["accent"],
                },
            ),
            _qss_block(
                "QPushButton#IconButton:pressed",
                {
                    "background": "transparent",
                    "border-color": pal["accent"],
                },
            ),
            _qss_block(
                "QPushButton#IconButton:checked",
                {
                    "background": "transparent",
                    "border": f"2px solid {pal['accent']}",
                },
            ),
            _qss_block(
                "QPushButton#IconButton:checked:hover",
                {
                    "background": "transparent",
                    "border": f"2px solid {pal['accent']}",
                },
            ),
            _qss_block(
                "QPushButton#IconButton:disabled",
                {
                    "background": "transparent",
                    "border-color": pal["border"],
                    "color": pal["hint"],
                },
            ),
        ]
    )

    button_base_qss = _build_button_base_qss(
        bg=pal["button_bg"],
        text=pal["text"],
        border=pal["border"],
        radius=6,
        padding="8px 16px",
        font_size=13,
    )
    button_hover_qss = _qss_block(
        "QPushButton:hover",
        {
            "background": pal["button_hover"],
        },
    )
    button_pressed_qss = _qss_block(
        "QPushButton:pressed",
        {
            "background": pal["border"],
        },
    )

    messagebox_button_qss = _qss_block(
        "QMessageBox QPushButton",
        {
            "min-width": "80px",
            "border": f"1px solid {pal['border']}",
            "border-radius": "4px",
            "padding": "6px 12px",
        },
    )

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

        /* RecordArea 中央區塊：必須透明，否則會被 QWidget 的 window_bg 蓋一層底 */
        #RecordCenterWrap {{
            background: transparent;
        }}

        #RecordTimer {{
            font-size: 24px;
            font-weight: 700;
        }}

        /* 純圖示按鈕：背景透明，但保留外框與互動狀態 */
        {icon_button_qss}

        /* 一般按鈕（不影響 IconButton，因為 IconButton 有更高 selector specificity） */
        {button_base_qss}
        {button_hover_qss}
        {button_pressed_qss}

        QMessageBox {{
            background: {pal["panel_bg"]};
        }}
        {messagebox_button_qss}
    """


# -------------------------------------------------------------------------
# Dialog Styles
# -------------------------------------------------------------------------

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


def _build_flat_checkbox_qss(
    *,
    border: str,
    unchecked_bg: str,
    disabled_bg: str,
    check_bg: str,
    check_hover: str
) -> str:
    """生成可復用的扁平化 CheckBox QSS。"""
    return f"""
        /* --- Flat checkbox --- */
        QCheckBox {{
            background: transparent;
            spacing: 8px;
            padding: 4px 0px;
        }}
        QCheckBox::indicator {{
            width: 18px;
            height: 18px;
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


def _build_checkbox_qss_from_palette(pal: dict[str, str], *, disabled_bg: str) -> str:
    """從 palette 組合 CheckBox QSS，集中管理顏色對應。"""
    return _build_flat_checkbox_qss(
        border=pal["border"],
        unchecked_bg=pal["input_bg"],
        disabled_bg=disabled_bg,
        check_bg=pal["check_bg"],
        check_hover=pal["check_hover"],
    )


def build_error_dialog_stylesheet(pal: dict[str, str]) -> str:
    """Error dialog（可 resize 的 QDialog）樣式。

    這裡沿用主 palette，使 error dialog 與主視窗維持一致的視覺語言；
    同時復用 Settings 相同的 CheckBox 外觀。
    """
    checkbox_qss = _build_checkbox_qss_from_palette(pal, disabled_bg=pal["button_hover"])
    primary_text = _on_color(pal["accent"], light=pal["text"])

    base_dialog_qss = _build_dialog_base_qss("QDialog", pal)
    label_base_qss = _qss_block("QLabel", {"background": "transparent"})
    title_qss = _qss_block(
        "QLabel#ErrorTitle",
        {
            "font-size": "15px",
            "font-weight": 700,
        },
    )

    text_edit_qss = _build_text_edit_base_qss(
        bg=pal["input_bg"],
        text=pal["text"],
        border=pal["border"],
        radius=8,
        padding="10px",
    )
    details_qss = _build_text_edit_mono_qss("QTextEdit#ErrorDetails", font_size=12)

    button_base_qss = _build_button_base_qss(
        bg=pal["button_bg"],
        text=pal["text"],
        border=pal["border"],
        radius=6,
        padding="8px 16px",
        font_size=13,
    )
    button_hover_qss = _qss_block(
        "QPushButton:hover",
        {
            "background": pal["button_hover"],
        },
    )
    primary_button_qss = _build_button_primary_qss(
        bg=pal["accent"],
        text=primary_text,
        border=pal["accent"],
        hover_bg=pal["button_hover"],
    )

    return f"""
        {base_dialog_qss}

        {label_base_qss}
        {title_qss}

        {text_edit_qss}
        {details_qss}

        {button_base_qss}
        {button_hover_qss}
        {primary_button_qss}

        {checkbox_qss}
    """


def build_transcript_popup_stylesheet(pal: dict[str, str]) -> str:
    """TranscriptPopupDialog 的樣式"""
    primary_bg, primary_hover = _dialog_primary_colors(pal)
    primary_text = _on_color(primary_bg, light=pal["text"])
    hover_bg = pal["button_hover"]

    base_dialog_qss = _build_dialog_base_qss("QDialog", pal)
    text_edit_qss = _build_text_edit_base_qss(
        bg=pal["input_bg"],
        text=pal["text"],
        border=pal["border"],
        radius=8,
        padding="10px",
    )
    text_edit_mono_qss = _build_text_edit_mono_qss("QTextEdit", font_size=12)

    button_base_qss = _build_button_base_qss(
        bg=pal["button_bg"],
        text=pal["text"],
        border=pal["border"],
        radius=6,
        padding="8px 12px",
    )
    button_hover_qss = _qss_block(
        "QPushButton:hover",
        {
            "border-color": pal["accent"],
            "background": hover_bg,
        },
    )
    button_pressed_qss = _qss_block(
        "QPushButton:pressed",
        {
            "background": primary_bg,
            "color": primary_text,
        },
    )
    primary_button_qss = _build_button_primary_qss(
        bg=primary_bg,
        text=primary_text,
        border=primary_bg,
        hover_bg=primary_hover,
        hover_border=primary_hover,
    )
    icon_button_qss = _qss_block("QPushButton#IconButton", {"padding": "0px"})
    label_base_qss = _qss_block("QLabel", {"background": "transparent"})

    return f"""
        {base_dialog_qss}
        {text_edit_qss}
        {text_edit_mono_qss}
        {button_base_qss}

        /* Popup 內的工具按鈕（Zoom In/Out）：
           - 使用 objectName = IconButton
           - padding 置 0，避免 fixedSize 時內容被擠壓
        */
        {icon_button_qss}
        {button_hover_qss}
        {button_pressed_qss}
        {primary_button_qss}
        {label_base_qss}
    """


def build_settings_dialog_stylesheet(pal: dict[str, str]) -> str:
    """SettingsDialog 的樣式（含扁平化 CheckBox）"""
    primary_bg, primary_hover = _dialog_primary_colors(pal)
    primary_text = _on_color(primary_bg, light=pal["text"])
    hover_bg = pal["button_hover"]

    checkbox_qss = _build_checkbox_qss_from_palette(pal, disabled_bg=hover_bg)

    base_dialog_qss = _build_dialog_base_qss("QWidget", pal)
    label_base_qss = _qss_block(
        "QLabel",
        {
            "background": "transparent",
            "border": "none",
            "padding": "2px",
        },
    )
    input_base_qss = _build_input_base_qss(
        selectors="QComboBox, QLineEdit",
        bg=pal["input_bg"],
        border=pal["border"],
        radius=6,
        padding="8px 12px",
    )
    button_base_qss = _build_button_base_qss(
        bg=pal["button_bg"],
        text=None,
        border=pal["border"],
        radius=6,
        padding="8px 12px",
    )
    download_button_qss = _qss_block(
        "QPushButton#DownloadButton",
        {
            "padding": "6px 10px",
            "min-width": "92px",
            "font-size": "12px",
        },
    )
    download_disabled_qss = _qss_block(
        "QPushButton#DownloadButton:disabled",
        {
            "color": pal["hint"],
            "background": pal["button_bg"],
            "border-color": pal["border"],
        },
    )
    hover_qss = _qss_block(
        "QComboBox:hover, QLineEdit:hover, QPushButton:hover",
        {
            "border-color": pal["accent"],
            "background": hover_bg,
        },
    )
    focus_qss = _qss_block(
        "QLineEdit:focus",
        {
            "border-color": pal["accent"],
        },
    )
    pressed_qss = _qss_block(
        "QPushButton:pressed",
        {
            "background": primary_bg,
            "color": primary_text,
        },
    )
    primary_button_qss = _build_button_primary_qss(
        bg=primary_bg,
        text=primary_text,
        border=primary_bg,
        hover_bg=primary_hover,
        hover_border=primary_hover,
    )

    return f"""
        {base_dialog_qss}

        /* --- Base controls --- */
        {label_base_qss}
        {input_base_qss}
        {button_base_qss}
        {download_button_qss}
        {download_disabled_qss}

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

        {hover_qss}
        {focus_qss}

        {pressed_qss}
        {primary_button_qss}

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
