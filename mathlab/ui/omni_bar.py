import os

from PySide6.QtCore import (
    QEasingCurve,
    QObject,
    QPropertyAnimation,
    QRect,
    Qt,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import QColor, QKeyEvent
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QVBoxLayout, QWidget


class OmniBarBackend(QObject):
    """暴露给前端 JS 的桥接对象 (QWebChannel)。

    JS 侧通过 ``window.backend.submit(text)`` / ``window.backend.request_dismiss()``
    调用这里的 Slot；这里再驱动 Python 侧原本的 OmniBar 行为。
    """

    def __init__(self, omni_bar: "OmniBar"):
        super().__init__()
        self._bar = omni_bar
        self._submitting = False

    @Slot(str)
    def submit(self, text: str) -> None:
        """复刻原 OmniBar.on_submit 的全部行为，保证功能一致性。"""
        # 去抖动：防止快速连按回车导致重复发送
        if self._submitting:
            return
        self._submitting = True
        try:
            text = (text or "").strip()
            if not text:
                return

            # 1. 触发全局 AI 任务
            self._bar.search_submitted.emit(text)

            # 2. 同时转发到 AI 对话面板（原 on_submit 行为）
            parent_win = self._bar.parent()
            if parent_win and hasattr(parent_win, "ai_tools_panel") and parent_win.ai_tools_panel:
                parent_win.ai_tools_panel.chat_input.setText(text)
                parent_win.ai_tools_panel.on_send_message()

            # 3. 发送完后自动功成身退
            self._bar.dismiss()
        finally:
            self._submitting = False

    @Slot()
    def request_dismiss(self) -> None:
        """JS 侧按下 Esc 时请求关闭。"""
        self._bar.dismiss()


class OmniBar(QWidget):
    """混合式重构后的命令栏：

    浮层窗口（无边框 / 置顶 / 半透明）的行为保留在 Python 侧，
    内部嵌入一个 QWebEngineView 渲染 JS/TS 前端 (omni_bar.html)，
    二者经 QWebChannel 双向通信。对外接口与旧版完全一致，
    main_window 与 _mixin_ai 无需改动。
    """

    search_submitted = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        # ✨ 魔法标志：脱离主窗体、无边框、永远置顶、背景透明
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._build_ui()
        self._setup_animations()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # 核心载体：WebEngine 视图，渲染 JS/TS 前端
        self.web_view = QWebEngineView(self)
        self.web_view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.web_view.page().setBackgroundColor(QColor(0, 0, 0, 0))
        main_layout.addWidget(self.web_view)

        # QWebChannel 桥接
        self.channel = QWebChannel()
        self.backend = OmniBarBackend(self)
        self.channel.registerObject("backend", self.backend)
        self.web_view.page().setWebChannel(self.channel)

        html_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "resources", "omni_bar.html"))
        self.web_view.setUrl(QUrl.fromLocalFile(html_path))

        # 页面加载完成后，若当前正处于召唤态则自动聚焦输入框
        self.web_view.loadFinished.connect(self._on_load_finished)

        # 默认隐藏
        self.setWindowOpacity(0.0)
        self.hide()

    def _on_load_finished(self, ok: bool):
        if ok and self.isVisible():
            self._focus_input()

    def _focus_input(self):
        self.web_view.page().runJavaScript("if (window.omni) window.omni.focusInput();")

    def _setup_animations(self):
        # 透明度渐变动画
        self.fade_anim = QPropertyAnimation(self, b"windowOpacity")
        self.fade_anim.setDuration(150)  # 150ms 极速响应
        self.fade_anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        # 只连接一次，避免 dismiss() 重复 connect 造成回调累积
        self.fade_anim.finished.connect(self._on_fade_out_finished)

    def summon(self, parent_rect: QRect):
        """召唤命令盘：居中浮现"""
        width = 600
        height = 80
        x = parent_rect.x() + (parent_rect.width() - width) // 2
        y = parent_rect.y() + parent_rect.height() // 4

        self.setGeometry(x, y, width, height)
        self.show()

        # 中断可能仍在进行的淡出动画，避免其 finished 回调误隐藏命盘
        self.fade_anim.stop()

        # 执行淡入动画
        self.fade_anim.setStartValue(0.0)
        self.fade_anim.setEndValue(1.0)
        self.fade_anim.start()

        # 强制抢占焦点，光标直接进入输入框
        self.activateWindow()
        # 页面就绪后聚焦输入框（首次可能尚未加载完，延时兜底 + loadFinished 双重保险）
        QTimer.singleShot(30, self._focus_input)

    def dismiss(self):
        """驱散命令盘：优雅淡出"""
        self.fade_anim.setStartValue(self.windowOpacity())
        self.fade_anim.setEndValue(0.0)

        # 动画结束后由 _on_fade_out_finished 真正隐藏，节约系统资源
        self.fade_anim.start()

    def _on_fade_out_finished(self):
        # 淡入结束时也会触发 finished，此时透明度不为 0，不应隐藏
        if self.windowOpacity() > 0.01:
            return
        self.hide()
        # 清空前端输入框，避免下次召唤残留上次文本
        self.web_view.page().runJavaScript("if (window.omni) window.omni.setValue('');")

    # --- 核心交互 UX ---
    def focusOutEvent(self, event):
        """当用户点击了画板的其他地方，Omni-Bar 自动识趣地消失"""
        self.dismiss()
        super().focusOutEvent(event)

    def keyPressEvent(self, event: QKeyEvent):
        """按下 Esc 键立即消失（Web 视图未抢焦点时的兜底）"""
        if event.key() == Qt.Key.Key_Escape:
            self.dismiss()
        super().keyPressEvent(event)
