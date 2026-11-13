"""
MathConsole — 交互式数学控制台
支持 MATLAB/Octave 语法，执行后将结果渲染为富文本（HTML 表格）。
"""

import html
from typing import Any

import numpy as np
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFont, QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from mathlab.core.octave_bridge import OctaveBridge, OctaveBridgeError
from mathlab.ui.easter_eggs import EasterEggDetector
from mathlab.utils.i18n_manager import t
from mathlab.utils.theme_tokens import get_tokens

_FONT_MONO = "Consolas, 'Courier New', monospace"


def _mc_colors() -> dict[str, str]:
    """从主题 Design Token 派生 MathConsole 富文本调色板。"""
    tok = get_tokens()
    return {
        "bg_table": tok["bg.inset"],
        "input": tok["accent.base"],
        "prompt": tok["obj.polygon"],
        "scalar": tok["success"],
        "matrix": tok["obj.circle"],
        "key": tok["obj.function"],
        "accent": tok["success"],
        "warn": tok["warning"],
        "error": tok["danger"],
        "muted": tok["fg.muted"],
        "border": tok["border.subtle"],
    }


class MathConsole(QDockWidget):
    """
    交互式数学控制台 DockWidget

    - 接受 MATLAB/Octave 语法输入（OctaveBridge 翻译 + 执行）
    - 将 ndarray、dict、标量等结果渲染为 HTML 富文本表格
    - 支持命令历史（↑/↓）和 Tab 智能补全提示
    - 工作区变量通过 ``bridge.workspace()`` 持久存储
    """

    # 矩阵/向量渲染上限：超过阈值退化为文本摘要，防止大批量 DOM 节点卡死界面
    _MAX_RENDER_ROWS = 30
    _MAX_RENDER_COLS = 30

    def __init__(self, parent=None):
        from mathlab.utils.i18n_manager import get_i18n

        t = get_i18n().t
        title = t("math_console.title")
        if title == "math_console.title":
            title = "Interactive Console"
        super().__init__(f"{title} (Octave / NumEngine)", parent)
        self.setAllowedAreas(Qt.BottomDockWidgetArea | Qt.RightDockWidgetArea)
        self.setFeatures(
            QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable | QDockWidget.DockWidgetClosable
        )

        self.bridge = OctaveBridge()
        self._history: list[str] = []
        self._history_idx: int = -1

        # 初始化彩蛋检测器
        self.egg_detector = EasterEggDetector(self.topLevelWidget())

        self._build_ui()
        self._print_welcome()

    # ─────────────────────────────────────────────────────────────────────────
    # UI 搭建
    # ─────────────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ── 工具栏 ────────────────────────────────────────────────────────────
        toolbar = QWidget()
        toolbar.setObjectName("mathConsoleToolbar")
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(8, 4, 8, 4)
        tb_layout.setSpacing(6)

        lbl_title = QLabel("⟩  MathLab Console")
        lbl_title.setObjectName("mathConsoleTitle")
        tb_layout.addWidget(lbl_title)
        tb_layout.addStretch()

        self._lbl_ws = QLabel(t("math_console.workspace_empty") or "Workspace: Empty")
        self._lbl_ws.setObjectName("mathConsoleWsLabel")
        tb_layout.addWidget(self._lbl_ws)

        self._btn_clear = QPushButton(t("math_console.clear") or "Clear")
        self._btn_clear.setObjectName("mathConsoleActionBtn")
        self._btn_clear.setFixedHeight(24)
        self._btn_clear.clicked.connect(self._clear_output)
        tb_layout.addWidget(self._btn_clear)

        self._btn_reset = QPushButton(t("math_console.reset") or "Reset Workspace")
        self._btn_reset.setObjectName("mathConsoleActionBtn")
        self._btn_reset.setFixedHeight(24)
        self._btn_reset.clicked.connect(self._reset_workspace)
        tb_layout.addWidget(self._btn_reset)

        root_layout.addWidget(toolbar)

        # ── 输出区 ────────────────────────────────────────────────────────────
        self._output = QTextBrowser()
        self._output.setObjectName("mathConsoleOutput")
        self._output.setOpenLinks(False)
        self._output.setReadOnly(True)
        self._output.setFont(QFont("Consolas", 11))
        root_layout.addWidget(self._output, stretch=1)

        # ── 输入行 ────────────────────────────────────────────────────────────
        input_row = QWidget()
        input_row.setObjectName("mathConsoleInputRow")
        ir_layout = QHBoxLayout(input_row)
        ir_layout.setContentsMargins(8, 4, 8, 4)
        ir_layout.setSpacing(6)

        prompt_lbl = QLabel(">>")
        prompt_lbl.setObjectName("mathConsolePrompt")
        ir_layout.addWidget(prompt_lbl)

        self._input = QLineEdit()
        self._input.setObjectName("mathConsoleInput")
        self._input.setFont(QFont("Consolas", 12))
        self._input.setPlaceholderText(
            t("math_console.placeholder") or "Enter Octave syntax (e.g. A = [1 2; 3 4] or eig(A)) ..."
        )
        self._input.returnPressed.connect(self._execute)
        self._input.installEventFilter(self)
        ir_layout.addWidget(self._input, stretch=1)

        self._btn_run = QPushButton(t("math_console.run") or "▶ Run")
        self._btn_run.setObjectName("mathConsoleRunBtn")
        self._btn_run.setFixedHeight(28)
        self._btn_run.clicked.connect(self._execute)
        ir_layout.addWidget(self._btn_run)

        root_layout.addWidget(input_row)
        self.setWidget(root)

    # ─────────────────────────────────────────────────────────────────────────
    # 事件过滤器：历史导航（↑↓）
    # ─────────────────────────────────────────────────────────────────────────

    def eventFilter(self, obj, event) -> bool:
        if obj is self._input and event.type() == QEvent.KeyPress:
            key = event.key()
            if key == Qt.Key_Up:
                self._navigate_history(-1)
                return True
            if key == Qt.Key_Down:
                self._navigate_history(1)
                return True
        return super().eventFilter(obj, event)

    def _navigate_history(self, direction: int) -> None:
        if not self._history:
            return
        self._history_idx = max(0, min(len(self._history) - 1, self._history_idx + direction))
        self._input.setText(self._history[self._history_idx])

    # ─────────────────────────────────────────────────────────────────────────
    # 执行逻辑
    # ─────────────────────────────────────────────────────────────────────────

    def _execute(self) -> None:
        code = self._input.text().strip()
        if not code:
            return

        self._input.clear()
        self._history.append(code)
        self._history_idx = len(self._history)

        # 1. 优先检测并触发彩蛋（后台默默执行，不打断主业务流）
        self.egg_detector.check_and_trigger(code)

        # 打印输入行
        c = _mc_colors()
        safe_code = html.escape(code)
        self._append_html(
            f"<span style='color:{c['prompt']};font-weight:bold;'>&gt;&gt;</span>"
            f"&nbsp;<span style='color:{c['input']};'>{safe_code}</span><br>"
        )

        try:
            result = self.bridge.evaluate(code)
            if result is not None:
                self._append_html(self._render(result))
            self._append_html("<br>")
        except OctaveBridgeError as exc:
            safe_err = html.escape(str(exc)).replace("\n", "<br>")
            self._append_html(f"<span style='color:{c['error']};'>⚠ {safe_err}</span><br><br>")
        except Exception as exc:
            safe_err = html.escape(str(exc))
            err_label = t("math_console.internal_error")
            self._append_html(f"<span style='color:{c['error']};'>💥 {err_label}: {safe_err}</span><br><br>")

        self._update_workspace_label()
        self._scroll_to_bottom()

    # ─────────────────────────────────────────────────────────────────────────
    # 富文本渲染器
    # ─────────────────────────────────────────────────────────────────────────

    def _render(self, value: Any) -> str:
        """将任意计算结果递归渲染为 HTML 字符串"""
        if isinstance(value, np.ndarray):
            return self._render_ndarray(value)
        if isinstance(value, dict):
            return self._render_dict(value)
        if isinstance(value, (list, tuple)):
            return self._render_sequence(value)
        if isinstance(value, (int, float)):
            return self._render_scalar(value)
        if isinstance(value, complex):
            return self._render_scalar(value)
        c = _mc_colors()
        return f"<span style='color:{c['scalar']};font-family:{_FONT_MONO};'>" f"{html.escape(str(value))}</span><br>"

    def _render_ndarray(self, arr: np.ndarray) -> str:
        """渲染 numpy 数组 → HTML 表格"""
        if arr.ndim == 0:
            return self._render_scalar(arr.item())

        if arr.ndim == 1:
            return self._render_1d(arr)

        if arr.ndim == 2:
            return self._render_2d(arr)

        # 3D+: 显示 shape + repr
        c = _mc_colors()
        return (
            f"<span style='color:{c['muted']};font-size:10px;'>"
            f"ndarray {arr.shape} dtype={arr.dtype}</span>"
            f"<pre style='color:{c['matrix']};font-size:10px;margin:4px 0;'>"
            f"{html.escape(np.array2string(arr, precision=4, suppress_small=True))}"
            f"</pre>"
        )

    def _render_1d(self, arr: np.ndarray) -> str:
        c = _mc_colors()
        shape_hint = f"<span style='color:{c['muted']};font-size:10px;'>1×{len(arr)}</span>&nbsp;"
        # 超出阈值时降级为文本摘要，避免生成海量 DOM 节点拖死 QTextBrowser
        if len(arr) > self._MAX_RENDER_COLS:
            summary = html.escape(np.array2string(arr, precision=4, suppress_small=True, threshold=20))
            return shape_hint + (f"<pre style='color:{c['matrix']};font-size:10px;margin:4px 0;'>{summary}</pre>")
        td_style = self._td_style(c["matrix"])  # 样式串只需计算一次
        cells = "".join(f"<td style='{td_style}'>{self._fmt(v)}</td>" for v in arr)
        return shape_hint + f"<table style='{self._tbl_style()}'><tr>{cells}</tr></table>"

    def _render_2d(self, arr: np.ndarray) -> str:
        c = _mc_colors()
        rows, cols = arr.shape[0], arr.shape[1]

        if rows > self._MAX_RENDER_ROWS or cols > self._MAX_RENDER_COLS:
            summary = html.escape(np.array2string(arr, precision=4, suppress_small=True, threshold=20))
            hint_suffix = t("math_console.matrix_summary_hint")
            shape_hint = f"<span style='color:{c['muted']};font-size:10px;'>" f"{rows}×{cols} {hint_suffix}</span><br>"
            return shape_hint + f"<pre style='color:{c['matrix']};font-size:10px;margin:4px 0;'>{summary}</pre>"

        td_style = self._td_style(c["matrix"])  # 样式串只需计算一次
        rows_html = []
        for i, row in enumerate(arr):
            # 行号
            row_lbl = (
                f"<td style='color:{c['muted']};font-size:10px;"
                f"padding:2px 6px;text-align:right;border-right:1px solid {c['border']};'>"
                f"{i + 1}</td>"
            )
            cells = "".join(f"<td style='{td_style}'>{self._fmt(v)}</td>" for v in row)
            rows_html.append(f"<tr>{row_lbl}{cells}</tr>")

        shape_hint = (
            f"<span style='color:{c['muted']};font-size:10px;'>" f"{arr.shape[0]}×{arr.shape[1]} matrix</span><br>"
        )
        return shape_hint + f"<table style='{self._tbl_style()}'>" + "".join(rows_html) + "</table>"

    def _render_dict(self, d: dict) -> str:
        """渲染字典（eig/svd 等返回的结构化结果）"""
        c = _mc_colors()
        parts = []
        for key, val in d.items():
            safe_key = html.escape(str(key))
            inner = self._render(val)
            parts.append(
                f"<div style='margin:2px 0 6px 0;'>"
                f"<span style='color:{c['key']};font-weight:bold;"
                f"font-family:{_FONT_MONO};'>{safe_key}:</span>&nbsp;"
                f"{inner}</div>"
            )
        return "<div style='margin-left:12px;'>" + "".join(parts) + "</div>"

    def _render_sequence(self, seq) -> str:
        c = _mc_colors()
        items = "".join(f"<li style='color:{c['scalar']};'>{self._render(item)}</li>" for item in seq)
        return f"<ul style='margin:4px 0 8px 16px;padding:0;'>{items}</ul>"

    def _render_scalar(self, v) -> str:
        c = _mc_colors()
        return (
            f"<span style='color:{c['scalar']};"
            f"font-family:{_FONT_MONO};font-size:13px;'>"
            f"{self._fmt(v)}</span><br>"
        )

    # ─────────────────────────────────────────────────────────────────────────
    # 辅助方法
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _fmt(v) -> str:
        """数值格式化：自动选择科学计数法 / 定点数"""
        if isinstance(v, complex):
            r = f"{v.real:.4g}"
            i = f"{abs(v.imag):.4g}"
            sign = "+" if v.imag >= 0 else "−"
            return f"{r} {sign} {i}i"
        if isinstance(v, (np.floating, float)):
            return f"{v:.4g}"
        return html.escape(str(v))

    @staticmethod
    def _td_style(color: str) -> str:
        c = _mc_colors()
        return (
            f"padding:3px 12px;"
            f"border:1px solid {c['border']};"
            f"text-align:right;"
            f"color:{color};"
            f"font-family:{_FONT_MONO};"
            f"font-size:12px;"
        )

    @staticmethod
    def _tbl_style() -> str:
        c = _mc_colors()
        return f"border-collapse:collapse;" f"margin:4px 0 10px 0;" f"background:{c['bg_table']};"

    def _append_html(self, html_str: str) -> None:
        cursor = self._output.textCursor()
        cursor.movePosition(QTextCursor.End)
        self._output.setTextCursor(cursor)
        self._output.insertHtml(html_str)

    def _scroll_to_bottom(self) -> None:
        sb = self._output.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _print_welcome(self) -> None:
        c = _mc_colors()
        backend_info = (
            t("math_console.backend_info")
            or "Backend: NumPy / SciPy / NumEngine &nbsp;·&nbsp; Syntax: MATLAB/Octave Compatible<br>"
        )
        hint1 = (
            t("math_console.hint1") or "Hint: Enter <code style='color:{0};'>A = [1 2; 3 4]</code> to build matrix, "
        )
        hint1 = hint1.format(c["input"])
        hint2 = (
            t("math_console.hint2") or "<code style='color:{0};'>eig(A)</code> for eigenvalues, ↑↓ to browse history"
        )
        hint2 = hint2.format(c["input"])
        self._append_html(
            f"<div style='margin-bottom:12px;'>"
            f"<span style='color:{c['accent']};font-size:14px;font-weight:bold;'>"
            f"MathLab Console  v2.6</span><br>"
            f"<span style='color:{c['muted']};font-size:11px;'>"
            f"{backend_info}"
            f"{hint1}"
            f"{hint2}</span></div>"
        )

    def _clear_output(self) -> None:
        self._output.clear()
        self._print_welcome()

    def _reset_workspace(self) -> None:
        c = _mc_colors()
        self.bridge.reset()
        self._clear_output()
        reset_success = t("math_console.reset_success") or "✓ Workspace reset"
        self._append_html(f"<span style='color:{c['muted']};font-size:11px;'>" f"{reset_success}</span><br><br>")
        self._update_workspace_label()

    def _update_workspace_label(self) -> None:
        ws = self.bridge.workspace()
        if ws:
            names = ", ".join(list(ws.keys())[:8])
            suffix = " …" if len(ws) > 8 else ""
            workspace_prefix = t("math_console.workspace") or "Workspace"
            vars_suffix = t("math_console.vars") or "vars"
            self._lbl_ws.setText(f"{workspace_prefix}: {names}{suffix}  ({len(ws)} {vars_suffix})")
        else:
            self._lbl_ws.setText(t("math_console.workspace_empty") or "Workspace: Empty")

    def retranslate_ui(self) -> None:
        """更新所有 UI 文本为当前语言"""
        # Dock 标题不再 .upper()：中文没有大小写语义，且会把英文标题压成难读的大写
        # （其余 Dock 已在 R-14/UI-10 清掉，这里是漏网的一处；切换语言时会重新大写）
        self.setWindowTitle(t("math_console.title"))
        if hasattr(self, "_lbl_ws"):
            self._update_workspace_label()
        if hasattr(self, "_btn_clear"):
            self._btn_clear.setText(t("math_console.clear") or "Clear")
        if hasattr(self, "_btn_reset"):
            self._btn_reset.setText(t("math_console.reset") or "Reset Workspace")
        if hasattr(self, "_input"):
            self._input.setPlaceholderText(
                t("math_console.placeholder") or "Enter Octave syntax (e.g. A = [1 2; 3 4] or eig(A)) ..."
            )
        if hasattr(self, "_btn_run"):
            self._btn_run.setText(t("math_console.run") or "▶ Run")

    # ─────────────────────────────────────────────────────────────────────────
    # 公开 API（供 main_window 调用）
    # ─────────────────────────────────────────────────────────────────────────

    def inject_code(self, code: str) -> None:
        """外部注入一行代码（静默执行，不显示提示符）"""
        try:
            self.bridge.evaluate(code)
            self._update_workspace_label()
        except Exception:
            pass

    def display_message(self, msg: str, level: str = "info") -> None:
        """向控制台输出一条系统消息"""
        c = _mc_colors()
        color = {
            "info": c["accent"],
            "warn": c["warn"],
            "error": c["error"],
        }.get(level, c["muted"])
        safe = html.escape(msg).replace("\n", "<br>")
        self._append_html(f"<span style='color:{color};font-size:11px;'>{safe}</span><br>")
        self._scroll_to_bottom()
