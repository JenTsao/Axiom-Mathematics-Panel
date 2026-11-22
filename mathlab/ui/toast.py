"""非模态 Toast 通知服务（R-16 / UI-14）。

提供轻量级、非打断的右下角堆叠通知卡片，替代频繁打断心流的模态
``QMessageBox`` 与容易被忽略的 ``statusBar().showMessage()``。

特性：
- 四种语义等级（``info`` / ``success`` / ``warning`` / ``error``），样式完全走
  ``styles.qss`` + ``THEME_TOKENS``，零内联样式与硬编码色值；
- 自动淡入/淡出动画（200ms OutCubic），鼠标悬停暂停自动消失计时；
- 支持最多 4 条同时堆叠，超限时自动挤出最早一条；
- 监听宿主窗口 Resize/Move 事件，始终锚定在宿主右下角安全区域内。
"""

from __future__ import annotations

from typing import Literal

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPropertyAnimation,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QWidget,
)

ToastLevel = Literal["info", "success", "warning", "error"]

_LEVEL_ICONS: dict[str, str] = {
    "info": "i",
    "success": "✓",
    "warning": "!",
    "error": "✕",
}


class ToastCard(QFrame):
    """单条非模态 Toast 卡片（样式由 ``styles.qss`` ``QFrame#toastCard`` 提供）。"""

    closed = Signal(object)

    def __init__(
        self,
        message: str,
        level: ToastLevel = "info",
        duration_ms: int = 3200,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.level: ToastLevel = level if level in _LEVEL_ICONS else "info"
        self.duration_ms = max(0, int(duration_ms))
        self._closing = False

        self.setObjectName("toastCard")
        self.setProperty("toastLevel", self.level)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumWidth(260)
        self.setMaximumWidth(380)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 10, 10)
        layout.setSpacing(10)

        self.icon_label = QLabel(_LEVEL_ICONS[self.level], self)
        self.icon_label.setObjectName("toastIcon")
        self.icon_label.setProperty("toastLevel", self.level)
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setFixedSize(20, 20)
        layout.addWidget(self.icon_label, 0, Qt.AlignmentFlag.AlignTop)

        self.message_label = QLabel(message, self)
        self.message_label.setObjectName("toastMessage")
        self.message_label.setWordWrap(True)
        layout.addWidget(self.message_label, 1)

        self.close_btn = QPushButton("✕", self)
        self.close_btn.setObjectName("toastCloseBtn")
        self.close_btn.setFixedSize(20, 20)
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.clicked.connect(self.dismiss)
        layout.addWidget(self.close_btn, 0, Qt.AlignmentFlag.AlignTop)

        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity_effect)

        self._fade_anim = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._fade_anim.setDuration(180)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.timeout.connect(self.dismiss)

        self.adjustSize()

    def start(self) -> None:
        """淡入显示并启动自动消失计时器。"""
        self.show()
        self.raise_()
        self._fade_anim.stop()
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.start()
        if self.duration_ms > 0:
            self._dismiss_timer.start(self.duration_ms)

    def dismiss(self) -> None:
        """平滑淡出并通知管理器移除。"""
        if self._closing:
            return
        self._closing = True
        self._dismiss_timer.stop()
        self._fade_anim.stop()
        self._fade_anim.setDuration(140)
        self._fade_anim.setStartValue(self._opacity_effect.opacity())
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.finished.connect(self._on_dismiss_finished)
        self._fade_anim.start()

    def _on_dismiss_finished(self) -> None:
        self.hide()
        self.closed.emit(self)
        self.deleteLater()

    def enterEvent(self, event) -> None:
        """鼠标悬停时暂停自动关闭，方便阅读长提示。"""
        if self._dismiss_timer.isActive():
            self._dismiss_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        """鼠标离开后恢复剩余关闭计时。"""
        if not self._closing and self.duration_ms > 0:
            self._dismiss_timer.start(min(self.duration_ms, 1800))
        super().leaveEvent(event)


class ToastManager(QObject):
    """宿主窗口右下角 Toast 队列管理器。"""

    MAX_VISIBLE = 4
    MARGIN_RIGHT = 18
    MARGIN_BOTTOM = 16
    SPACING = 8

    def __init__(self, host: QWidget) -> None:
        super().__init__(host)
        self._host = host
        self._toasts: list[ToastCard] = []
        self._host.installEventFilter(self)

    @property
    def active_count(self) -> int:
        return len(self._toasts)

    def show_toast(
        self,
        message: str,
        level: ToastLevel = "info",
        duration_ms: int = 3200,
    ) -> ToastCard | None:
        """展示一条非模态 Toast 通知。"""
        text = (message or "").strip()
        if not text:
            return None

        while len(self._toasts) >= self.MAX_VISIBLE:
            oldest = self._toasts.pop(0)
            oldest.dismiss()

        card = ToastCard(text, level=level, duration_ms=duration_ms, parent=self._host)
        card.closed.connect(self._on_card_closed)
        self._toasts.append(card)
        self._reposition()
        card.start()
        return card

    def info(self, message: str, duration_ms: int = 3000) -> ToastCard | None:
        return self.show_toast(message, level="info", duration_ms=duration_ms)

    def success(self, message: str, duration_ms: int = 3000) -> ToastCard | None:
        return self.show_toast(message, level="success", duration_ms=duration_ms)

    def warning(self, message: str, duration_ms: int = 4000) -> ToastCard | None:
        return self.show_toast(message, level="warning", duration_ms=duration_ms)

    def error(self, message: str, duration_ms: int = 5000) -> ToastCard | None:
        return self.show_toast(message, level="error", duration_ms=duration_ms)

    def clear(self) -> None:
        """立即关闭所有当前可见的 Toast。"""
        for card in list(self._toasts):
            card.dismiss()
        self._toasts.clear()

    def _on_card_closed(self, card: ToastCard) -> None:
        if card in self._toasts:
            self._toasts.remove(card)
        self._reposition()

    def _bottom_clearance(self) -> int:
        """为 QMainWindow 状态栏预留安全底边距。"""
        clearance = self.MARGIN_BOTTOM
        if isinstance(self._host, QMainWindow):
            sb = self._host.statusBar()
            if sb is not None and sb.isVisible():
                clearance += sb.height()
        return clearance

    def _reposition(self) -> None:
        """将所有活跃 Toast 自下而上排列在宿主右下角。"""
        host_w = max(self._host.width(), 320)
        host_h = max(self._host.height(), 200)
        y_cursor = host_h - self._bottom_clearance()

        for card in reversed(self._toasts):
            card.adjustSize()
            w = min(max(card.sizeHint().width(), card.minimumWidth()), card.maximumWidth())
            h = card.sizeHint().height()
            card.resize(w, h)
            x = max(8, host_w - w - self.MARGIN_RIGHT)
            y_cursor -= h
            card.move(x, max(8, y_cursor))
            y_cursor -= self.SPACING

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        host = getattr(self, "_host", None)
        if host is None:
            return False
        if watched is host and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self._reposition()
        return super().eventFilter(watched, event)
