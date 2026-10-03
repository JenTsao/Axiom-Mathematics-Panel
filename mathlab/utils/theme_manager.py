"""主题管理器 — 全应用唯一的样式注入点（Single Source of Truth 出口）。

架构（UI_SYSTEM_DESIGN.md §1）：
- 数据源：``mathlab/utils/theme_tokens.py::THEME_TOKENS``（token 表）。
- 模板：``mathlab/ui/styles.qss``（``${token}`` 占位符，string.Template 语法）。
- 唯一写入点：``set_theme(name)`` → ``render_qss()`` 渲染一次 →
  ``app.setStyleSheet(qss)``（全应用唯一一次 app 级注入）。
- 主题变更后发射 ``theme_signals.theme_changed``，驱动画布等订阅者重绘。

``THEMES`` / ``get_theme_colors()`` 保留为**兼容视图**（由 token 派生），
存量消费者零改动可编译；新代码一律走 ``get_tokens()``。
"""

from __future__ import annotations

import json
import os
from string import Template

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from mathlab.utils.logger import get_logger
from mathlab.utils.theme_tokens import THEME_TOKENS, flat_tokens, get_tokens

logger = get_logger(__name__)

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "settings.json")

# styles.qss 模板路径（打包映射路径，勿改动 — 见 UI_SYSTEM_DESIGN.md §2.3 / R-4）
QSS_TEMPLATE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ui", "styles.qss")

# 快照字节阈值：超过则跳过记录（预留，供撤销栈等大对象场景使用）
MAX_RENDER_LOG_LEN = 200

# ── 兼容垫片：旧 THEMES 键 → 新 token 键（§1.7） ────────────────────────────
_TOKEN_TO_LEGACY = {
    "background": "bg.base",
    "foreground": "fg.primary",
    "panel_bg": "bg.surface",
    "panel_border": "border.subtle",
    "accent": "accent.base",
    "secondary": "obj.segment",  # 废弃：PRD 禁止第二强调色，仅为编译兼容保留
    "console_bg": "bg.inset",
    "console_fg": "fg.primary",
    "success": "success",
    "warning": "warning",
    "error": "danger",
    "point_color": "obj.point",
    "segment_color": "obj.segment",
    "circle_color": "obj.circle",
    "polygon_color": "obj.polygon",
}

_THEME_DISPLAY_NAMES = {"light": "Light", "dark": "Dark", "sepia": "Sepia"}


def _derive_legacy_view(theme_name: str) -> dict:
    """由 token 表派生旧版 THEMES 兼容视图（含 name 键）。"""
    tokens = get_tokens(theme_name)
    view = {legacy: tokens[tok] for legacy, tok in _TOKEN_TO_LEGACY.items()}
    view["name"] = _THEME_DISPLAY_NAMES.get(theme_name, theme_name.title())
    return view


# DEPRECATED: 旧键兼容视图，仅供存量消费者编译运行；新代码必须使用 get_tokens()
THEMES: dict[str, dict] = {name: _derive_legacy_view(name) for name in THEME_TOKENS}


def load_settings() -> dict:
    """读取 settings.json（与 config_manager 共用同一文件）。"""
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("Could not load settings: %s", e)
    return {}


def save_settings(settings: dict) -> None:
    """合并写入 settings.json。"""
    try:
        current = load_settings()
        current.update(settings)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logger.warning("Could not save settings: %s", e)


_cached_theme = None


def get_current_theme():
    """返回当前主题键（light / dark / sepia），首次调用从 settings.json 读取。"""
    global _cached_theme
    if _cached_theme is None:
        settings = load_settings()
        _cached_theme = settings.get("theme", "dark")
        if _cached_theme not in THEME_TOKENS:
            _cached_theme = "dark"
    return _cached_theme


