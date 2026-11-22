"""集中式快捷键注册表与 WebEngine 焦点保护（R-18 / A-09）。

职责：
1. 集中登记窗口级快捷键并自动检测冲突（同一按键序列重复绑定时记录警告）；
2. 提供 WebEngine 焦点保护：当键盘焦点位于嵌入的 ``QWebEngineView``（如 JupyterLab /
   Monaco 编辑器）内部时，自动放行不抢占其快捷键；
3. 统一跨平台快捷键展示文本（macOS 下将 ``Ctrl`` 渲染为 ``⌘`` 语义，Qt 底层自动处理）。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QWidget

from mathlab.utils.logger import get_logger

logger = get_logger(__name__)

_WEBENGINE_CLASS_HINTS = ("QWebEngineView", "RenderWidgetHostView")


def is_webengine_focused(widget: QWidget | None = None) -> bool:
    """判断当前（或指定）焦点控件是否处于嵌入式 QWebEngineView 子树内。"""
    current = widget if widget is not None else QApplication.focusWidget()
    while current is not None:
        cls_name = type(current).__name__
        if any(hint in cls_name for hint in _WEBENGINE_CLASS_HINTS):
            return True
        current = current.parentWidget()
    return False


def format_shortcut_hint(sequence: str) -> str:
    """将标准 Qt 快捷键字符串转为平台友好的提示文案。"""
    if not sequence:
        return ""
    if sys.platform == "darwin":
        return sequence.replace("Ctrl+", "⌘").replace("Shift+", "⇧").replace("Alt+", "⌥")
    return sequence


@dataclass(frozen=True)
class ShortcutEntry:
    """一条已注册的快捷键记录。"""

    shortcut_id: str
    sequence: str
    description: str
    respect_webengine_focus: bool
    shortcut: QShortcut


class ShortcutRegistry:
    """主窗口快捷键集中注册与冲突检测器。"""

    def __init__(self, parent: QWidget) -> None:
        self._parent = parent
        self._entries: dict[str, ShortcutEntry] = {}
        self._by_sequence: dict[str, list[str]] = {}

    def register(
        self,
        shortcut_id: str,
        sequence: str,
        callback: Callable[[], None],
        *,
        description: str = "",
        context: Qt.ShortcutContext = Qt.ShortcutContext.WindowShortcut,
        respect_webengine_focus: bool = True,
    ) -> QShortcut:
        """注册一条快捷键，若按键序列已存在则记录冲突警告。"""
        normalized = QKeySequence(sequence).toString()
        existing_ids = self._by_sequence.setdefault(normalized, [])
        if existing_ids and shortcut_id not in existing_ids:
            logger.warning(
                "快捷键冲突: '%s' 同时绑定到 %s 与 '%s'",
                normalized,
                existing_ids,
                shortcut_id,
            )
        if shortcut_id not in existing_ids:
            existing_ids.append(shortcut_id)

        shortcut = QShortcut(QKeySequence(sequence), self._parent)
        shortcut.setContext(context)

        def _guarded_invoke() -> None:
            if respect_webengine_focus and is_webengine_focused():
                logger.debug("WebEngine 持有焦点，跳过窗口快捷键 %s (%s)", shortcut_id, normalized)
                return
            callback()

        shortcut.activated.connect(_guarded_invoke)
        self._entries[shortcut_id] = ShortcutEntry(
            shortcut_id=shortcut_id,
            sequence=normalized,
            description=description,
            respect_webengine_focus=respect_webengine_focus,
            shortcut=shortcut,
        )
        return shortcut

    def get_conflicts(self) -> dict[str, list[str]]:
        """返回存在多处绑定的按键序列映射（空字典 = 无冲突）。"""
        return {seq: list(ids) for seq, ids in self._by_sequence.items() if len(ids) > 1}

    def list_entries(self) -> list[ShortcutEntry]:
        """返回所有已登记快捷键条目。"""
        return list(self._entries.values())

    def get(self, shortcut_id: str) -> ShortcutEntry | None:
        """按 ID 查找已登记条目。"""
        return self._entries.get(shortcut_id)
