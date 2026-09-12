"""UI 布局组装与面板切换 Mixin。

将 MainWindow 中与 UI 构建、Dock 面板创建和面板显隐切换
相关的方法提取到此模块，降低主窗口文件的体积与复杂度。
"""

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QDockWidget, QTabWidget

from .ai_tools_panel import AIToolsPanel
from .algebra_panel import AlgebraPanel
from .algo_vis_panel import AlgoVisPanel
from .animations import fade_in, fade_out
from .canvas import GeometryCanvas
from .command_bar import CommandPalette
from .console import PythonConsole
from .function_explorer_panel import FunctionExplorerPanel
from .math_console import MathConsole
from .notebook_panel import NotebookPanel
from .properties_panel import PropertiesPanel

# Soft dependencies
try:
    from mathlab.core.jupyter_manager import JupyterManager
    from mathlab.ui.jupyter_panel import JupyterPanel
except ImportError:
    JupyterPanel = None
    JupyterManager = None

from mathlab.utils.i18n_manager import t
from mathlab.utils.logger import get_logger

logger = get_logger(__name__)


class UISetupMixin:
    """MainWindow Mixin：UI 布局组装与面板切换。"""

    def setup_ui(self):
        self.central_tabs = QTabWidget()
        self.central_tabs.setStyleSheet("QTabWidget::pane { border: none; }")

        self.central_widget = GeometryCanvas(self)
        self.notebook = NotebookPanel(self)
        self.notebook.ai_explain_requested.connect(self.handle_ai_explain)

        try:
            from .geometry_panel import GeometryPanel

            self.geogebra_panel = GeometryPanel(self)
            if hasattr(self.geogebra_panel, "canvas"):
                self.geogebra_panel.canvas.ipc_client = self.ipc_client
        except ImportError:
            self.geogebra_panel = None

        self.central_tabs.addTab(self.notebook, t("notebook.title") or "Interactive Notebook")
        self.central_tabs.addTab(self.central_widget, t("main_window.geometry_tools") or "Geometry Canvas")
        if self.geogebra_panel:
            self.central_tabs.addTab(self.geogebra_panel, "Mini GeoGebra")

        # ── 🌌 JupyterLab 嵌入工作区 ────────────────────────────────────────────
        self._init_jupyter_tab()

        self.setCentralWidget(self.central_tabs)

    def _init_jupyter_tab(self):
        """在后台线程启动 JupyterLab，避免阻塞 UI 初始化"""
        self.jupyter_mgr = None
        self.jupyter_workspace = None

        if JupyterManager is None or JupyterPanel is None:
            logger.warning("JupyterManager / JupyterPanel 未能导入，Jupyter 标签页已跳过。")
            return

        try:
            self.jupyter_mgr = JupyterManager()
            # 创建面板（此时服务还未就绪，面板显示加载动画）
            self.jupyter_workspace = JupyterPanel(self.jupyter_mgr.url, self)
            self.central_tabs.addTab(self.jupyter_workspace, "🌌 Jupyter 工作区")

            # 在后台线程启动服务，就绪后触发页面加载
            import threading

            def _start_and_load():
                success = self.jupyter_mgr.start(timeout=getattr(self.jupyter_mgr, "_default_timeout", 30))
                # 切回主线程执行 UI 操作（Qt 要求 UI 操作在主线程）
                from PySide6.QtCore import QMetaObject, Qt

                if success:
                    QMetaObject.invokeMethod(
                        self.jupyter_workspace,
                        "load_workspace",
                        Qt.ConnectionType.QueuedConnection,
                    )
                else:
                    # 启动失败，在主线程中安全地显示错误
                    def _show_error():
                        if hasattr(self.jupyter_workspace, "_card"):
                            self.jupyter_workspace._card.show_error(
                                f"JupyterLab 服务器启动失败\n"
                                f"端口：{self.jupyter_mgr.port}\n\n"
                                f"请确认 jupyterlab 已安装:\n"
                                f"  pip install jupyterlab"
                            )

                    from PySide6.QtCore import QTimer

                    QTimer.singleShot(0, _show_error)

            t_jupyter = threading.Thread(target=_start_and_load, daemon=True, name="JupyterStartup")
            t_jupyter.start()
            logger.info("JupyterLab 后台启动线程已派发，端口：%s", self.jupyter_mgr.port)

        except Exception as exc:
            logger.warning("Jupyter 初始化失败（不影响其他功能）：%s", exc)

    def setup_docks(self):
        self.algebra_panel = AlgebraPanel(self)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.algebra_panel)
        self.algebra_panel.setWindowTitle(t("algebra_panel.title").upper())

        self.properties_panel = PropertiesPanel(self)
        self.addDockWidget(Qt.RightDockWidgetArea, self.properties_panel)
        self.properties_panel.setWindowTitle(t("properties_panel.title").upper())

        self.console = PythonConsole(self)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.console)
        self.console.setWindowTitle(t("console.title").upper())
        self.console.set_python_repl(self.python_repl)

        # ── 数学控制台（Octave / NumEngine 交互终端）────────────────────────────
        self.math_console = MathConsole(self)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.math_console)
        # 与 Python Console 合并为 Tab（底部共享一个停靠区）
        self.tabifyDockWidget(self.console, self.math_console)
        # 默认显示 Python Console（让 math_console 在背景 Tab）
        self.console.raise_()

        # 函数探索器面板
        self.function_explorer = FunctionExplorerPanel(self)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.function_explorer)
        self.function_explorer.setWindowTitle(t("function_explorer.title").upper())
        self.function_explorer.hide()  # 默认隐藏

        self.algo_vis_panel = AlgoVisPanel(self)
        self.addDockWidget(Qt.RightDockWidgetArea, self.algo_vis_panel)
        self.algo_vis_panel.setWindowTitle(t("algo_vis.title").upper())
        self.algo_vis_panel.hide()

        self.ai_tools_panel = AIToolsPanel(self)
        self.addDockWidget(Qt.RightDockWidgetArea, self.ai_tools_panel)
        self.ai_tools_panel.setWindowTitle(t("ai_tools.title").upper())
        self.ai_tools_panel.hide()

        self.tabifyDockWidget(self.algo_vis_panel, self.ai_tools_panel)

        # ── 命令面板（悬浮层，必须在 setup_docks 结尾创建） ───────────────────────
        self.cmd_palette = CommandPalette(self.cmd_manager, self)

        # Ctrl+Shift+P 唤醒命令面板
        palette_shortcut = QShortcut(QKeySequence("Ctrl+Shift+P"), self)
        palette_shortcut.activated.connect(self._show_command_palette)

        # Ctrl+P 备用快捷键
        palette_shortcut2 = QShortcut(QKeySequence("Ctrl+P"), self)
        palette_shortcut2.activated.connect(self._show_command_palette)

        # ── ✨ 信号接线：数学控制台 plot() 命令 → ECharts 渲染 ────────────────
        # math_console.bridge.signals 是 BridgeSignals(QObject)，
        # plot_requested 发射一个包含 x/y/type/title 的 dict。
        self.math_console.bridge.signals.plot_requested.connect(self.handle_console_plot)

    def load_stylesheet(self):
        try:
            from mathlab.utils.theme_manager import get_theme_colors

            theme = get_theme_colors()

            stylesheet_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ui", "styles.qss")
            with open(stylesheet_path, "r", encoding="utf-8") as f:
                qss = f.read()

            if theme["name"] != "Dark":
                qss = qss.replace("#13131A", theme["background"])
                qss = qss.replace("#E0E0E6", theme["foreground"])
                qss = qss.replace("#1E1E28", theme["panel_bg"])
                qss = qss.replace("#2A2A35", theme["panel_border"])
                qss = qss.replace("#181822", theme["console_bg"])
                qss = qss.replace("#323242", theme["panel_border"])
                qss = qss.replace("#FFFFFF", theme["console_fg"])
                qss = qss.replace("#00A67E", theme["accent"])
                qss = qss.replace("#2A2A38", theme["panel_bg"])
                qss = qss.replace("#3A3A4A", theme["panel_border"])
                qss = qss.replace("#353545", theme["panel_border"])

            self.setStyleSheet(qss)
        except Exception as e:
            logger.warning("样式表加载失败: %s", e)

    def _refresh_notebook_ui(self) -> None:
        # 暴力清空 UI 然后让其重新为空
        from mathlab.core.notebook import CellType

        layout = self.notebook.canvas_layout
        while layout.count() > 1:  # 结尾有弹簧
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.notebook.ui_cells.clear()
        # add_new_cell 接收 CellType 枚举（此前误传 NotebookCell 实例）
        self.notebook.add_new_cell(CellType.CODE)

    def toggle_algebra_panel(self, visible: bool) -> None:
        if visible:
            self.algebra_panel.show()
            fade_in(self.algebra_panel)
        else:
            fade_out(self.algebra_panel, callback=self.algebra_panel.hide)

    def toggle_properties_panel(self, visible: bool) -> None:
        if visible:
            self.properties_panel.show()
            fade_in(self.properties_panel)
        else:
            fade_out(self.properties_panel, callback=self.properties_panel.hide)

    def toggle_console(self, visible: bool) -> None:
        if visible:
            self.console.show()
            fade_in(self.console)
        else:
            fade_out(self.console, callback=self.console.hide)

    def toggle_algo_vis_panel(self, visible: bool) -> None:
        if visible:
            self.algo_vis_panel.show()
            self.algo_vis_panel.raise_()
            fade_in(self.algo_vis_panel)
        else:
            fade_out(self.algo_vis_panel, callback=self.algo_vis_panel.hide)

    def toggle_ai_tools_panel(self, visible: bool) -> None:
        if visible:
            self.ai_tools_panel.show()
            self.ai_tools_panel.raise_()
            fade_in(self.ai_tools_panel)
        else:
            fade_out(self.ai_tools_panel, callback=self.ai_tools_panel.hide)

    def toggle_function_explorer(self, visible: bool) -> None:
        if visible:
            self.function_explorer.show()
            self.function_explorer.raise_()
            fade_in(self.function_explorer)
        else:
            fade_out(self.function_explorer, callback=self.function_explorer.hide)

    def toggle_math_console(self, visible: bool) -> None:
        if visible:
            self.math_console.show()
            self.math_console.raise_()
            fade_in(self.math_console)
        else:
            fade_out(self.math_console, callback=self.math_console.hide)

    def toggle_notebook_panel(self, visible: bool) -> None:
        if visible:
            self.notebook.show()
            self.notebook.raise_()
            fade_in(self.notebook)
        else:
            fade_out(self.notebook, callback=self.notebook.hide)

    # ─────────────────────────────────────────────────────────────────────
    # ECharts 图表串联棕函数
    # ─────────────────────────────────────────────────────────────────────
    def add_dynamic_panel(self, panel_name: str, widget, icon=None):
        """允许插件添加一个新的 UI 面板到主窗口侧边栏"""
        dock = QDockWidget(panel_name.upper(), self)
        dock.setObjectName(f"dock_dynamic_{panel_name}")
        dock.setWidget(widget)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)
        if hasattr(self, "ai_tools_panel"):
            self.tabifyDockWidget(self.ai_tools_panel, dock)
        dock.show()
        return dock
