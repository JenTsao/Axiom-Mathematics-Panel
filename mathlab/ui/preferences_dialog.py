"""
ui/preferences_dialog.py
------------------------
MathLab Preferences / Settings dialog.

Layout
~~~~~~
  Left  : QTabWidget (West / sidebar mode) — 6 tabs
  Right : QScrollArea + QFormLayout per page
  Bottom: [Cancel]  [Apply]  [OK]

样式（R-03 / §4）：本文件内联样式清零到 ≤3 处（仅动态强调色板保留，
标 ``ALLOWED-INLINE``），其余全部迁入 ``styles.qss`` §4 分区，
以 ``QDialog#preferencesDialog`` 命名空间前缀防泄漏。

Signals exported to main window
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
  theme_changed(str)                  — theme key e.g. "dark"
  accent_color_changed(str)           — hex colour string
  font_changed(str, int)              — family, pt-size
  language_changed(str)               — lang code e.g. "zh"
  graphics_settings_changed(dict)
  console_settings_changed(dict)
  shortcuts_changed(dict)
  advanced_settings_changed(dict)
  canvas_white_paper_changed(bool)    — D-2 白纸开关
  undo_enabled_changed(bool)          — D-3 撤销栈开关
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFontComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from mathlab.ui.session_state import get_white_paper, set_white_paper
from mathlab.utils.i18n_manager import SUPPORTED_LANGUAGES, get_i18n, t
from mathlab.utils.theme_manager import (
    THEMES,
    get_current_theme,
    save_settings,
    set_theme,
)

# 动态强调色板（用户可自选强调色 — §11 O-2 token 覆写层的数据源）
# 仅此列表允许硬编码 HEX（验收 A-03：preferences_dialog HEX ≤ 5）
_ACCENT_COLORS = [
    "#004ac6",
    "#10B981",
    "#8B5CF6",
    "#F59E0B",
    "#EF4444",
]


class PreferencesDialog(QDialog):
    theme_changed = Signal(str)
    accent_color_changed = Signal(str)
    font_changed = Signal(str, int)
    language_changed = Signal(str)
    graphics_settings_changed = Signal(dict)
    console_settings_changed = Signal(dict)
    shortcuts_changed = Signal(dict)
    advanced_settings_changed = Signal(dict)
    canvas_white_paper_changed = Signal(bool)
    undo_enabled_changed = Signal(bool)

    def __init__(self, parent=None, initial_settings: dict | None = None):
        super().__init__(parent)
        # 命名空间（§4.2）：styles.qss §4 全部以 QDialog#preferencesDialog 前缀生效
        self.setObjectName("preferencesDialog")
        self.setWindowTitle(t("preferences.title"))
        self.setMinimumSize(700, 500)
        self.resize(800, 560)

        self.settings: dict = initial_settings or self._default_settings()

        self._build_ui()
        self._load_settings()
        self._connect_change_signals()

        get_i18n().add_language_change_listener(self._on_lang_changed_extern)

    @staticmethod
    def _default_settings() -> dict:
        return {
            "theme": get_current_theme(),
            "accent": "",
            "ui_font": "Segoe UI",
            "ui_font_size": 10,
            "canvas_bg": "grid",
            "line_width": 1.5,
            "point_size": 4,
            "aa_enabled": True,
            "anim_speed": 50,
            "console_font": "Consolas",
            "console_font_size": 11,
            "console_history": 1000,
            "autocomplete": True,
            "hw_accel": False,
            "autosave_interval": 5,
            "enable_undo": True,
            "shortcuts": {
                "New Project": "Ctrl+N",
                "Save": "Ctrl+S",
                "Undo": "Ctrl+Z",
                "Redo": "Ctrl+Shift+Z",
                "Clear Canvas": "Ctrl+Del",
                "Select Mode": "Esc",
                "Execute Code": "Shift+Enter",
            },
        }

    def _connect_change_signals(self):
        for widget in self.findChildren(QComboBox) + self.findChildren(QFontComboBox):
            widget.currentIndexChanged.connect(self._on_setting_changed)
        for widget in self.findChildren(QSpinBox) + self.findChildren(QDoubleSpinBox):
            widget.valueChanged.connect(self._on_setting_changed)
        for widget in self.findChildren(QCheckBox):
            widget.toggled.connect(self._on_setting_changed)
        for widget in self.findChildren(QSlider):
            widget.valueChanged.connect(self._on_setting_changed)
        self.shortcut_table.itemChanged.connect(self._on_setting_changed)
        if hasattr(self, "accent_btns"):
            for _, btn in self.accent_btns:
                btn.clicked.connect(self._on_setting_changed)

    def _on_setting_changed(self, *args, **kwargs):
        self.btn_apply.setEnabled(True)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QWidget()
        header.setObjectName("prefHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(24, 12, 24, 12)
        header_layout.setSpacing(12)

        title_label = QLabel(t("preferences.title"))
        title_label.setObjectName("prefTitle")
        header_layout.addWidget(title_label)
        header_layout.addStretch()

        close_btn = QPushButton()
        close_btn.setObjectName("prefCloseBtn")
        close_btn.setText("✕")
        close_btn.setFixedSize(32, 32)
        close_btn.clicked.connect(self.reject)
        header_layout.addWidget(close_btn)

        root.addWidget(header)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        self.tabs = QTabWidget()
        self.tabs.setTabPosition(QTabWidget.West)

        self.tabs.addTab(self._page_appearance(), t("preferences.appearance"))
        self.tabs.addTab(self._page_graphics(), t("preferences.graphics"))
        self.tabs.addTab(self._page_console(), t("preferences.console_tab"))
        self.tabs.addTab(self._page_shortcuts(), t("preferences.shortcuts"))
        self.tabs.addTab(self._page_ai_lab(), t("preferences.ai_lab"))
        self.tabs.addTab(self._page_advanced(), t("preferences.advanced"))

        body_layout.addWidget(self.tabs, 1)
        root.addWidget(body, 1)

        bar = QWidget()
        bar.setObjectName("prefFooter")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(24, 16, 24, 16)
        bar_layout.setSpacing(8)

        self.btn_cancel = QPushButton(t("dialogs.cancel"))
        self.btn_cancel.setObjectName("prefSecondaryBtn")

        self.btn_apply = QPushButton(t("preferences.apply"))
        self.btn_apply.setObjectName("prefSecondaryBtn")
        self.btn_apply.setEnabled(False)

        self.btn_ok = QPushButton(t("preferences.ok"))
        self.btn_ok.setObjectName("prefPrimaryBtn")
        self.btn_ok.setDefault(True)

        bar_layout.addStretch()
        bar_layout.addWidget(self.btn_cancel)
        bar_layout.addWidget(self.btn_apply)
        bar_layout.addWidget(self.btn_ok)

        self.btn_cancel.clicked.connect(self.reject)
        self.btn_apply.clicked.connect(self._apply_settings)
        self.btn_ok.clicked.connect(self._on_ok)

        root.addWidget(bar)

    @staticmethod
    def _scroll(inner: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName("prefPage")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(inner)
        return scroll

    def _create_section_header(self, title: str) -> QLabel:
        header = QLabel(title)
        header.setObjectName("prefSectionTitle")
        return header

    def _create_section_card(self) -> tuple[QWidget, QVBoxLayout]:
        """构建 §4 prefCard 区块（样式统一走 QSS）。"""
        section = QWidget()
        section.setObjectName("prefCard")
        section_layout = QVBoxLayout(section)
        section_layout.setSpacing(16)
        return section, section_layout

    @staticmethod
    def _form_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("prefFormLabel")
        return label

    def _page_appearance(self) -> QScrollArea:
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(24)

        section, section_layout = self._create_section_card()
        section_layout.addWidget(self._create_section_header(t("preferences.appearance")))

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(16)
        form.setLabelAlignment(Qt.AlignLeft)

        self.theme_combo = QComboBox()
        for key, data in THEMES.items():
            self.theme_combo.addItem(data["name"], key)
        form.addRow(self._form_label(t("preferences.theme")), self.theme_combo)

        accent_row = QHBoxLayout()
        accent_row.setSpacing(8)
        self.accent_btns: list[tuple[str, QPushButton]] = []
        for color in _ACCENT_COLORS:
            btn = QPushButton()
            btn.setFixedSize(26, 26)
            btn.setCheckable(True)
            # ALLOWED-INLINE: dynamic accent swatch（运行时才知道颜色，§4.2）
            btn.setStyleSheet(f"background-color:{color}; border-radius:13px; border:2px solid transparent;")
            btn.setToolTip(
                t(
                    "preferences.accent_tooltip",
                    "Click Apply or OK to save the accent color.",
                )
            )
            btn.clicked.connect(lambda _checked, c=color: self._set_accent(c))
            accent_row.addWidget(btn)
            self.accent_btns.append((color, btn))
        accent_row.addStretch()
        form.addRow(self._form_label(t("preferences.accent_color")), accent_row)

        font_row = QHBoxLayout()
        self.ui_font_combo = QFontComboBox()
        self.ui_font_size_spin = QSpinBox()
        self.ui_font_size_spin.setRange(8, 24)
        self.ui_font_size_spin.setSuffix(" pt")
        font_row.addWidget(self.ui_font_combo, 1)
        font_row.addWidget(self.ui_font_size_spin)
        form.addRow(self._form_label(t("preferences.interface_font")), font_row)

        self.bg_combo = QComboBox()
        self.bg_combo.addItem(t("preferences.canvas_bg_grid"), "grid")
        self.bg_combo.addItem(t("preferences.canvas_bg_blank"), "blank")
        self.bg_combo.addItem(t("preferences.canvas_bg_polar"), "polar")
        form.addRow(self._form_label(t("preferences.canvas_background")), self.bg_combo)

        # D-2 白纸开关：跟随主题 + 可强制白纸
        self.white_paper_check = QCheckBox(t("preferences.canvas_white_paper"))
        form.addRow(self._form_label(t("preferences.canvas_background")), self.white_paper_check)

        self.lang_combo = QComboBox()
        for code, display in SUPPORTED_LANGUAGES.items():
            self.lang_combo.addItem(display, code)
        self.lang_combo.currentIndexChanged.connect(self._on_lang_combo_changed)
        form.addRow(self._form_label(t("preferences.language")), self.lang_combo)

        section_layout.addLayout(form)
        layout.addWidget(section)

        return self._scroll(inner)

    def _page_graphics(self) -> QScrollArea:
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(24)

        section, section_layout = self._create_section_card()
        section_layout.addWidget(self._create_section_header(t("preferences.graphics")))

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(16)

        self.line_width_spin = QDoubleSpinBox()
        self.line_width_spin.setRange(0.1, 10.0)
        self.line_width_spin.setSingleStep(0.1)
        self.line_width_spin.setSuffix(" px")
        form.addRow(self._form_label(t("preferences.default_line_width")), self.line_width_spin)

        self.point_size_spin = QSpinBox()
        self.point_size_spin.setRange(1, 20)
        self.point_size_spin.setSuffix(" px")
        form.addRow(self._form_label(t("preferences.default_point_size")), self.point_size_spin)

        self.aa_check = QCheckBox(t("preferences.antialiasing"))
        form.addRow(self._form_label(t("preferences.rendering")), self.aa_check)

        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel(t("preferences.slow")))
        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setRange(10, 200)
        speed_row.addWidget(self.speed_slider, 1)
        speed_row.addWidget(QLabel(t("preferences.fast")))
        form.addRow(self._form_label(t("preferences.animation_speed")), speed_row)

        self.snap_combo = QComboBox()
        self.snap_combo.addItem(t("preferences.snap_grid"), "grid")
        self.snap_combo.addItem(t("preferences.snap_points"), "points")
        self.snap_combo.addItem(t("preferences.snap_off"), "off")
        form.addRow(self._form_label(t("preferences.snapping")), self.snap_combo)

        section_layout.addLayout(form)
        layout.addWidget(section)

        return self._scroll(inner)

    def _page_console(self) -> QScrollArea:
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(24)

        section, section_layout = self._create_section_card()
        section_layout.addWidget(self._create_section_header(t("preferences.console_tab")))

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(16)

        font_row = QHBoxLayout()
        self.con_font_combo = QFontComboBox()
        self.con_font_size_spin = QSpinBox()
        self.con_font_size_spin.setRange(8, 30)
        self.con_font_size_spin.setSuffix(" pt")
        font_row.addWidget(self.con_font_combo, 1)
        font_row.addWidget(self.con_font_size_spin)
        form.addRow(self._form_label(t("preferences.console_font")), font_row)

        self.color_scheme_combo = QComboBox()
        self.color_scheme_combo.addItem(t("preferences.scheme_dark"), "dark")
        self.color_scheme_combo.addItem(t("preferences.scheme_light"), "light")
        self.color_scheme_combo.addItem(t("preferences.scheme_system"), "system")
        form.addRow(self._form_label(t("preferences.color_scheme")), self.color_scheme_combo)

        self.history_spin = QSpinBox()
        self.history_spin.setRange(100, 10000)
        self.history_spin.setSingleStep(100)
        form.addRow(self._form_label(t("preferences.history_limit")), self.history_spin)

        self.autocomplete_check = QCheckBox(t("preferences.autocomplete"))
        form.addRow(self._form_label(t("preferences.intellisense")), self.autocomplete_check)

        section_layout.addLayout(form)
        layout.addWidget(section)

        return self._scroll(inner)

    def _page_shortcuts(self) -> QScrollArea:
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(16)

        layout.addWidget(self._create_section_header(t("preferences.shortcuts")))

        self.shortcut_table = QTableWidget(0, 2)
        self.shortcut_table.setObjectName("prefShortcutTable")
        self.shortcut_table.setHorizontalHeaderLabels([t("preferences.action"), t("preferences.shortcut")])
        self.shortcut_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.shortcut_table.setAlternatingRowColors(True)
        self.shortcut_table.setEditTriggers(QTableWidget.DoubleClicked)
        layout.addWidget(self.shortcut_table)

        self.btn_restore = QPushButton(t("preferences.restore_defaults"))
        self.btn_restore.setObjectName("prefSecondaryBtn")
        self.btn_restore.clicked.connect(self._restore_shortcuts)
        layout.addWidget(self.btn_restore, alignment=Qt.AlignRight)

        return self._scroll(inner)

    def _page_advanced(self) -> QScrollArea:
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(16)

        layout.addWidget(self._create_section_header(t("preferences.advanced")))

        self.hw_accel_check = QCheckBox(t("preferences.hardware_acceleration"))
        layout.addWidget(self.hw_accel_check)

        # D-3：撤销栈启用开关（关闭时 Ctrl+Z 灰置，UndoStack 零开销）
        self.enable_undo_check = QCheckBox(t("preferences.enable_undo"))
        layout.addWidget(self.enable_undo_check)

        autosave_row = QHBoxLayout()
        self.lbl_autosave_pre = QLabel(t("preferences.autosave_interval"))
        self.autosave_spin = QSpinBox()
        self.autosave_spin.setRange(0, 60)
        self.lbl_autosave_post = QLabel(t("preferences.autosave_minutes"))
        autosave_row.addWidget(self.lbl_autosave_pre)
        autosave_row.addWidget(self.autosave_spin)
        autosave_row.addWidget(self.lbl_autosave_post)
        autosave_row.addStretch()
        layout.addLayout(autosave_row)

        self.lbl_restart = QLabel(t("preferences.restart_notice"))
        layout.addWidget(self.lbl_restart)

        layout.addStretch()

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        layout.addWidget(separator)

        reset_row = QHBoxLayout()
        reset_label = QLabel(t("preferences.factory_reset"))
        reset_label.setObjectName("prefDangerLabel")

        self.btn_reset_all = QPushButton(t("preferences.reset_all"))
        self.btn_reset_all.setObjectName("prefDangerBtn")
        self.btn_reset_all.clicked.connect(self._reset_all)

        reset_row.addWidget(reset_label)
        reset_row.addStretch()
        reset_row.addWidget(self.btn_reset_all)
        layout.addLayout(reset_row)

        hint_label = QLabel(t("preferences.reset_hint"))
        hint_label.setObjectName("prefHintLabel")
        layout.addWidget(hint_label)

        return self._scroll(inner)

    def _page_ai_lab(self) -> QScrollArea:
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(32, 32, 32, 32)
        layout.setSpacing(24)

        section, section_layout = self._create_section_card()
        section_layout.addWidget(self._create_section_header(t("preferences.ai_lab")))

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(16)

        self.ai_provider_combo = QComboBox()
        provider_data = [
            ("deepseek", t("preferences.ai_provider_deepseek") or "DeepSeek"),
            ("openai", t("preferences.ai_provider_openai") or "OpenAI"),
            ("siliconflow", t("preferences.ai_provider_siliconflow") or "硅基流动 (SiliconFlow)"),
            ("ollama", t("preferences.ai_provider_ollama") or "Ollama (本地)"),
            ("custom", t("preferences.ai_provider_custom") or "自定义"),
        ]
        for data, text in provider_data:
            self.ai_provider_combo.addItem(text, data)
        self.ai_provider_combo.currentIndexChanged.connect(self._on_ai_provider_changed)

        self.ai_base_url_input = QLineEdit()
        self.ai_base_url_input.setPlaceholderText(
            t("preferences.ai_base_url_placeholder") or "例如: https://api.deepseek.com/v1"
        )

        self.ai_api_key_input = QLineEdit()
        self.ai_api_key_input.setPlaceholderText("sk-...")
        self.ai_api_key_input.setEchoMode(QLineEdit.EchoMode.Password)

        self.ai_model_input = QLineEdit()
        self.ai_model_input.setPlaceholderText(t("preferences.ai_model_placeholder") or "例如: deepseek-chat")

        form.addRow(t("preferences.ai_provider_label") or "服务提供商:", self.ai_provider_combo)
        form.addRow("Base URL:", self.ai_base_url_input)
        form.addRow("API Key:", self.ai_api_key_input)
        form.addRow(t("preferences.ai_model_label") or "默认模型:", self.ai_model_input)

        section_layout.addLayout(form)

        tip_label = QLabel(
            t("preferences.ai_lab_tip")
            or "💡 提示: 数据请求将直接从您的本地网络发送至服务商，MathLab 不会收集您的 API Key。"
        )
        tip_label.setObjectName("prefHintLabel")
        section_layout.addWidget(tip_label)

        layout.addWidget(section)
        layout.addStretch()

        return self._scroll(inner)

    def _on_ai_provider_changed(self, index):
        provider_key = self.ai_provider_combo.itemData(index)
        templates = {
            "deepseek": {
                "url": "https://api.deepseek.com/v1",
                "model": "deepseek-chat",
            },
            "siliconflow": {
                "url": "https://api.siliconflow.cn/v1",
                "model": "deepseek-ai/DeepSeek-V3",
            },
            "ollama": {"url": "http://localhost:11434/v1", "model": "llama3"},
            "openai": {"url": "https://api.openai.com/v1", "model": "gpt-4o"},
        }
        if provider_key in templates:
            self.ai_base_url_input.setText(templates[provider_key]["url"])
            self.ai_model_input.setText(templates[provider_key]["model"])
            if provider_key == "ollama":
                self.ai_api_key_input.setText("ollama")

    def _load_settings(self):
        s = self.settings

        idx = self.theme_combo.findData(s.get("theme", "light"))
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)

        self._set_accent(s.get("accent", ""))

        try:
            self.ui_font_combo.setCurrentFont(QFont(s.get("ui_font", "Segoe UI")))
        except Exception:
            pass
        self.ui_font_size_spin.setValue(s.get("ui_font_size", 10))

        idx = self.bg_combo.findData(s.get("canvas_bg", "grid"))
        if idx >= 0:
            self.bg_combo.setCurrentIndex(idx)

        # D-2：白纸开关状态存 QSettings（§5.1 边界）
        self.white_paper_check.setChecked(get_white_paper())

        lang_code = get_i18n().get_language()
        idx = self.lang_combo.findData(lang_code)
        if idx >= 0:
            self.lang_combo.blockSignals(True)
            self.lang_combo.setCurrentIndex(idx)
            self.lang_combo.blockSignals(False)

        self.line_width_spin.setValue(s.get("line_width", 1.5))
        self.point_size_spin.setValue(s.get("point_size", 4))
        self.aa_check.setChecked(s.get("aa_enabled", True))
        self.speed_slider.setValue(s.get("anim_speed", 50))

        try:
            self.con_font_combo.setCurrentFont(QFont(s.get("console_font", "Consolas")))
        except Exception:
            pass
        self.con_font_size_spin.setValue(s.get("console_font_size", 11))
        self.history_spin.setValue(s.get("console_history", 1000))
        self.autocomplete_check.setChecked(s.get("autocomplete", True))

        self.hw_accel_check.setChecked(s.get("hw_accel", False))
        self.enable_undo_check.setChecked(s.get("enable_undo", True))
        self.autosave_spin.setValue(s.get("autosave_interval", 5))

        self.ai_base_url_input.setText(s.get("ai_base_url", "https://api.deepseek.com/v1"))
        self.ai_api_key_input.setText(s.get("ai_api_key", ""))
        self.ai_model_input.setText(s.get("ai_model", "deepseek-chat"))

        shortcuts = s.get("shortcuts", {})
        self.shortcut_table.blockSignals(True)
        self.shortcut_table.setRowCount(len(shortcuts))
        for row, (action, key) in enumerate(shortcuts.items()):
            self.shortcut_table.setItem(row, 0, QTableWidgetItem(action))
            self.shortcut_table.setItem(row, 1, QTableWidgetItem(key))
        self.shortcut_table.blockSignals(False)

    def _set_accent(self, hex_color: str):
        """选中强调色板按钮（O-2：token 覆写层，色值由 theme_manager 渲染时覆写）。"""
        self.settings["accent"] = hex_color
        for color, btn in self.accent_btns:
            selected = color == hex_color
            btn.setChecked(selected)
            # ALLOWED-INLINE: dynamic accent swatch（选中描边随选中项变化）
            border = "#1e293b" if selected else "transparent"
            btn.setStyleSheet(f"background-color:{color}; border-radius:13px; border:2px solid {border};")

    def _on_lang_combo_changed(self, index: int):
        lang_code = self.lang_combo.itemData(index)
        if not lang_code:
            return
        if self.isVisible() and lang_code != get_i18n().get_language():
            get_i18n().set_language(lang_code)
            self.language_changed.emit(lang_code)

    def _on_lang_changed_extern(self, lang_code: str):
        self.retranslate_ui()
        idx = self.lang_combo.findData(lang_code)
        if idx >= 0 and self.lang_combo.currentIndex() != idx:
            self.lang_combo.blockSignals(True)
            self.lang_combo.setCurrentIndex(idx)
            self.lang_combo.blockSignals(False)

    def retranslate_ui(self):
        self.setWindowTitle(t("preferences.title"))

        self.tabs.setTabText(0, t("preferences.appearance"))
        self.tabs.setTabText(1, t("preferences.graphics"))
        self.tabs.setTabText(2, t("preferences.console_tab"))
        self.tabs.setTabText(3, t("preferences.shortcuts"))
        self.tabs.setTabText(4, t("preferences.ai_lab"))
        self.tabs.setTabText(5, t("preferences.advanced"))

        self.btn_cancel.setText(t("dialogs.cancel"))
        self.btn_apply.setText(t("preferences.apply"))
        self.btn_ok.setText(t("preferences.ok"))

    def _apply_settings(self):
        # O-2：强调色覆写层 — 先持久化，set_theme 渲染时覆写 accent token
        accent = self.settings.get("accent", "")
        save_settings({"accent": accent})
        self.accent_color_changed.emit(accent)

        theme_key = self.theme_combo.currentData()
        if theme_key:
            set_theme(theme_key)
            self.settings["theme"] = theme_key
            self.theme_changed.emit(theme_key)

        family = self.ui_font_combo.currentFont().family()
        size = self.ui_font_size_spin.value()
        self.settings.update({"ui_font": family, "ui_font_size": size})
        self.font_changed.emit(family, size)

        # 语言已在 _on_lang_combo_changed 中处理，此处不再重复发射
        lang_code = self.lang_combo.currentData()
        if lang_code:
            self.settings["language"] = lang_code

        canvas_bg = self.bg_combo.currentData()
        if canvas_bg:
            self.settings["canvas_bg"] = canvas_bg

        # D-2：白纸开关 → QSettings + 信号驱动画布即时刷新
        white_paper = self.white_paper_check.isChecked()
        set_white_paper(white_paper)
        self.canvas_white_paper_changed.emit(white_paper)

        gfx = {
            "line_width": self.line_width_spin.value(),
            "point_size": self.point_size_spin.value(),
            "aa": self.aa_check.isChecked(),
            "speed": self.speed_slider.value(),
            "snap": self.snap_combo.currentData(),
        }
        self.settings.update(
            {
                "line_width": gfx["line_width"],
                "point_size": gfx["point_size"],
                "aa_enabled": gfx["aa"],
                "anim_speed": gfx["speed"],
            }
        )
        self.graphics_settings_changed.emit(gfx)

        con = {
            "font": self.con_font_combo.currentFont().family(),
            "font_size": self.con_font_size_spin.value(),
            "history": self.history_spin.value(),
            "autocomplete": self.autocomplete_check.isChecked(),
            "color_scheme": self.color_scheme_combo.currentData(),
        }
        self.settings.update(
            {
                "console_font": con["font"],
                "console_font_size": con["font_size"],
                "console_history": con["history"],
                "autocomplete": con["autocomplete"],
            }
        )
        self.console_settings_changed.emit(con)

        enable_undo = self.enable_undo_check.isChecked()
        adv = {
            "hw_accel": self.hw_accel_check.isChecked(),
            "autosave": self.autosave_spin.value(),
            "enable_undo": enable_undo,
        }
        self.settings.update(
            {
                "hw_accel": adv["hw_accel"],
                "autosave_interval": adv["autosave"],
                "enable_undo": adv["enable_undo"],
            }
        )
        save_settings({"enable_undo": enable_undo})
        self.undo_enabled_changed.emit(enable_undo)
        self.advanced_settings_changed.emit(adv)

        shortcuts = {}
        for row in range(self.shortcut_table.rowCount()):
            action_item = self.shortcut_table.item(row, 0)
            key_item = self.shortcut_table.item(row, 1)
            if action_item and key_item:
                shortcuts[action_item.text()] = key_item.text()
        self.settings["shortcuts"] = shortcuts
        self.shortcuts_changed.emit(shortcuts)

        # [BUG修复] AI 实验室设置保存（从 _build_ui 中移出到这里）
        if hasattr(self, "ai_base_url_input"):
            self.settings["ai_base_url"] = self.ai_base_url_input.text()
            self.settings["ai_api_key"] = self.ai_api_key_input.text()
            self.settings["ai_model"] = self.ai_model_input.text()

            import json
            import os

            settings_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "settings.json",
            )
            try:
                with open(settings_path, "w", encoding="utf-8") as f:
                    json.dump(self.settings, f, ensure_ascii=False, indent=4)
            except Exception:
                pass

            if hasattr(self.parent(), "ai_manager"):
                self.parent().ai_manager.reload_config()

        self.btn_apply.setEnabled(False)

    def _on_ok(self):
        self._apply_settings()
        self.accept()

    def _restore_shortcuts(self):
        defaults = self._default_settings()["shortcuts"]
        self.settings["shortcuts"] = defaults
        self.shortcut_table.setRowCount(len(defaults))
        for row, (action, key) in enumerate(defaults.items()):
            self.shortcut_table.setItem(row, 0, QTableWidgetItem(action))
            self.shortcut_table.setItem(row, 1, QTableWidgetItem(key))

    def _reset_all(self):
        result = QMessageBox.question(
            self,
            t("preferences.title"),
            t("preferences.reset_confirm"),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if result == QMessageBox.Yes:
            self.settings = self._default_settings()
            self._load_settings()

    def closeEvent(self, event):
        get_i18n().remove_language_change_listener(self._on_lang_changed_extern)
        super().closeEvent(event)
