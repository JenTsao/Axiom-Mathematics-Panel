"""命令面板注册 Mixin。

将 MainWindow 中与 CommandManager 命令注册相关的方法提取到此模块。
"""

import os
import platform
import subprocess

from mathlab.core.command_manager import Command
from mathlab.utils.logger import LOG_DIR, get_logger

logger = get_logger(__name__)


class CommandsMixin:
    """MainWindow Mixin：命令面板注册。"""

    def _show_command_palette(self) -> None:
        """居中显示命令面板层。"""
        self.cmd_palette.show_centered_on(self)

    def _register_commands(self) -> None:
        """向 CommandManager 注册所有默认命令。

        分类设计：
          视图   — 面板切换、dock 显隐
          文件   — 新建、打开、保存、导出
          画布   — 清空、缩放、工具切换
          变量   — 常用数学常量注入
          模板   — 向控制台插入常用公式模板
          系统   — 主题、语言、首选项
        """
        reg = self.cmd_manager.register
        C = Command

        # ── 视图 ────────────────────────────────────────────────────────
        reg(
            C(
                "view.algebra",
                "显示 代数面板",
                lambda: self.algebra_panel.show(),
                "视图",
                "Ctrl+1",
            )
        )  # noqa: E272,E241
        reg(
            C(
                "view.properties",
                "显示 属性面板",
                lambda: self.properties_panel.show(),
                "视图",
                "Ctrl+2",
            )
        )  # noqa: E272,E241
        reg(
            C(
                "view.console",
                "显示 Python 控制台",
                lambda: self.console.show(),
                "视图",
                "Ctrl+3",
            )
        )  # noqa: E272,E241
        reg(
            C(
                "view.algo",
                "显示 算法可视化面板",
                lambda: (self.algo_vis_panel.show(), self.algo_vis_panel.raise_()),
                "视图",
            )
        )  # noqa: E272,E241
        reg(
            C(
                "view.ai",
                "显示 AI 工具面板",
                lambda: (self.ai_tools_panel.show(), self.ai_tools_panel.raise_()),
                "视图",
            )
        )  # noqa: E272,E241
        reg(
            C(
                "view.function",
                "显示 函数探索器",
                lambda: (
                    self.function_explorer.show(),
                    self.function_explorer.raise_(),
                ),
                "视图",
            )
        )  # noqa: E272,E241

        reg(
            C(
                "view.hide.algebra",
                "隐藏 代数面板",
                lambda: self.algebra_panel.hide(),
                "视图",
            )
        )  # noqa: E272,E241
        reg(
            C(
                "view.hide.properties",
                "隐藏 属性面板",
                lambda: self.properties_panel.hide(),
                "视图",
            )
        )  # noqa: E272,E241
        reg(
            C(
                "view.hide.console",
                "隐藏 Python 控制台",
                lambda: self.console.hide(),
                "视图",
            )
        )  # noqa: E272,E241
        reg(
            C(
                "view.hide.algo",
                "隐藏 算法可视化面板",
                lambda: self.algo_vis_panel.hide(),
                "视图",
            )
        )  # noqa: E272,E241
        reg(
            C(
                "view.hide.ai",
                "隐藏 AI 工具面板",
                lambda: self.ai_tools_panel.hide(),
                "视图",
            )
        )  # noqa: E272,E241

        # ── 文件 ────────────────────────────────────────────────────────
        reg(C("file.new", "新建项目", self.on_new_project, "文件", "Ctrl+N"))
        reg(C("file.open", "打开项目…", self.on_open_project, "文件", "Ctrl+O"))
        reg(C("file.save", "保存项目", self.on_save_project, "文件", "Ctrl+S"))
        reg(
            C(
                "file.save_as",
                "另存项目…",
                self.on_save_project_as,
                "文件",
                "Ctrl+Shift+S",
            )
        )
        reg(C("file.export.png", "导出 PNG 图片", self.on_export_png, "文件"))
        reg(C("file.export.svg", "导出 SVG 矢量图", self.on_export_svg, "文件"))
        reg(C("file.export.tex", "导出 LaTeX 文档", self.on_export_latex, "文件"))

        # ── 画布 ────────────────────────────────────────────────────────
        reg(C("canvas.clear", "清空画布与变量", self.on_clear_canvas, "画布"))
        reg(
            C(
                "canvas.zoom_in",
                "放大画布",
                lambda: self.central_widget.zoom_in(),
                "画布",
                "Ctrl+=",
            )
        )  # noqa: E272,E241
        reg(
            C(
                "canvas.zoom_out",
                "缩小画布",
                lambda: self.central_widget.zoom_out(),
                "画布",
                "Ctrl+-",
            )
        )  # noqa: E272,E241
        reg(
            C(
                "tool.select",
                "切换工具: 选择",
                lambda: self.on_action_selected("select"),
                "画布",
                "Alt+S",
            )
        )  # noqa: E272,E241
        reg(
            C(
                "tool.point",
                "切换工具: 点",
                lambda: self.on_action_selected("point"),
                "画布",
                "Alt+P",
            )
        )  # noqa: E272,E241
        reg(
            C(
                "tool.segment",
                "切换工具: 线段",
                lambda: self.on_action_selected("segment"),
                "画布",
                "Alt+L",
            )
        )  # noqa: E272,E241
        reg(
            C(
                "tool.circle",
                "切换工具: 圆",
                lambda: self.on_action_selected("circle"),
                "画布",
                "Alt+C",
            )
        )  # noqa: E272,E241
        reg(
            C(
                "tool.polygon",
                "切换工具: 多边形",
                lambda: self.on_action_selected("polygon"),
                "画布",
                "Alt+G",
            )
        )  # noqa: E272,E241
        reg(
            C(
                "tool.pan",
                "切换工具: 平移画布",
                lambda: self.on_action_selected("pan"),
                "画布",
                "Alt+H",
            )
        )  # noqa: E272,E241

        # ── 笔记本与工作区 ────────────────────────────────────────────────────────
        reg(
            C(
                "notebook.new",
                "新建笔记本 (> new notebook)",
                lambda: (
                    self.central_tabs.setCurrentWidget(self.notebook),
                    self.notebook.backend.cells.clear(),
                    self._refresh_notebook_ui(),
                ),
                "工作区",
            )
        )
        reg(
            C(
                "notebook.run_all",
                "运行全部代码块 (> run all)",
                lambda: (
                    self.central_tabs.setCurrentWidget(self.notebook),
                    self.notebook.run_all_cells(),
                ),
                "工作区",
            )
        )  # noqa: E272,E241
        reg(
            C(
                "notebook.clear",
                "清空所有输出 (> clear output)",
                lambda: (
                    self.central_tabs.setCurrentWidget(self.notebook),
                    self.notebook.clear_all_outputs(),
                ),
                "工作区",
            )
        )

        if self.geogebra_panel:
            reg(
                C(
                    "geometry.open",
                    "打开几何画板 (> open geometry)",
                    lambda: self.central_tabs.setCurrentWidget(self.geogebra_panel),
                    "工作区",
                )
            )

        # ── 变量注入 ────────────────────────────────────────────────────
        def _inject(name, expr):
            self.console.inject_variable(name, expr)

        reg(
            C(
                "var.pi",
                "注入常量: 圆周率 PI",
                lambda: _inject("PI", "3.141592653589793"),
                "变量",
                "",
                "≈ 3.14159",
            )
        )  # noqa: E272,E241
        reg(
            C(
                "var.e",
                "注入常量: 自然常数 E",
                lambda: _inject("E", "2.718281828459045"),
                "变量",
                "",
                "≈ 2.71828",
            )
        )  # noqa: E272,E241
        reg(
            C(
                "var.phi",
                "注入常量: 黄金分割比 PHI",
                lambda: _inject("PHI", "1.618033988749895"),
                "变量",
                "",
                "≈ 1.61803",
            )
        )  # noqa: E272,E241
        reg(
            C(
                "var.sqrt2",
                "注入常量: 根号 2 SQRT2",
                lambda: _inject("SQRT2", "1.4142135623730951"),
                "变量",
                "",
                "≈ 1.41421",
            )
        )  # noqa: E272,E241
        reg(
            C(
                "var.inf",
                "注入常量: 正无穷 INF",
                lambda: _inject("INF", 'float("inf")'),
                "变量",
            )
        )  # noqa: E272,E241
        reg(
            C(
                "var.deg",
                "注入常量: 度转弧系数 DEG2RAD",
                lambda: _inject("DEG2RAD", "0.017453292519943295"),
                "变量",
                "",
                "° → rad",
            )
        )  # noqa: E272,E241

        # ── 模板插入 ────────────────────────────────────────────────────
        def _insert(text):
            self.console.insert_text_at_cursor(text)

        reg(
            C(
                "tpl.integrate",
                "插入模板: 不定积分",
                lambda: _insert("integrate(f, x)"),
                "模板",
            )
        )  # noqa: E272,E241
        reg(C("tpl.diff", "插入模板: 导数", lambda: _insert("diff(f, x)"), "模板"))  # noqa: E272,E241
        reg(C("tpl.limit", "插入模板: 极限", lambda: _insert("limit(f, x, 0)"), "模板"))  # noqa: E272,E241
        reg(C("tpl.solve", "插入模板: 方程求解", lambda: _insert("solve(f, x)"), "模板"))  # noqa: E272,E241
        reg(
            C(
                "tpl.matrix",
                "插入模板: 2x2 矩阵",
                lambda: _insert("Matrix([[1,0],[0,1]])"),
                "模板",
            )
        )  # noqa: E272,E241
        reg(
            C(
                "tpl.plot_sin",
                "插入模板: 正弦函数绘图",
                lambda: _insert("sin(x)"),
                "模板",
            )
        )  # noqa: E272,E241
        reg(
            C(
                "tpl.plot_cos",
                "插入模板: 余弦函数绘图",
                lambda: _insert("cos(x)"),
                "模板",
            )
        )  # noqa: E272,E241
        reg(
            C(
                "tpl.plot_normal",
                "插入模板: 正态分布函数",
                lambda: _insert("exp(-x**2/2)"),
                "模板",
            )
        )  # noqa: E272,E241
        reg(
            C(
                "tpl.taylor",
                "插入模板: Taylor 展开",
                lambda: _insert("series(f, x, 0, 6)"),
                "模板",
            )
        )  # noqa: E272,E241

        # ── 系统 ────────────────────────────────────────────────────────
        # ── 撤销/重做（R-10 / §6.4：不并轨 CommandManager，仅暴露给命令面板） ──
        undo_stack = getattr(self, "undo_stack", None)
        if undo_stack is not None and undo_stack.enabled:
            reg(C("undo.last", "撤销", undo_stack.undo, "编辑", "Ctrl+Z"))
            reg(C("redo.last", "重做", undo_stack.redo, "编辑", "Ctrl+Y"))

        reg(
            C(
                "sys.preferences",
                "打开首选项",
                self.show_preferences_dialog,
                "系统",
                "Ctrl+,",
            )
        )
        reg(
            C(
                "sys.theme",
                "切换主题 / 深色模式 (> toggle dark mode)",
                self._toggle_theme,
                "系统",
            )
        )
        reg(C("sys.language", "切换语言", self.show_language_dialog, "系统"))
        reg(C("sys.about", "关于 Axiom Mathematics", self.show_about, "系统"))
        reg(C("sys.console.clear", "清空控制台", self.console.clear, "系统"))
        reg(C("sys.exit", "退出 MathLab (> exit)", self.close, "系统", "Alt+F4"))

        # ── 日志 ────────────────────────────────────────────────────────
        def _open_log_dir():
            """跨平台打开运行日志目录，方便用户拖取日志文件提交 Bug 报告。"""
            try:
                if platform.system() == "Windows":
                    os.startfile(LOG_DIR)
                elif platform.system() == "Darwin":
                    subprocess.Popen(["open", LOG_DIR])
                else:
                    subprocess.Popen(["xdg-open", LOG_DIR])
                logger.info("用户打开了日志目录: %s", LOG_DIR)
            except Exception as e:
                logger.error("无法打开日志目录: %s", e)
                if hasattr(self, "console"):
                    self.console.display_system_message(f"无法打开日志目录: {e}")

        reg(
            C(
                "sys.open_logs",
                "系统：打开运行日志目录 (Open Logs)",
                _open_log_dir,
                "系统",
                description=f"日志路径: {LOG_DIR}",
            )
        )
