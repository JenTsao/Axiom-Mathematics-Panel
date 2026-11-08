"""命令面板注册 Mixin。

将 MainWindow 中与 CommandManager 命令注册相关的方法提取到此模块。
所有用户可见文案一律走 ``t()``，key 收在 ``commands`` / ``main_window`` 命名空间。
"""

import os
import platform
import subprocess

from mathlab.core.command_manager import Command
from mathlab.utils.i18n_manager import t
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

        # 分组名一次性取值，避免每条命令重复调用 t()
        g_view = t("commands.group_view")
        g_file = t("commands.group_file")
        g_canvas = t("commands.group_canvas")
        g_workspace = t("commands.group_workspace")
        g_var = t("commands.group_var")
        g_tpl = t("commands.group_tpl")
        g_edit = t("commands.group_edit")
        g_system = t("commands.group_system")

        # ── 视图 ────────────────────────────────────────────────────────
        reg(C("view.algebra", t("commands.view_show_algebra"), lambda: self.algebra_panel.show(), g_view, "Ctrl+1"))
        reg(
            C(
                "view.properties",
                t("commands.view_show_properties"),
                lambda: self.properties_panel.show(),
                g_view,
                "Ctrl+2",
            )
        )
        reg(C("view.console", t("commands.view_show_console"), lambda: self.console.show(), g_view, "Ctrl+3"))
        reg(
            C(
                "view.algo",
                t("commands.view_show_algo"),
                lambda: (self.algo_vis_panel.show(), self.algo_vis_panel.raise_()),
                g_view,
            )
        )
        reg(
            C(
                "view.ai",
                t("commands.view_show_ai"),
                lambda: (self.ai_tools_panel.show(), self.ai_tools_panel.raise_()),
                g_view,
            )
        )
        reg(
            C(
                "view.function",
                t("commands.view_show_function"),
                lambda: (self.function_explorer.show(), self.function_explorer.raise_()),
                g_view,
            )
        )
        reg(C("view.hide.algebra", t("commands.view_hide_algebra"), lambda: self.algebra_panel.hide(), g_view))
        reg(
            C(
                "view.hide.properties",
                t("commands.view_hide_properties"),
                lambda: self.properties_panel.hide(),
                g_view,
            )
        )
        reg(C("view.hide.console", t("commands.view_hide_console"), lambda: self.console.hide(), g_view))
        reg(C("view.hide.algo", t("commands.view_hide_algo"), lambda: self.algo_vis_panel.hide(), g_view))
        reg(C("view.hide.ai", t("commands.view_hide_ai"), lambda: self.ai_tools_panel.hide(), g_view))

        # ── 文件 ────────────────────────────────────────────────────────
        reg(C("file.new", t("main_window.new_project"), self.on_new_project, g_file, "Ctrl+N"))
        reg(C("file.open", t("main_window.open_project"), self.on_open_project, g_file, "Ctrl+O"))
        reg(C("file.save", t("main_window.save_project"), self.on_save_project, g_file, "Ctrl+S"))
        reg(C("file.save_as", t("main_window.save_as"), self.on_save_project_as, g_file, "Ctrl+Shift+S"))
        reg(C("file.export.png", t("main_window.export_png"), self.on_export_png, g_file))
        reg(C("file.export.svg", t("main_window.export_svg"), self.on_export_svg, g_file))
        reg(C("file.export.tex", t("main_window.export_latex"), self.on_export_latex, g_file))

        # ── 画布 ────────────────────────────────────────────────────────
        reg(C("canvas.clear", t("commands.canvas_clear"), self.on_clear_canvas, g_canvas))
        reg(
            C(
                "canvas.zoom_in",
                t("main_window.zoom_in"),
                lambda: self.central_widget.zoom_in(),
                g_canvas,
                "Ctrl+=",
            )
        )
        reg(
            C(
                "canvas.zoom_out",
                t("main_window.zoom_out"),
                lambda: self.central_widget.zoom_out(),
                g_canvas,
                "Ctrl+-",
            )
        )
        reg(C("tool.select", t("commands.tool_select"), lambda: self.on_action_selected("select"), g_canvas, "Alt+S"))
        reg(C("tool.point", t("commands.tool_point"), lambda: self.on_action_selected("point"), g_canvas, "Alt+P"))
        reg(
            C("tool.segment", t("commands.tool_segment"), lambda: self.on_action_selected("segment"), g_canvas, "Alt+L")
        )
        reg(C("tool.circle", t("commands.tool_circle"), lambda: self.on_action_selected("circle"), g_canvas, "Alt+C"))
        reg(
            C("tool.polygon", t("commands.tool_polygon"), lambda: self.on_action_selected("polygon"), g_canvas, "Alt+G")
        )
        reg(C("tool.pan", t("commands.tool_pan"), lambda: self.on_action_selected("pan"), g_canvas, "Alt+H"))

        # ── 笔记本与工作区 ────────────────────────────────────────────────
        reg(
            C(
                "notebook.new",
                t("commands.notebook_new"),
                lambda: (
                    self.central_tabs.setCurrentWidget(self.notebook),
                    self.notebook.backend.cells.clear(),
                    self._refresh_notebook_ui(),
                ),
                g_workspace,
            )
        )
        reg(
            C(
                "notebook.run_all",
                t("commands.notebook_run_all"),
                lambda: (
                    self.central_tabs.setCurrentWidget(self.notebook),
                    self.notebook.run_all_cells(),
                ),
                g_workspace,
            )
        )
        reg(
            C(
                "notebook.clear",
                t("commands.notebook_clear"),
                lambda: (
                    self.central_tabs.setCurrentWidget(self.notebook),
                    self.notebook.clear_all_outputs(),
                ),
                g_workspace,
            )
        )

        if self.geogebra_panel:
            reg(
                C(
                    "geometry.open",
                    t("commands.geometry_open"),
                    lambda: self.central_tabs.setCurrentWidget(self.geogebra_panel),
                    g_workspace,
                )
            )

        # ── 变量注入 ────────────────────────────────────────────────────
        def _inject(name, expr):
            self.console.inject_variable(name, expr)

        reg(
            C(
                "var.pi",
                t("commands.var_pi"),
                lambda: _inject("PI", "3.141592653589793"),
                g_var,
                "",
                "≈ 3.14159",
            )
        )
        reg(
            C(
                "var.e",
                t("commands.var_e"),
                lambda: _inject("E", "2.718281828459045"),
                g_var,
                "",
                "≈ 2.71828",
            )
        )
        reg(
            C(
                "var.phi",
                t("commands.var_phi"),
                lambda: _inject("PHI", "1.618033988749895"),
                g_var,
                "",
                "≈ 1.61803",
            )
        )
        reg(
            C(
                "var.sqrt2",
                t("commands.var_sqrt2"),
                lambda: _inject("SQRT2", "1.4142135623730951"),
                g_var,
                "",
                "≈ 1.41421",
            )
        )
        reg(C("var.inf", t("commands.var_inf"), lambda: _inject("INF", 'float("inf")'), g_var))
        reg(
            C(
                "var.deg",
                t("commands.var_deg"),
                lambda: _inject("DEG2RAD", "0.017453292519943295"),
                g_var,
                "",
                "° → rad",
            )
        )

        # ── 模板插入 ────────────────────────────────────────────────────
        def _insert(text):
            self.console.insert_text_at_cursor(text)

        reg(C("tpl.integrate", t("commands.tpl_integrate"), lambda: _insert("integrate(f, x)"), g_tpl))
        reg(C("tpl.diff", t("commands.tpl_diff"), lambda: _insert("diff(f, x)"), g_tpl))
        reg(C("tpl.limit", t("commands.tpl_limit"), lambda: _insert("limit(f, x, 0)"), g_tpl))
        reg(C("tpl.solve", t("commands.tpl_solve"), lambda: _insert("solve(f, x)"), g_tpl))
        reg(C("tpl.matrix", t("commands.tpl_matrix"), lambda: _insert("Matrix([[1,0],[0,1]])"), g_tpl))
        reg(C("tpl.plot_sin", t("commands.tpl_plot_sin"), lambda: _insert("sin(x)"), g_tpl))
        reg(C("tpl.plot_cos", t("commands.tpl_plot_cos"), lambda: _insert("cos(x)"), g_tpl))
        reg(C("tpl.plot_normal", t("commands.tpl_plot_normal"), lambda: _insert("exp(-x**2/2)"), g_tpl))
        reg(C("tpl.taylor", t("commands.tpl_taylor"), lambda: _insert("series(f, x, 0, 6)"), g_tpl))

        # ── 系统 ────────────────────────────────────────────────────────
        # ── 撤销/重做（R-10 / §6.4：不并轨 CommandManager，仅暴露给命令面板） ──
        undo_stack = getattr(self, "undo_stack", None)
        if undo_stack is not None and undo_stack.enabled:
            reg(C("undo.last", t("main_window.undo"), undo_stack.undo, g_edit, "Ctrl+Z"))
            reg(C("redo.last", t("main_window.redo"), undo_stack.redo, g_edit, "Ctrl+Y"))

        reg(C("sys.preferences", t("main_window.preferences"), self.show_preferences_dialog, g_system, "Ctrl+,"))
        reg(C("sys.theme", t("commands.sys_theme"), self._toggle_theme, g_system))
        reg(C("sys.language", t("main_window.language"), self.show_language_dialog, g_system))
        reg(C("sys.about", t("commands.sys_about"), self.show_about, g_system))
        reg(C("sys.console.clear", t("commands.sys_console_clear"), self.console.clear, g_system))
        reg(C("sys.exit", t("main_window.exit"), self.close, g_system, "Alt+F4"))

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
                    self.console.display_system_message(t("commands.open_logs_failed", str(e)))

        reg(
            C(
                "sys.open_logs",
                t("commands.sys_open_logs"),
                _open_log_dir,
                g_system,
                description=f"{t('commands.log_path')}: {LOG_DIR}",
            )
        )
