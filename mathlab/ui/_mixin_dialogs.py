"""对话框、主题与国际化 Mixin。

将 MainWindow 中与主题切换、语言切换、偏好设置对话框、
以及 UI 国际化重绘相关的方法提取到此模块。
"""

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

try:
    from .preferences_dialog import PreferencesDialog
except ImportError:
    PreferencesDialog = None

from mathlab.ui.session_state import reset_session  # noqa: E402
from mathlab.utils.i18n_manager import SUPPORTED_LANGUAGES, get_i18n, t
from mathlab.utils.theme_manager import THEMES, get_current_theme, set_theme


class DialogsMixin:
    """MainWindow Mixin：对话框、主题与国际化。"""

    def apply_theme(self, theme_key: str) -> None:
        """全局应用指定主题（唯一外部入口 — UI_SYSTEM_DESIGN.md §1.5）。

        样式注入由 theme_manager.set_theme() 完成；此处仅负责
        主题敏感组件（工具栏图标等）的联动刷新。
        """
        if theme_key not in THEMES:
            return
        set_theme(theme_key)
        self.update_toolbar_icons(theme_key)

    def _toggle_theme(self) -> None:
        current = get_current_theme()
        new_theme = "light" if current == "dark" else "dark"
        self.apply_theme(new_theme)

    def reset_default_layout(self) -> None:
        """「视图 → 恢复默认布局」入口（A-05）。"""
        reset_session(self)

    def show_about(self) -> None:
        QMessageBox.about(self, t("dialogs.about_title"), t("dialogs.about_text"))

    def show_preferences_dialog(self) -> None:
        if PreferencesDialog is None:
            self.show_theme_dialog()
            return
        dlg = PreferencesDialog(self)

        def on_theme_changed(name_or_key):
            if name_or_key in THEMES:
                theme_key = name_or_key
            else:
                theme_key = next((k for k, v in THEMES.items() if v["name"] == name_or_key), "light")
            self.apply_theme(theme_key)

        dlg.theme_changed.connect(on_theme_changed)

        def log_pref(name, val):
            if hasattr(self, "console"):
                self.console.display_system_message(f"偏好设置已更新: {name} (功能预留)", level="info")

        dlg.accent_color_changed.connect(lambda c: log_pref("强调色", c))
        dlg.font_changed.connect(lambda f, s: log_pref("字体", f"{f} {s}px"))
        dlg.graphics_settings_changed.connect(lambda gfx: log_pref("图形设置", str(gfx)))
        dlg.console_settings_changed.connect(lambda con: log_pref("控制台设置", str(con)))
        dlg.advanced_settings_changed.connect(lambda adv: log_pref("高级设置", str(adv)))

        # D-2 白纸开关 / D-3 撤销栈开关：即时生效
        dlg.canvas_white_paper_changed.connect(self.on_canvas_white_paper_changed)
        dlg.undo_enabled_changed.connect(self.on_undo_enabled_changed)
        dlg.exec()

    def show_theme_dialog(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(t("dialogs.select_theme"))
        dialog.setModal(True)
        dialog.setMinimumWidth(300)

        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(t("dialogs.choose_theme")))

        combo = QComboBox()
        current_theme = get_current_theme()
        for theme_id, theme_data in THEMES.items():
            combo.addItem(theme_data["name"], theme_id)
            if theme_id == current_theme:
                combo.setCurrentIndex(combo.count() - 1)
        layout.addWidget(combo)

        btn_layout = QHBoxLayout()
        ok_btn = QPushButton(t("dialogs.apply"))
        cancel_btn = QPushButton(t("dialogs.cancel"))
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        def on_apply():
            self.apply_theme(combo.currentData())
            dialog.accept()

        ok_btn.clicked.connect(on_apply)
        cancel_btn.clicked.connect(dialog.reject)
        dialog.exec()

    def show_language_dialog(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(t("dialogs.language"))
        dialog.setModal(True)
        dialog.setMinimumWidth(300)

        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(t("dialogs.choose_language")))

        combo = QComboBox()
        current_lang = get_i18n().get_language()
        for lang_code, lang_name in SUPPORTED_LANGUAGES.items():
            combo.addItem(lang_name, lang_code)
            if lang_code == current_lang:
                combo.setCurrentIndex(combo.count() - 1)
        layout.addWidget(combo)

        btn_layout = QHBoxLayout()
        ok_btn = QPushButton(t("dialogs.apply"))
        cancel_btn = QPushButton(t("dialogs.cancel"))
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        def on_apply():
            get_i18n().set_language(combo.currentData())
            dialog.accept()

        ok_btn.clicked.connect(on_apply)
        cancel_btn.clicked.connect(dialog.reject)
        dialog.exec()

    def _toggle_language(self) -> None:
        current = get_i18n().get_language()
        target = "zh" if current == "en" else "en"
        get_i18n().set_language(target)

    def _on_language_changed(self, lang_code: str) -> None:
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        self.setWindowTitle(t("main_window.title"))

        if hasattr(self, "central_tabs"):
            # R-08：Tab 序已调整为 画板 → Notebook → Mini GeoGebra → Jupyter，
            # 用 widget 反查 index，避免硬编码页序（R-23：4 个中央 Tab 全部刷新）
            self.central_tabs.setTabText(
                self.central_tabs.indexOf(self.central_widget), t("main_window.geometry_tools") or "Geometry Canvas"
            )
            self.central_tabs.setTabText(
                self.central_tabs.indexOf(self.notebook), t("notebook.title") or "Interactive Notebook"
            )

        if hasattr(self, "notebook") and hasattr(self.notebook, "retranslate_ui"):
            self.notebook.retranslate_ui()

        if hasattr(self, "properties_panel") and hasattr(self.properties_panel, "retranslate_ui"):
            self.properties_panel.retranslate_ui()

        self.file_menu.setTitle(t("menu.file"))
        self.edit_menu.setTitle(t("menu.edit"))
        self.view_menu.setTitle(t("menu.view"))
        self.tools_menu.setTitle(t("menu.tools"))
        self.help_menu.setTitle(t("menu.help"))

        self.new_action.setText(t("main_window.new_project"))
        self.open_action.setText(t("main_window.open_project"))
        self.save_action.setText(t("main_window.save_project"))
        self.save_as_action.setText(t("main_window.save_as"))
        self.export_png_action.setText(t("main_window.export_png"))
        self.export_svg_action.setText(t("main_window.export_svg"))
        self.export_latex_action.setText(t("main_window.export_latex"))
        self.exit_action.setText(t("main_window.exit"))

        self.undo_action.setText(t("main_window.undo"))
        self.redo_action.setText(t("main_window.redo"))
        self.delete_action.setText(t("main_window.delete"))

        self.algebra_panel_action.setText(t("main_window.algebra_panel"))
        self.properties_panel_action.setText(t("main_window.properties_panel"))
        self.console_action.setText(t("main_window.console"))
        self.algo_vis_action.setText(t("main_window.algorithm_visualization"))
        self.ai_tools_action.setText(t("main_window.ai_tools"))
        self.theme_action.setText(t("main_window.theme"))
        self.language_action.setText(t("main_window.language"))

        self.geometry_tool_action.setText(t("main_window.geometry_tools"))
        self.algebra_tool_action.setText(t("main_window.algebra_tools"))
        self.ai_tool_action.setText(t("main_window.ai_tools"))

        self.about_action.setText(t("main_window.about"))

        self.reset_layout_action.setText(t("view.reset_layout"))

        self.select_action.setText(t("main_window.select"))
        self.point_action.setText(t("main_window.point"))
        self.segment_action.setText(t("main_window.segment"))
        self.circle_action.setText(t("main_window.circle"))
        self.polygon_action.setText(t("main_window.polygon"))
        self.pan_action.setText(t("main_window.pan"))

        self.preferences_action.setText(t("main_window.preferences"))
        self.ai_menu.setTitle(t("menu.ai"))
        self.ai_scatter_action.setText(t("ai_tools.scatter_fitting"))
        self.ai_cluster_action.setText(t("ai_tools.clustering"))
        self.ai_digit_action.setText(t("ai_tools.digit_recognition"))
        self.ai_train_action.setText(t("ai_tools.training_notebook"))

        self.lang_btn.setToolTip(t("main_window.language"))
        self.settings_btn.setToolTip(t("main_window.preferences"))

        # R-14/UI-10：Dock 标题不再 .upper()
        self.algebra_panel.setWindowTitle(t("algebra_panel.title"))
        self.properties_panel.setWindowTitle(t("properties_panel.title"))
        self.console.setWindowTitle(t("console.title"))
        self.math_console.setWindowTitle(t("math_console.title"))
        self.algo_vis_panel.setWindowTitle(t("algo_vis.title"))
        self.ai_tools_panel.setWindowTitle(t("ai_tools.title"))
        # [I18n 修复] 补充遗漏的函数探索器标题刷新
        self.function_explorer.setWindowTitle(t("function_explorer.title"))

        self.algebra_panel.retranslate_ui()
        self.properties_panel.retranslate_ui()
        self.console.retranslate_ui()
        self.math_console.retranslate_ui()
        self.algo_vis_panel.retranslate_ui()
        self.ai_tools_panel.retranslate_ui()
        # [I18n 修复] 级联调用函数探索器的重绘
        self.function_explorer.retranslate_ui()
        # [I18n 修复] 级联调用 GeoGebra 面板的重绘
        if hasattr(self, "geogebra_panel") and self.geogebra_panel is not None:
            self.geogebra_panel.retranslate_ui()
