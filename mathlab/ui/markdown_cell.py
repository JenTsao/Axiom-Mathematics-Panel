import os

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QFont, QKeySequence
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QTextEdit,
    QVBoxLayout,
)


class MarkdownTextEdit(QTextEdit):
    def __init__(self, parent_widget, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.parent_widget = parent_widget

    def keyPressEvent(self, event):
        if event.modifiers() == Qt.ShiftModifier and event.key() == Qt.Key_Return:
            self.parent_widget.switch_to_view()
        else:
            super().keyPressEvent(event)


class MarkdownCellWidget(QFrame):
    """
    交互式 Markdown/LaTeX 单元格
    支持双击/点击工具栏切换编辑，Shift+Enter 渲染。

    渲染引擎：WebEngine (marked.js + KaTeX)
    此单元格需要高质量的 LaTeX 公式渲染，因此使用 JS 引擎。
    纯文本 Markdown 场景请使用 MarkdownService (Python 引擎)。
    """

    code_synced = Signal(str)

    def __init__(self, cell_id, initial_content="", parent=None):
        super().__init__(parent)
        self.cell_id = cell_id
        self.init_ui()
        self.set_content(initial_content)
        self.set_focused(False)

    def init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 5, 0, 5)
        self.main_layout.setSpacing(0)

        # ── 1. 悬浮工具栏 ──
        self.toolbar_layout = QHBoxLayout()
        self.toolbar_layout.setContentsMargins(10, 0, 10, 0)

        self.type_label = QLabel("Markdown 文本")
        self.type_label.setObjectName("mdTypeLabel")

        self.btn_edit = QPushButton("✎ 编辑")
        self.btn_delete = QPushButton("🗑 删除")
        for btn in [self.btn_edit, self.btn_delete]:
            btn.setObjectName("mdActionBtn")
            btn.setCursor(Qt.PointingHandCursor)

        self.btn_edit.clicked.connect(self.switch_to_edit)

        self.toolbar_layout.addWidget(self.type_label)
        self.toolbar_layout.addSpacerItem(QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        self.toolbar_layout.addWidget(self.btn_edit)
        self.toolbar_layout.addWidget(self.btn_delete)

        self.toolbar_container = QFrame()
        self.toolbar_container.setLayout(self.toolbar_layout)
        self.toolbar_container.setFixedHeight(28)
        self.toolbar_container.hide()

        # ── 2. 编辑模式: 纯文本输入框 ──
        self.input_editor = MarkdownTextEdit(self)
        self.input_editor.setObjectName("mdEditor")
        self.input_editor.setFont(QFont("Consolas", 12))
        self.input_editor.setMinimumHeight(60)
        self.input_editor.textChanged.connect(self._adjust_editor_height)
        self.input_editor.textChanged.connect(lambda: self.code_synced.emit(self.input_editor.toPlainText()))

        # ── 3. 预览模式: WebEngine 渲染器 ──
        self.viewer = QWebEngineView()
        self.viewer.setMinimumHeight(60)
        self.viewer.page().setBackgroundColor(self.palette().color(self.backgroundRole()))

        html_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "resources", "markdown.html"))
        self.viewer.load(QUrl.fromLocalFile(html_path))
        self.viewer.hide()  # 初始隐藏，等渲染

        self.main_layout.addWidget(self.toolbar_container)
        self.main_layout.addWidget(self.input_editor)
        self.main_layout.addWidget(self.viewer)

    def switch_to_edit(self):
        """切换到源码编辑模式"""
        self.viewer.hide()
        self.input_editor.show()
        self.input_editor.setFocus()
        self.btn_edit.hide()

    def switch_to_view(self):
        """切换到绝美排版渲染模式"""
        text = self.input_editor.toPlainText()
        # 处理转义符，防止 JS 报错
        # [BUG修复] 补充 ${} 转义，防止模板字符串注入
        safe_text = text.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${").replace("\n", "\\n")
        js_code = f"renderMarkdown(`{safe_text}`);"

        self.viewer.page().runJavaScript(js_code)

        # 渲染后动态获取内容高度并调整
        # 使用 QTimer 延迟执行，确保 DOM 已完成更新
        from PySide6.QtCore import QTimer

        QTimer.singleShot(100, self._request_view_height)

        self.input_editor.hide()
        self.viewer.show()
        self.btn_edit.show()

    def _request_view_height(self):
        """通过 JS 获取渲染后的内容高度"""
        js_code = (
            "Math.max("
            "document.body.scrollHeight, "
            "document.documentElement.scrollHeight, "
            "document.getElementById('content').scrollHeight"
            ")"
        )
        self.viewer.page().runJavaScript(js_code, self._on_height_received)

    def _on_height_received(self, height):
        """根据 JS 返回的高度动态调整 viewer"""
        if height and height > 0:
            # 限制在 60~600px 之间
            self.viewer.setFixedHeight(min(max(int(height) + 20, 60), 600))

    def _adjust_editor_height(self):
        """根据内容行数动态调整编辑器高度"""
        line_count = self.input_editor.toPlainText().count("\n") + 1
        # 每行约 20px，加 padding 30px，限制 60~400px
        height = min(max(line_count * 20 + 30, 60), 400)
        self.input_editor.setFixedHeight(height)

    def set_content(self, text):
        self.input_editor.setPlainText(text)

    # 悬浮与聚焦逻辑 (同之前的设计)
    def enterEvent(self, event):
        self.toolbar_container.show()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.toolbar_container.hide()
        super().leaveEvent(event)

    def set_focused(self, is_focused):
        self.setProperty("focused", "true" if is_focused else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event):
        self.set_focused(True)
        super().mousePressEvent(event)
