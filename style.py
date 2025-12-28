def get_palette(theme: str) -> dict[str, str]:
    """根據主題返回調色板"""
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
    """構建 Qt 樣式表"""
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
