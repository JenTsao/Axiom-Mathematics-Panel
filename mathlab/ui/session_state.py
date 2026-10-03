"""会话状态持久化（UI_SYSTEM_DESIGN.md §5，对应 R-09 / A-05）。

边界（避免第二套真源）：
- 偏好类数据（主题 / 语言 / 各类开关）→ 继续走 ``settings.json``。
- **会话态**（窗口几何 / Dock 布局 / 末选 Tab / 画布白纸开关）→ ``QSettings``。
  二进制 QByteArray 不适合 JSON；会话态 ≠ 偏好。

Key 规范（§5.3）：
``window/schemaVersion`` ``window/geometry`` ``window/state``
``docks/<objectName>/visible`` ``central/lastTabIndex`` ``canvas/whitePaper``
``session/firstRun``
"""

from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDockWidget, QMainWindow

from mathlab.utils.logger import get_logger

logger = get_logger(__name__)

ORG = "MathLab"
APP = "MathLab"

SCHEMA_VERSION = 1

# ── Key 常量（共享知识，见 §10） ────────────────────────────────────────────
KEY_SCHEMA_VERSION = "window/schemaVersion"
KEY_GEOMETRY = "window/geometry"
KEY_WINDOW_STATE = "window/state"
KEY_DOCK_VISIBLE = "docks/{name}/visible"
KEY_LAST_TAB = "central/lastTabIndex"
KEY_WHITE_PAPER = "canvas/whitePaper"
KEY_FIRST_RUN = "session/firstRun"

# 首启默认布局中「核心可见」的 Dock objectName（§5.5 / R-15）
_DEFAULT_VISIBLE_DOCKS = ("dockAlgebra", "dockProperties", "dockConsole", "dockAlgoVis", "dockAITools")
_DEFAULT_HIDDEN_DOCKS = ("dockMathConsole", "dockFunctionExplorer")


def make_settings() -> QSettings:
    """创建会话 QSettings（IniFormat：跨平台一致、可肉眼检查、无注册表权限问题）。"""
    return QSettings(QSettings.IniFormat, QSettings.UserScope, ORG, APP)


# ── 白纸开关（D-2，状态入 QSettings） ───────────────────────────────────────


def get_white_paper() -> bool:
    """读取画布白纸开关（默认关）。"""
    return make_settings().value(KEY_WHITE_PAPER, False, type=bool)


def set_white_paper(enabled: bool) -> None:
    """写入画布白纸开关并立即落盘。"""
    settings = make_settings()
    settings.setValue(KEY_WHITE_PAPER, bool(enabled))
    settings.sync()


# ── 会话保存 / 恢复 ────────────────────────────────────────────────────────


def save_session(win: QMainWindow) -> None:
    """在 closeEvent 最前端调用（快、无副作用）。

    保存：schema 版本、窗口几何、Dock/Toolbar 状态、各 Dock 显隐兜底、末选 Tab。
    """
    try:
        settings = make_settings()
        settings.setValue(KEY_SCHEMA_VERSION, SCHEMA_VERSION)
        settings.setValue(KEY_GEOMETRY, win.saveGeometry())
        settings.setValue(KEY_WINDOW_STATE, win.saveState())

        # Dock 显隐兜底（saveState 已含，供 _apply_default_layout / 诊断用）
        for dock in win.findChildren(QDockWidget):
            name = dock.objectName()
            if name:
                settings.setValue(KEY_DOCK_VISIBLE.format(name=name), dock.isVisible())

        settings.setValue(KEY_LAST_TAB, win.central_tabs.currentIndex())
        settings.setValue(KEY_FIRST_RUN, False)
        settings.sync()
        logger.debug("会话状态已保存")
    except Exception as e:
        logger.warning("保存会话状态失败: %s", e)


def restore_session(win: QMainWindow) -> bool:
    """在 setup_docks() 之后、apply_theme() 之前调用。

    Returns:
        True = 从持久化恢复；False = 首启 / schema 不符 / 恢复失败 → 已走默认布局。
    """
    try:
        settings = make_settings()
        version = settings.value(KEY_SCHEMA_VERSION, -1, type=int)
        if version != SCHEMA_VERSION:
            logger.info("会话 schema 版本不符（%s ≠ %s），使用默认布局", version, SCHEMA_VERSION)
            _apply_default_layout(win)
            return False

        geometry = settings.value(KEY_GEOMETRY)
        state = settings.value(KEY_WINDOW_STATE)
        restored = False
        if geometry is not None:
            restored = win.restoreGeometry(geometry) or restored
        if state is not None:
            restored = win.restoreState(state) or restored

        if not restored:
            logger.info("无有效会话状态，使用默认布局")
            _apply_default_layout(win)
            return False

        # 末选 Tab（restoreState 不含中央 QTabWidget）
        last_tab = settings.value(KEY_LAST_TAB, 0, type=int)
        if 0 <= last_tab < win.central_tabs.count():
            win.central_tabs.setCurrentIndex(last_tab)

        logger.debug("会话状态已恢复")
        return True
    except Exception as e:
        logger.warning("恢复会话状态失败，回退默认布局: %s", e)
        _apply_default_layout(win)
        return False


def reset_session(win: QMainWindow) -> None:
    """「视图 → 恢复默认布局」入口：清除持久化并应用默认布局。"""
    try:
        settings = make_settings()
        settings.clear()
        settings.sync()
    except Exception as e:
        logger.warning("清除会话数据失败: %s", e)
    _apply_default_layout(win)
    logger.info("已恢复默认布局")


def _apply_default_layout(win: QMainWindow) -> None:
    """首启默认布局（§5.5）：
    - 几何：主屏可用区域 80%，居中（删除 1200×800 硬编码）。
    - 中央 Tab 首页 = 几何画板（R-08）。
    - 可见面板：代数 / 属性 / 控制台 + 右侧 Tab 组（算法可视化 / AI 工具可见）；
      函数探索器与数学控制台隐藏。
    """
    screen = QGuiApplication.primaryScreen()
    if screen is not None:
        avail = screen.availableGeometry()
        width = int(avail.width() * 0.8)
        height = int(avail.height() * 0.8)
        x = avail.x() + (avail.width() - width) // 2
        y = avail.y() + (avail.height() - height) // 2
        win.setGeometry(x, y, width, height)

    # Dock 默认显隐（前置条件：setup_docks() 已为每个 QDockWidget 补 objectName）
    dock_map = {
        "dockAlgebra": getattr(win, "algebra_panel", None),
        "dockProperties": getattr(win, "properties_panel", None),
        "dockConsole": getattr(win, "console", None),
        "dockMathConsole": getattr(win, "math_console", None),
        "dockFunctionExplorer": getattr(win, "function_explorer", None),
        "dockAlgoVis": getattr(win, "algo_vis_panel", None),
        "dockAITools": getattr(win, "ai_tools_panel", None),
    }
    for name, dock in dock_map.items():
        if dock is None:
            continue
        if name in _DEFAULT_VISIBLE_DOCKS:
            dock.show()
        elif name in _DEFAULT_HIDDEN_DOCKS:
            dock.hide()

    # 右侧 Tab 组：算法可视化 / AI 工具可见并置前（R-15）
    if getattr(win, "algo_vis_panel", None) is not None:
        win.algo_vis_panel.show()
        win.algo_vis_panel.raise_()

    # 冷启动落在几何画板（R-08：Tab 序已调整为 画板 → Notebook → Mini GeoGebra → Jupyter）
    if hasattr(win, "central_tabs"):
        win.central_tabs.setCurrentIndex(0)
