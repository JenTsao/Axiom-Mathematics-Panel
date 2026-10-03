"""菜单栏、工具栏构建与图标管理 Mixin。

将 MainWindow 中与菜单栏、工具栏、工具按钮和图标主题
相关的方法提取到此模块。
"""

import os

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QMenu,
    QMenuBar,
    QPushButton,
    QToolBar,
)

from mathlab.utils.i18n_manager import t
from mathlab.utils.theme_manager import THEMES, get_current_theme

from .command_bar import CommandBar
from .fractal_gpu_panel import FractalGPUExplorer
from .signal_lab_panel import SignalLabPanel


class MenusMixin:
    """MainWindow Mixin：菜单栏、工具栏与图标管理。"""

    def setup_menus(self):
        menu_bar = QMenuBar(self)

        self.file_menu = QMenu(t("menu.file"), self)

        self.new_action = QAction(t("main_window.new_project"), self)
        self.open_action = QAction(t("main_window.open_project"), self)
        self.save_action = QAction(t("main_window.save_project"), self)
        self.save_as_action = QAction(t("main_window.save_as"), self)
        self.export_png_action = QAction(t("main_window.export_png"), self)
        self.export_svg_action = QAction(t("main_window.export_svg"), self)
        self.export_latex_action = QAction(t("main_window.export_latex"), self)
        self.exit_action = QAction(t("main_window.exit"), self)

        self.new_action.setShortcut("Ctrl+N")
        self.open_action.setShortcut("Ctrl+O")
        self.save_action.setShortcut("Ctrl+S")
        self.save_as_action.setShortcut("Ctrl+Shift+S")

        self.file_menu.addAction(self.new_action)
        self.file_menu.addAction(self.open_action)
        self.file_menu.addAction(self.save_action)
        self.file_menu.addAction(self.save_as_action)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.export_png_action)
        self.file_menu.addAction(self.export_svg_action)
        self.file_menu.addAction(self.export_latex_action)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.exit_action)

        self.edit_menu = QMenu(t("menu.edit"), self)

        self.undo_action = QAction(t("main_window.undo"), self)
        self.redo_action = QAction(t("main_window.redo"), self)
        self.delete_action = QAction(t("main_window.delete"), self)

        self.undo_action.setShortcut("Ctrl+Z")
        self.redo_action.setShortcut("Ctrl+Y")
        self.delete_action.setShortcut("Delete")

        self.edit_menu.addAction(self.undo_action)
        self.edit_menu.addAction(self.redo_action)
        self.edit_menu.addSeparator()
        self.edit_menu.addAction(self.delete_action)

        self.view_menu = QMenu(t("menu.view"), self)

        self.algebra_panel_action = QAction(t("main_window.algebra_panel"), self)
        self.algebra_panel_action.setCheckable(True)
        self.algebra_panel_action.setChecked(True)

        self.properties_panel_action = QAction(t("main_window.properties_panel"), self)
        self.properties_panel_action.setCheckable(True)
        self.properties_panel_action.setChecked(True)

        self.console_action = QAction(t("main_window.console"), self)
        self.console_action.setCheckable(True)
        self.console_action.setChecked(True)

        self.algo_vis_action = QAction(t("main_window.algorithm_visualization"), self)
        self.algo_vis_action.setCheckable(True)

        self.ai_tools_action = QAction(t("main_window.ai_tools"), self)
        self.ai_tools_action.setCheckable(True)

        self.notebook_action = QAction(t("main_window.notebook"), self)
        self.notebook_action.setCheckable(True)

        self.function_explorer_action = QAction(t("function_explorer.title"), self)
        self.function_explorer_action.setCheckable(True)

        self.math_console_action = QAction(t("math_console.title"), self)
        self.math_console_action.setCheckable(True)
        self.math_console_action.setChecked(True)
        self.math_console_action.setShortcut("Ctrl+Shift+M")

        self.reset_layout_action = QAction(t("view.reset_layout"), self)
        self.reset_layout_action.setObjectName("reset_layout_action")

        self.theme_action = QAction(t("main_window.theme"), self)
        self.language_action = QAction(t("main_window.language"), self)

        self.view_menu.addAction(self.algebra_panel_action)
        self.view_menu.addAction(self.properties_panel_action)
        self.view_menu.addAction(self.console_action)
        self.view_menu.addAction(self.math_console_action)
        self.view_menu.addAction(self.algo_vis_action)
        self.view_menu.addAction(self.ai_tools_action)
        self.view_menu.addAction(self.notebook_action)
        self.view_menu.addAction(self.function_explorer_action)
        self.view_menu.addSeparator()
        self.view_menu.addAction(self.reset_layout_action)
        self.view_menu.addAction(self.theme_action)
        self.view_menu.addAction(self.language_action)
        self.preferences_action = QAction(t("main_window.preferences"), self)
        self.preferences_action.setShortcut("Ctrl+,")
        self.view_menu.addAction(self.preferences_action)

        self.ai_menu = QMenu(t("menu.ai"), self)
        self.ai_scatter_action = QAction(t("ai_tools.scatter_fitting"), self)
        self.ai_cluster_action = QAction(t("ai_tools.clustering"), self)
        self.ai_digit_action = QAction(t("ai_tools.digit_recognition"), self)
        self.ai_train_action = QAction(t("ai_tools.training_notebook"), self)
        self.ai_menu.addAction(self.ai_scatter_action)
        self.ai_menu.addAction(self.ai_cluster_action)
        self.ai_menu.addAction(self.ai_digit_action)
        self.ai_menu.addSeparator()
        self.ai_menu.addAction(self.ai_train_action)

        self.tools_menu = QMenu(t("menu.tools"), self)

        self.geometry_tool_action = QAction(t("main_window.geometry_tools"), self)
        self.algebra_tool_action = QAction(t("main_window.algebra_tools"), self)
        self.ai_tool_action = QAction(t("main_window.ai_tools"), self)
        # R-26：语义色治理 — 菜单名去掉装饰性 emoji，接 i18n
        self.signal_lab_action = QAction(t("tools.signal_lab"), self)
        self.fractal_gpu_action = QAction(t("tools.fractal_explorer"), self)

        self.tools_menu.addAction(self.geometry_tool_action)
        self.tools_menu.addAction(self.algebra_tool_action)
        self.tools_menu.addAction(self.ai_tool_action)
        self.tools_menu.addAction(self.signal_lab_action)
        self.tools_menu.addAction(self.fractal_gpu_action)

        self.help_menu = QMenu(t("menu.help"), self)

        self.about_action = QAction(t("main_window.about"), self)

        self.help_menu.addAction(self.about_action)

        menu_bar.addMenu(self.file_menu)
        menu_bar.addMenu(self.edit_menu)
        menu_bar.addMenu(self.view_menu)
        menu_bar.addMenu(self.tools_menu)
        menu_bar.addMenu(self.ai_menu)
        menu_bar.addMenu(self.help_menu)

        self.setMenuBar(menu_bar)

        self.new_action.triggered.connect(self.on_new_project)
        self.open_action.triggered.connect(self.on_open_project)
        self.save_action.triggered.connect(self.on_save_project)
        self.save_as_action.triggered.connect(self.on_save_project_as)
        self.export_png_action.triggered.connect(self.on_export_png)
        self.export_svg_action.triggered.connect(self.on_export_svg)
        self.export_latex_action.triggered.connect(self.on_export_latex)
        self.exit_action.triggered.connect(self.close)

        self.delete_action.triggered.connect(self.on_delete_selected)

        # ── 撤销/重做接 UndoStack（R-10，§6.4）────────────────────────────
        undo_stack = getattr(self, "undo_stack", None)
        if undo_stack is not None and undo_stack.enabled:
            self.undo_action.triggered.connect(undo_stack.undo)
            self.redo_action.triggered.connect(undo_stack.redo)
            # 可用性信号驱动灰置（保留用户可发现性，而非隐藏）
            undo_stack.undo_available.connect(self.undo_action.setEnabled)
            undo_stack.redo_available.connect(self.redo_action.setEnabled)
            self.undo_action.setEnabled(False)
            self.redo_action.setEnabled(False)
        else:
            # D-3：偏好关闭 enable_undo 时灰置
            self.undo_action.setEnabled(False)
            self.redo_action.setEnabled(False)

        self.algebra_panel_action.triggered.connect(self.toggle_algebra_panel)
        self.properties_panel_action.triggered.connect(self.toggle_properties_panel)
        self.console_action.triggered.connect(self.toggle_console)
        self.algo_vis_action.triggered.connect(self.toggle_algo_vis_panel)
        self.notebook_action.triggered.connect(self.toggle_notebook_panel)
        self.ai_tools_action.triggered.connect(self.toggle_ai_tools_panel)
        self.function_explorer_action.triggered.connect(self.toggle_function_explorer)
        self.math_console_action.triggered.connect(self.toggle_math_console)

        self.geometry_tool_action.triggered.connect(self._show_command_palette)
        self.algebra_tool_action.triggered.connect(lambda: self.toggle_algebra_panel(True))
        self.ai_tool_action.triggered.connect(lambda: self.toggle_ai_tools_panel(True))
        self.signal_lab_action.triggered.connect(self.open_signal_lab)
        self.fractal_gpu_action.triggered.connect(self.open_gpu_fractal_explorer)

        self.theme_action.triggered.connect(self.show_theme_dialog)
        self.language_action.triggered.connect(self.show_language_dialog)
        self.preferences_action.triggered.connect(self.show_preferences_dialog)
        self.reset_layout_action.triggered.connect(self.reset_default_layout)

        self.ai_scatter_action.triggered.connect(lambda: self.toggle_ai_tools_panel(True))
        self.ai_cluster_action.triggered.connect(lambda: self.toggle_ai_tools_panel(True))
        self.ai_digit_action.triggered.connect(lambda: self.toggle_ai_tools_panel(True))
        self.ai_train_action.triggered.connect(lambda: self.toggle_ai_tools_panel(True))

        self.about_action.triggered.connect(self.show_about)

    def open_signal_lab(self):
        self.signal_lab = SignalLabPanel(self)
        self.signal_lab.show()

    def open_gpu_fractal_explorer(self):
        self.gpu_fractal_explorer = FractalGPUExplorer(self)
        self.gpu_fractal_explorer.show()

    def setup_toolbar(self):
        self.toolbar = QToolBar("Main Toolbar")
        self.toolbar.setObjectName("mainToolbar")  # restoreState 依赖 objectName
        self.toolbar.setIconSize(QSize(20, 20))
        self.toolbar.setToolButtonStyle(Qt.ToolButtonIconOnly)

        # 6 个工具 action 补 tooltip + accessibleName（R-28 无障碍基线）
        self.select_action = QAction(t("main_window.select"), self)
        self.select_action.setCheckable(True)
        self.select_action.setChecked(True)
        self.select_action.setToolTip(t("main_window.select"))

        self.point_action = QAction(t("main_window.point"), self)
        self.point_action.setCheckable(True)
        self.point_action.setToolTip(t("main_window.point"))

        self.segment_action = QAction(t("main_window.segment"), self)
        self.segment_action.setCheckable(True)
        self.segment_action.setToolTip(t("main_window.segment"))

        self.circle_action = QAction(t("main_window.circle"), self)
        self.circle_action.setCheckable(True)
        self.circle_action.setToolTip(t("main_window.circle"))

        self.polygon_action = QAction(t("main_window.polygon"), self)
        self.polygon_action.setCheckable(True)
        self.polygon_action.setToolTip(t("main_window.polygon"))

        self.pan_action = QAction(t("main_window.pan"), self)
        self.pan_action.setCheckable(True)
        self.pan_action.setToolTip(t("main_window.pan"))

        self.tool_actions = [
            self.select_action,
            self.point_action,
            self.segment_action,
            self.circle_action,
            self.polygon_action,
            self.pan_action,
        ]

        self.toolbar.addAction(self.select_action)
        self.toolbar.addAction(self.point_action)
        self.toolbar.addAction(self.segment_action)
        self.toolbar.addAction(self.circle_action)
        self.toolbar.addAction(self.polygon_action)
        self.toolbar.addAction(self.pan_action)
        self.toolbar.addSeparator()

        self.command_bar = CommandBar()
        self.toolbar.addWidget(self.command_bar)

        self.toolbar.addSeparator()

        self._zoom_in_action = QAction(t("main_window.zoom_in"), self)
        self.toolbar.addAction(self._zoom_in_action)
        self._zoom_in_action.triggered.connect(self.on_zoom_in)

        self._zoom_out_action = QAction(t("main_window.zoom_out"), self)
        self.toolbar.addAction(self._zoom_out_action)
        self._zoom_out_action.triggered.connect(self.on_zoom_out)

        self.toolbar.addSeparator()

        self.lang_btn = QPushButton("EN/ZH")
        self.lang_btn.setToolTip(t("main_window.language"))
        self.lang_btn.setObjectName("lang_btn")
        self.lang_btn.setFixedSize(64, 28)
        # 样式由 styles.qss #lang_btn 规则提供（R-20：深色下无浅色贴片）
        self.lang_btn.clicked.connect(self._toggle_language)
        self.toolbar.addWidget(self.lang_btn)

        self.settings_btn = QPushButton()
        self.settings_btn.setObjectName("settings_btn")
        self.settings_btn.setToolTip(t("main_window.preferences"))
        self.settings_btn.setAccessibleName(t("main_window.preferences"))
        self.settings_btn.setFixedSize(28, 28)
        self.settings_btn.setIconSize(QSize(18, 18))
        self.settings_btn.clicked.connect(self.show_preferences_dialog)
        self.toolbar.addWidget(self.settings_btn)

        self.addToolBar(Qt.TopToolBarArea, self.toolbar)

        self._connect_tool_actions()
        self.update_toolbar_icons()

    def _connect_tool_actions(self):
        tool_map = [
            ("select", self.select_action),
            ("point", self.point_action),
            ("segment", self.segment_action),
            ("circle", self.circle_action),
            ("polygon", self.polygon_action),
            ("pan", self.pan_action),
        ]
        for tool_name, action in tool_map:
            action.triggered.connect(lambda checked, tn=tool_name: self.on_action_selected(tn))

    def on_action_selected(self, tool_name: str) -> None:
        for action in self.tool_actions:
            action.setChecked(False)

        action_map = {
            "select": self.select_action,
            "point": self.point_action,
            "segment": self.segment_action,
            "circle": self.circle_action,
            "polygon": self.polygon_action,
            "pan": self.pan_action,
        }
        if tool_name in action_map:
            action_map[tool_name].setChecked(True)

        self.central_widget.set_tool(tool_name)

    def on_zoom_in(self) -> None:
        self.central_widget.zoom_in()

    def on_zoom_out(self) -> None:
        self.central_widget.zoom_out()

    def get_themed_icon(self, name: str, theme_name: str = None) -> QIcon:
        """获取带有当前主题前景色渲染的 SVG 图标。"""
        if theme_name is None:
            theme_name = get_current_theme()

        icon_path = os.path.join(os.path.dirname(__file__), "icons", f"{name}.svg")
        if not os.path.exists(icon_path):
            return QIcon()

        try:
            with open(icon_path, "r", encoding="utf-8") as f:
                svg_content = f.read()

            foreground = THEMES.get(theme_name, {}).get("foreground", "#434655")
            svg_content = svg_content.replace("currentColor", foreground)

            from PySide6.QtGui import QPixmap

            pixmap = QPixmap()
            pixmap.loadFromData(svg_content.encode("utf-8"), "SVG")
            return QIcon(pixmap)
        except Exception as e:
            print(f"Warning: Could not load themed icon {name}: {e}")
            return QIcon(icon_path)

    def update_toolbar_icons(self, theme_name: str = None) -> None:
        """刷新工具栏上所有按钮的图标颜色。"""
        if theme_name is None:
            theme_name = get_current_theme()

        self.select_action.setIcon(self.get_themed_icon("mouse-pointer", theme_name))
        self.point_action.setIcon(self.get_themed_icon("target", theme_name))
        self.segment_action.setIcon(self.get_themed_icon("segment", theme_name))
        self.circle_action.setIcon(self.get_themed_icon("circle", theme_name))
        self.polygon_action.setIcon(self.get_themed_icon("polygon", theme_name))
        self.pan_action.setIcon(self.get_themed_icon("move", theme_name))

        self._zoom_in_action.setIcon(self.get_themed_icon("zoom-in", theme_name))
        self._zoom_out_action.setIcon(self.get_themed_icon("zoom-out", theme_name))

        self.settings_btn.setIcon(self.get_themed_icon("settings", theme_name))