def _apply_user_accent_override(tokens: dict) -> None:
    """用户自选强调色覆写层（§11 O-2）。

    settings.json 中存在非空 ``accent`` 键时，覆写 ``accent.base/hover/pressed``
    三个 token 后再渲染 —— 保持「单一 accent token」不变量，只是值可被用户覆写。
    """
    accent = load_settings().get("accent", "")
    if not accent or not isinstance(accent, str):
        return
    color = QColor(accent)
    if not color.isValid():
        return
    tokens["accent.base"] = accent
    tokens["accent.hover"] = _shift_lightness(color, 1.25).name(QColor.HexRgb)
    tokens["accent.pressed"] = _shift_lightness(color, 0.8).name(QColor.HexRgb)


def _shift_lightness(color: QColor, factor: float) -> QColor:
    """按系数缩放颜色明度（hover 变亮 / pressed 变暗的简单派生）。"""
    hue, sat, light, alpha = color.getHslF()
    light = max(0.0, min(1.0, light * factor))
    return QColor.fromHslF(hue, sat, light, alpha)


def _apply_palette(tokens: dict) -> None:
    """由 token 构建 QPalette（保留原逻辑，色值改取 token）。"""
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(tokens["bg.base"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(tokens["fg.primary"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(tokens["bg.surface"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(tokens["bg.surface"]))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(tokens["bg.elevated"]))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(tokens["fg.primary"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(tokens["fg.primary"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(tokens["bg.surface"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(tokens["fg.primary"]))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(tokens["danger"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(tokens["accent.base"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(tokens["fg.onAccent"]))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(tokens["fg.muted"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(tokens["fg.muted"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(tokens["fg.muted"]))

    app = QApplication.instance()
    if app is not None:
        app.setPalette(palette)


def render_qss(theme_name: str, tokens: dict | None = None) -> str:
    """渲染 styles.qss 模板（唯一渲染入口）。

    Args:
        theme_name: 主题键。
        tokens: 可选 token 覆写（如用户强调色）；None 时取 THEME_TOKENS[theme_name]。

    Returns:
        完整 QSS 文本（保证无 ``${`` 残留）。
    """
    if tokens is None:
        tokens = dict(get_tokens(theme_name))
    with open(QSS_TEMPLATE_FILE, "r", encoding="utf-8") as f:
        template_text = f.read()
    rendered = Template(template_text).safe_substitute(flat_tokens(tokens))
    if "${" in rendered:
        logger.warning("QSS 模板渲染后仍有未替换占位符（主题 %s）", theme_name)
    return rendered


def set_theme(theme_name: str) -> bool:
    """应用指定主题（全应用唯一一次 app 级样式注入）。

    流程：token 覆写（用户强调色）→ QPalette → 渲染 QSS → 注入 →
    持久化 → 发射 ``theme_changed``（在样式应用**之后**，订阅者看到的是新 token）。
    """
    global _cached_theme
    if theme_name not in THEME_TOKENS:
        logger.warning("未知主题: %s", theme_name)
        return False

    tokens = dict(THEME_TOKENS[theme_name])
    _cached_theme = theme_name
    _apply_user_accent_override(tokens)  # §11 O-2 用户自选强调色
    _apply_palette(tokens)

    qss = render_qss(theme_name, tokens)
    app = QApplication.instance()
    if app is not None:
        app.setStyleSheet(qss)  # ← 全应用唯一一次 app 级注入（A-02）
        app.setProperty("current_theme", theme_name)

    save_settings({"theme": theme_name})

    # documented cycle-escape: utils → core 延迟导入，与 config_manager/i18n_manager 同模式
    from mathlab.core.signals import theme_signals

    theme_signals.theme_changed.emit(theme_name)
    logger.debug("主题已切换: %s", theme_name)
    return True


def get_theme_colors(theme_name=None):
    """兼容接口：返回旧版 THEMES 键视图（由 token 派生）。

    DEPRECATED: 新代码必须使用 ``mathlab.utils.theme_tokens.get_tokens()``。
    """
    if theme_name is None:
        theme_name = get_current_theme()
    if theme_name not in THEME_TOKENS:
        theme_name = "light"
    return _derive_legacy_view(theme_name)
