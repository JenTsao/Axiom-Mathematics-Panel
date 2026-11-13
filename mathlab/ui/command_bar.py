"""command_bar.py — 全局命令面板 (Command Palette)

取代原简单的 QToolBar 输入框，实现 VS Code 风格的无边框悬浮搜索面板。

功能：
  - Ctrl+Shift+P 唤醒 / Esc 关闭
  - 实时模糊搜索（调用 CommandManager.search）
  - 键盘导航（↑↓ 在列表项间移动，Enter 执行）
  - 分类标签 + 快捷键显示
  - 深色 / 亮色主题自适应（读取全局 QSS 变量）
  - 点击外部自动关闭
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mathlab.core.command_manager import Command, CommandManager
from mathlab.utils.i18n_manager import t

# ══════════════════════════════════════════════════════════════════
#  CommandPalette
# ══════════════════════════════════════════════════════════════════


class CommandPalette(QWidget):
    """VS Code 风格的全局命令面板。

    作为普通 QWidget 放置在 MainWindow 内层，通过绝对定位居中覆盖
    在画布上方。使用 Qt.Tool | Qt.FramelessWindowHint 作为独立浮层。
    """

    command_executed = Signal(str)  # 执行命令后发出命令 id

    def __init__(self, command_manager: CommandManager, parent: QWidget = None):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(620, 440)

        self._manager = command_manager
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(60)  # 60ms 防抖
        self._debounce_timer.timeout.connect(self._do_update_list)

        self._build_ui()

        # 点击外部关闭
        self.installEventFilter(self)

    # ── UI 构建 ────────────────────────────────────────────────────
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(0)

        # 投影效果
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(32)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 140))

        self._frame = QFrame(self)
        self._frame.setObjectName("cp_frame")
        self._frame.setGraphicsEffect(shadow)
        outer.addWidget(self._frame)

        frame_layout = QVBoxLayout(self._frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.setSpacing(0)

        # ── 搜索框 ─────────────────────────────────────────────
        self._input = QLineEdit()
        self._input.setObjectName("cp_input")
        self._input.setFixedHeight(48)
        self._input.setPlaceholderText(t("command_bar.palette_placeholder"))
        self._input.setClearButtonEnabled(True)
        frame_layout.addWidget(self._input)

        # 分隔线
        sep = QFrame()
        sep.setObjectName("cp_sep")
        sep.setFrameShape(QFrame.HLine)
        frame_layout.addWidget(sep)

        # ── 结果列表 ───────────────────────────────────────────
        self._list = QListWidget()
        self._list.setObjectName("cp_list")
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._list.setSpacing(1)
        self._list.setFocusPolicy(Qt.NoFocus)  # 焦点留在 input
        frame_layout.addWidget(self._list)

        # 空结果提示（叠加在列表上方，用 stacked 方式隐藏）
        self._empty_label = QLabel(t("command_bar.palette_empty"))
        self._empty_label.setObjectName("cp_empty_hint")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setFixedHeight(60)
        self._empty_label.hide()
        frame_layout.addWidget(self._empty_label)

        # ── 信号连接 ───────────────────────────────────────────
        self._input.textChanged.connect(self._on_text_changed)
        self._input.returnPressed.connect(self._execute_selected)
        self._list.itemClicked.connect(self._on_item_clicked)

        # 让 input 捕获上下键以导航列表
        self._input.installEventFilter(self)

    # ── 生命周期 ───────────────────────────────────────────────────
    def show_centered_on(self, parent_widget: QWidget):
        """在父窗口的上 1/3 处居中显示。"""
        if parent_widget:
            pg = parent_widget.geometry()
            x = pg.x() + (pg.width() - self.width()) // 2
            y = pg.y() + (pg.height() - self.height()) // 3
            self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()
        self._input.clear()
        self._input.setFocus()
        self._do_update_list()

    def hide(self):
        self._input.clear()
        super().hide()

    # ── 事件过滤（键盘导航 + 点击外部关闭） ────────────────────────
    def eventFilter(self, obj, event):
        if obj is self._input and event.type() == QEvent.KeyPress:
            key = event.key()
            if key == Qt.Key_Escape:
                self.hide()
                return True
            elif key == Qt.Key_Down:
                self._move_selection(1)
                return True
            elif key == Qt.Key_Up:
                self._move_selection(-1)
                return True
            elif key == Qt.Key_Tab:
                self._move_selection(1)
                return True

        # 点击面板外部时关闭
        if event.type() == QEvent.WindowDeactivate:
            self.hide()
        elif event.type() == QEvent.MouseButtonPress:
            from PySide6.QtWidgets import QApplication

            widget = QApplication.widgetAt(event.globalPos())
            if widget is None or not self.isAncestorOf(widget):
                self.hide()

        return super().eventFilter(obj, event)

    def focusOutEvent(self, event):
        # 延迟一帧检查，避免点击列表项时误关
        QTimer.singleShot(100, self._check_focus_lost)
        super().focusOutEvent(event)

    def _check_focus_lost(self):
        from PySide6.QtWidgets import QApplication

        fw = QApplication.focusWidget()
        if fw is None or (fw is not self._input and fw is not self._list):
            self.hide()

    # ── 列表更新 ───────────────────────────────────────────────────
    def _on_text_changed(self, text: str):
        self._debounce_timer.start()  # 防抖：等用户停止输入 60ms 再刷新

    def _do_update_list(self):
        query = self._input.text().strip()
        commands = self._manager.search(query)

        self._list.clear()

        if not commands:
            self._list.hide()
            self._empty_label.show()
            return

        self._empty_label.hide()
        self._list.show()

        prev_category = None
        for cmd in commands:
            # 分类标题行
            if cmd.category != prev_category:
                cat_item = QListWidgetItem()
                cat_widget = self._make_category_header(cmd.category)
                cat_item.setSizeHint(cat_widget.sizeHint())
                cat_item.setFlags(Qt.NoItemFlags)  # 不可选
                self._list.addItem(cat_item)
                self._list.setItemWidget(cat_item, cat_widget)
                prev_category = cmd.category

            # 命令行
            item = QListWidgetItem()
            item.setData(Qt.UserRole, cmd)
            row_widget = self._make_command_row(cmd)
            item.setSizeHint(row_widget.sizeHint())
            self._list.addItem(item)
            self._list.setItemWidget(item, row_widget)

        # 默认选中第一个可选项
        self._select_first_selectable()

    def _make_category_header(self, category: str) -> QWidget:
        w = QWidget()
        w.setObjectName("cp_cat_header")
        w.setFixedHeight(22)
        layout = QHBoxLayout(w)
        layout.setContentsMargins(16, 0, 16, 0)
        lbl = QLabel(category.upper())
        lbl.setObjectName("cp_cat_label")
        layout.addWidget(lbl)
        layout.addStretch()
        return w

    def _make_command_row(self, cmd: Command) -> QWidget:
        w = QWidget()
        w.setObjectName("cp_row")
        w.setProperty("selected", False)
        w.setFixedHeight(44)

        layout = QHBoxLayout(w)
        layout.setContentsMargins(16, 4, 16, 4)
        layout.setSpacing(12)

        # 图标占位（可后期换成真实图标）
        icon_lbl = QLabel("›")
        icon_lbl.setObjectName("cp_row_icon")
        icon_lbl.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon_lbl)

        # 标题 + 描述
        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        title_lbl = QLabel(cmd.title)
        title_lbl.setObjectName("cp_row_title")
        text_col.addWidget(title_lbl)

        if cmd.description:
            desc_lbl = QLabel(cmd.description)
            desc_lbl.setObjectName("cp_row_desc")
            text_col.addWidget(desc_lbl)

        layout.addLayout(text_col)
        layout.addStretch()

        # 快捷键徽章
        if cmd.shortcut:
            sc_lbl = QLabel(cmd.shortcut)
            sc_lbl.setObjectName("cp_row_shortcut")
            layout.addWidget(sc_lbl)

        return w

    # ── 导航与执行 ─────────────────────────────────────────────────
    def _select_first_selectable(self):
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.flags() & Qt.ItemIsSelectable:
                self._list.setCurrentItem(item)
                self._highlight_row(item, True)
                break

    def _move_selection(self, delta: int):
        current = self._list.currentRow()
        count = self._list.count()
        if count == 0:
            return
        new_row = current + delta
        # 跳过分类标题
        while 0 <= new_row < count:
            item = self._list.item(new_row)
            if item.flags() & Qt.ItemIsSelectable:
                if current >= 0:
                    self._highlight_row(self._list.item(current), False)
                self._list.setCurrentRow(new_row)
                self._highlight_row(item, True)
                self._list.scrollToItem(item)
                return
            new_row += delta

    def _highlight_row(self, item: QListWidgetItem, selected: bool):
        w = self._list.itemWidget(item)
        if w:
            w.setProperty("selected", selected)
            w.style().unpolish(w)
            w.style().polish(w)

    def _execute_selected(self):
        item = self._list.currentItem()
        if item is None:
            return
        cmd: Command = item.data(Qt.UserRole)
        if cmd is None:
            return
        self.hide()
        try:
            cmd.action()
        except Exception as e:
            print(f"[CommandPalette] Error executing '{cmd.id}': {e}")
        self.command_executed.emit(cmd.id)

    def _on_item_clicked(self, item: QListWidgetItem):
        self._list.setCurrentItem(item)
        self._execute_selected()

    # ── 公开方法（供 MainWindow 调用） ─────────────────────────────
    def set_manager(self, manager: CommandManager):
        self._manager = manager


# ══════════════════════════════════════════════════════════════════
#  CommandBar  (向后兼容保留，仅转发 command_entered 信号)
# ══════════════════════════════════════════════════════════════════

from PySide6.QtWidgets import QCompleter, QLineEdit, QToolBar


class CommandBar(QToolBar):
    """原有的工具栏内嵌输入框，保持向后兼容。"""

    command_entered = Signal(str)

    def __init__(self, parent=None):
        super().__init__("Command Bar", parent)

        self.command_edit = QLineEdit()
        self.command_edit.setObjectName("commandBarEdit")
        from mathlab.utils.i18n_manager import get_i18n

        self.command_edit.setPlaceholderText(
            get_i18n().t("command_bar.placeholder") or "Enter command (Ctrl+Shift+P to open Command Palette)"
        )
        self.addWidget(self.command_edit)
        self.command_edit.returnPressed.connect(self._on_command_entered)
        self._setup_completer()

    def _setup_completer(self):
        commands = [
            "Point",
            "Circle",
            "Segment",
            "Polygon",
            "Line",
            "Ray",
            "Angle",
            "Midpoint",
            "Perpendicular",
            "Parallel",
            "Intersection",
            "Distance",
            "Area",
            "Clear",
        ]
        self.completer = QCompleter(commands, self)
        self.completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.command_edit.setCompleter(self.completer)

    def _on_command_entered(self):
        command = self.command_edit.text().strip()
        if command:
            self.command_entered.emit(command)
            self.command_edit.clear()

    def set_text(self, text: str):
        self.command_edit.setText(text)

    def clear(self):
        self.command_edit.clear()
