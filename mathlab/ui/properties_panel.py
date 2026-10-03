"""
Properties Panel — redesigned with three collapsible sections:
  • Appearance (color swatches, opacity slider, stroke slider)
  • Label       (show-label checkbox, Name/Value toggle)
  • Definition  (read-only formula display)
"""

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from mathlab.utils.i18n_manager import t
from mathlab.utils.theme_tokens import get_tokens

# ──────────────────────────────────────────────────────────────────────────────
# Helper: collapsible section header widget
# ──────────────────────────────────────────────────────────────────────────────


class _SectionHeader(QLabel):
    """Clickable section header that can toggle a body widget."""

    toggled = Signal(bool)

    def __init__(self, text: str, parent=None):
        super().__init__("", parent)
        self.setObjectName("section_label")
        self._collapsed = False
        self._body: QWidget | None = None
        self._base_text = text
        self._arrow = "▾"
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_style()

    def setText(self, text: str):
        self._base_text = text
        super().setText(f"{self._arrow} {text}")

    def _apply_style(self):
        # 样式由 styles.qss `QLabel#section_label` 提供（R-27：内联清零）
        self._arrow = "▸" if self._collapsed else "▾"
        super().setText(f"{self._arrow} {self._base_text}")

    def set_body(self, body: QWidget):
        self._body = body

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._collapsed = not self._collapsed
            self._apply_style()
            if self._body:
                self._body.setVisible(not self._collapsed)
            self.toggled.emit(not self._collapsed)
        super().mousePressEvent(event)


# ──────────────────────────────────────────────────────────────────────────────
# Helper: circular color-dot button
# ──────────────────────────────────────────────────────────────────────────────


class _ColorDot(QPushButton):
    """20×20 filled circle button with an outer ring when selected."""

    def __init__(self, hex_color: str, parent=None):
        super().__init__(parent)
        self.hex_color = hex_color
        self._selected = False
        self.setFixedSize(QSize(24, 24))
        self.setCheckable(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(hex_color)
        self._refresh_style()

    def _refresh_style(self):
        # ALLOWED-INLINE: dynamic user color swatch（色值即业务数据，运行时才知道）
        if self._selected:
            self.setStyleSheet(
                f"QPushButton {{"
                f"  background-color: {self.hex_color};"
                f"  border-radius: 12px;"
                f"  border: 2.5px solid {get_tokens()['fg.primary']};"
                f"}}"
                # outer ring via box-shadow is not supported in Qt;
                # we paint it manually in paintEvent instead
            )
        else:
            self.setStyleSheet(
                f"QPushButton {{"
                f"  background-color: {self.hex_color};"
                f"  border-radius: 12px;"
                f"  border: 2px solid transparent;"
                f"}}"
            )

    def set_selected(self, selected: bool):
        self._selected = selected
        self._refresh_style()
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._selected:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(QColor(self.hex_color))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            # draw outer ring with 1px margin outside the button rect
            painter.drawEllipse(1, 1, self.width() - 2, self.height() - 2)
            painter.end()


# ──────────────────────────────────────────────────────────────────────────────
# Helper: horizontal divider
# ──────────────────────────────────────────────────────────────────────────────


def _make_divider() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Sunken)
    # 样式由 styles.qss QFrame[frameShape] 规则提供（R-27）
    return line


# ──────────────────────────────────────────────────────────────────────────────
# Main panel
# ──────────────────────────────────────────────────────────────────────────────


class PropertiesPanel(QDockWidget):
    # ── existing signals ──────────────────────────────────────────────
    property_changed = Signal(str, str, object)
    object_renamed = Signal(str, str)

    # ── new signals ───────────────────────────────────────────────────
    color_changed = Signal(str, str)  # (obj_id, color_hex)
    opacity_changed = Signal(str, int)  # (obj_id, 0-100)
    stroke_changed = Signal(str, float)  # (obj_id, 1.0-10.0)
    label_toggled = Signal(str, bool)  # (obj_id, show_label)

    @staticmethod
    def _default_colors() -> list[str]:
        """色板取自当前主题 token（R-27：禁止裸 HEX 字面量）。"""
        tokens = get_tokens()
        return [tokens["accent.base"], tokens["obj.segment"], tokens["obj.circle"], tokens["danger"]]

    def __init__(self, parent=None):
        super().__init__(t("properties_panel.title"), parent)
        self.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea)
        self.setMinimumWidth(220)
        self.setObjectName("dockPropertiesInner")

        self._current_obj_id: str | None = None
        self._block_signals = False
        self.COLORS = self._default_colors()

        # ── outer scroll area ─────────────────────────────────────────
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        container.setObjectName("properties_container")
        root_layout = QVBoxLayout(container)
        root_layout.setContentsMargins(12, 8, 12, 8)
        root_layout.setSpacing(0)

        # ── title label ("PROPERTIES: …") ────────────────────────────
        self._title_label = QLabel(t("properties_panel.title").upper())
        self._title_label.setObjectName("section_label")
        root_layout.addWidget(self._title_label)
        root_layout.addWidget(_make_divider())

        # ── APPEARANCE section ────────────────────────────────────────
        self._app_header = _SectionHeader(t("properties_panel.appearance").upper())
        root_layout.addWidget(self._app_header)

        self._app_body = self._build_appearance_section()
        root_layout.addWidget(self._app_body)
        self._app_header.set_body(self._app_body)

        root_layout.addWidget(_make_divider())

        # ── LABEL section ─────────────────────────────────────────────
        self._lbl_header = _SectionHeader(t("properties_panel.label_section").upper())
        root_layout.addWidget(self._lbl_header)

        self._lbl_body = self._build_label_section()
        root_layout.addWidget(self._lbl_body)
        self._lbl_header.set_body(self._lbl_body)

        root_layout.addWidget(_make_divider())

        # ── DEFINITION section ────────────────────────────────────────
        self._def_header = _SectionHeader(t("properties_panel.definition").upper())
        root_layout.addWidget(self._def_header)

        self._def_body = self._build_definition_section()
        root_layout.addWidget(self._def_body)
        self._def_header.set_body(self._def_body)

        root_layout.addStretch()

        self._scroll_area.setWidget(container)
        self.setWidget(self._scroll_area)

        # start with no object loaded
        self.clear()

    def retranslate_ui(self):
        self._app_header.setText(t("properties_panel.appearance").upper())
        self._lbl_header.setText(t("properties_panel.label_section").upper())
        self._def_header.setText(t("properties_panel.definition").upper())
        self._color_label.setText(t("properties_panel.color"))
        self._opacity_label.setText(t("properties_panel.opacity"))
        self._thickness_label.setText(t("properties_panel.thickness"))
        self._show_lbl_cb.setText(t("properties_panel.show_label"))

    # ──────────────────────────────────────────────────────────────────
    # Section builders
    # ──────────────────────────────────────────────────────────────────

    def _build_appearance_section(self) -> QWidget:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 4, 0, 8)
        layout.setSpacing(10)

        # ── Color row ─────────────────────────────────────────────────
        color_row = QHBoxLayout()
        color_row.setSpacing(6)
        self._color_label = QLabel(t("properties_panel.color"))
        self._color_label.setFixedWidth(64)
        color_row.addWidget(self._color_label)

        self._color_dots: list[_ColorDot] = []
        for hex_col in self.COLORS:
            dot = _ColorDot(hex_col)
            dot.clicked.connect(lambda checked=False, c=hex_col: self._on_color_clicked(c))
            self._color_dots.append(dot)
            color_row.addWidget(dot)
        color_row.addStretch()
        layout.addLayout(color_row)

        # ── Opacity row ───────────────────────────────────────────────
        opacity_row = QHBoxLayout()
        opacity_row.setSpacing(8)
        self._opacity_label = QLabel(t("properties_panel.opacity"))
        self._opacity_label.setFixedWidth(64)
        opacity_row.addWidget(self._opacity_label)

        self._opacity_value_label = QLabel("100%")
        self._opacity_value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(0, 100)
        self._opacity_slider.setValue(100)
        # 滑块样式由 styles.qss `QDockWidget QSlider` 规则提供（R-27）
        self._opacity_slider.valueChanged.connect(self._on_opacity_changed)

        opacity_row.addWidget(self._opacity_slider)
        opacity_row.addWidget(self._opacity_value_label)
        layout.addLayout(opacity_row)

        # ── Stroke row ────────────────────────────────────────────────
        stroke_row = QHBoxLayout()
        stroke_row.setSpacing(8)
        self._stroke_label = QLabel(t("properties_panel.stroke"))
        self._stroke_label.setFixedWidth(64)
        stroke_row.addWidget(self._stroke_label)

        self._stroke_value_label = QLabel("2px")
        self._stroke_value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self._stroke_slider = QSlider(Qt.Orientation.Horizontal)
        self._stroke_slider.setRange(1, 10)
        self._stroke_slider.setValue(2)
        self._stroke_slider.valueChanged.connect(self._on_stroke_changed)

        stroke_row.addWidget(self._stroke_slider)
        stroke_row.addWidget(self._stroke_value_label)
        layout.addLayout(stroke_row)

        return body

    def _build_label_section(self) -> QWidget:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 4, 0, 8)
        layout.setSpacing(8)

        # ── Show Label checkbox ───────────────────────────────────────
        self._show_label_cb = QCheckBox(t("properties_panel.show_label"))
        self._show_label_cb.setChecked(True)
        self._show_label_cb.toggled.connect(self._on_label_toggled)
        layout.addWidget(self._show_label_cb)

        # ── Name / Value toggle buttons ───────────────────────────────
        toggle_row = QHBoxLayout()
        toggle_row.setSpacing(0)

        self._name_btn = QPushButton(t("properties_panel.name_tab"))
        self._value_btn = QPushButton(t("properties_panel.value_tab"))

        for btn in (self._name_btn, self._value_btn):
            btn.setCheckable(True)
            btn.setFixedHeight(30)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._name_btn.setChecked(True)
        self._name_btn.setObjectName("tab_btn_left")
        self._value_btn.setObjectName("tab_btn_right")
        self._apply_tab_styles()

        self._name_btn.clicked.connect(lambda: self._set_label_mode("name"))
        self._value_btn.clicked.connect(lambda: self._set_label_mode("value"))

        toggle_row.addWidget(self._name_btn)
        toggle_row.addWidget(self._value_btn)
        layout.addLayout(toggle_row)

        self._label_mode = "name"
        return body

    def _build_definition_section(self) -> QWidget:
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 4, 0, 8)

        self._definition_edit = QTextEdit()
        self._definition_edit.setReadOnly(True)
        self._definition_edit.setFixedHeight(70)
        # 样式由 styles.qss QTextEdit / QLineEdit[readOnly] 规则提供（R-27）
        layout.addWidget(self._definition_edit)
        return body

    # ──────────────────────────────────────────────────────────────────
    # Style helpers
    # ──────────────────────────────────────────────────────────────────

    def _apply_tab_styles(self):
        """名称/值切换按钮的选中态样式（色值全部取自 token — R-27）。"""
        tokens = get_tokens()
        active_style = (
            "QPushButton {"
            f"  background: {tokens['accent.base']}; color: {tokens['fg.onAccent']};"
            "  font-size: 12px; font-weight: 600;"
            f"  border: 1px solid {tokens['accent.base']};"
            "  padding: 0 8px;"
            "}"
        )
        inactive_style = (
            "QPushButton {"
            f"  background: {tokens['bg.surface']}; color: {tokens['fg.secondary']};"
            "  font-size: 12px;"
            f"  border: 1px solid {tokens['border.subtle']};"
            "  padding: 0 8px;"
            "}"
            "QPushButton:hover {"
            f"  background: {tokens['bg.hover']};"
            "}"
        )
        left_radius = "border-top-left-radius: 6px; border-bottom-left-radius: 6px;"
        right_radius = "border-top-right-radius: 6px; border-bottom-right-radius: 6px;"

        name_active = self._name_btn.isChecked()
        value_active = self._value_btn.isChecked()

        self._name_btn.setStyleSheet(
            (active_style if name_active else inactive_style) + f"QPushButton {{ {left_radius} }}"
        )
        self._value_btn.setStyleSheet(
            (active_style if value_active else inactive_style) + f"QPushButton {{ {right_radius} }}"
        )

    # ──────────────────────────────────────────────────────────────────
    # Internal slot helpers
    # ──────────────────────────────────────────────────────────────────

    def _on_color_clicked(self, hex_color: str):
        for dot in self._color_dots:
            dot.set_selected(dot.hex_color == hex_color)
        if self._current_obj_id and not self._block_signals:
            self.color_changed.emit(self._current_obj_id, hex_color)

    def _on_opacity_changed(self, value: int):
        self._opacity_value_label.setText(f"{value}%")
        if self._current_obj_id and not self._block_signals:
            self.opacity_changed.emit(self._current_obj_id, value)

    def _on_stroke_changed(self, value: int):
        self._stroke_value_label.setText(f"{value}px")
        if self._current_obj_id and not self._block_signals:
            self.stroke_changed.emit(self._current_obj_id, float(value))

    def _on_label_toggled(self, checked: bool):
        self._name_btn.setEnabled(checked)
        self._value_btn.setEnabled(checked)
        if self._current_obj_id and not self._block_signals:
            self.label_toggled.emit(self._current_obj_id, checked)

    def _set_label_mode(self, mode: str):
        self._label_mode = mode
        self._name_btn.setChecked(mode == "name")
        self._value_btn.setChecked(mode == "value")
        self._apply_tab_styles()

    # ──────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────

    def set_object(self, obj_data: dict) -> None:
        """Populate the panel with the given object's data."""
        self._block_signals = True
        self._current_obj_id = obj_data.get("id")

        obj_type = obj_data.get("type", "")
        obj_name = obj_data.get("name", "")

        # window title
        label = f"{t('properties_panel.title').upper()}: {obj_type.upper()} {obj_name}"
        self.setWindowTitle(label)
        self._title_label.setText(label)

        # ── appearance ────────────────────────────────────────────────
        saved_color = obj_data.get("color", self.COLORS[0])
        saved_opacity = int(obj_data.get("opacity", 100))
        saved_stroke = int(obj_data.get("stroke", 2))

        for dot in self._color_dots:
            dot.set_selected(dot.hex_color == saved_color)

        self._opacity_slider.setValue(saved_opacity)
        self._opacity_value_label.setText(f"{saved_opacity}%")

        self._stroke_slider.setValue(saved_stroke)
        self._stroke_value_label.setText(f"{saved_stroke}px")

        # ── label ─────────────────────────────────────────────────────
        show_label = bool(obj_data.get("show_label", True))
        self._show_label_cb.setChecked(show_label)
        label_mode = obj_data.get("label_mode", "name")
        self._set_label_mode(label_mode)

        # 确保按钮状态与 show_label 同步
        self._name_btn.setEnabled(show_label)
        self._value_btn.setEnabled(show_label)

        # ── definition ────────────────────────────────────────────────
        definition = self._format_definition(obj_data)
        self._definition_edit.setPlainText(definition)

        self._block_signals = False

    def clear(self) -> None:
        """Reset all controls and remove the current object reference."""
        self._block_signals = True
        self._current_obj_id = None

        title = t("properties_panel.title").upper()
        self.setWindowTitle(title)
        self._title_label.setText(title)

        for dot in self._color_dots:
            dot.set_selected(False)
        self._opacity_slider.setValue(100)
        self._opacity_value_label.setText("100%")
        self._stroke_slider.setValue(2)
        self._stroke_value_label.setText("2px")

        self._show_label_cb.setChecked(True)
        self._set_label_mode("name")
        self._definition_edit.clear()

        self._block_signals = False

    def retranslate_ui(self) -> None:
        """Re-apply all translated strings (called on language switch)."""
        self.setWindowTitle(t("properties_panel.title"))
        self._app_header.setText(t("properties_panel.appearance").upper())
        self._lbl_header.setText(t("properties_panel.label_section").upper())
        self._def_header.setText(t("properties_panel.definition").upper())

        self._color_label.setText(t("properties_panel.color"))
        self._opacity_label.setText(t("properties_panel.opacity"))
        self._stroke_label.setText(t("properties_panel.stroke"))

        self._show_label_cb.setText(t("properties_panel.show_label"))
        self._name_btn.setText(t("properties_panel.name_tab"))
        self._value_btn.setText(t("properties_panel.value_tab"))

    # ──────────────────────────────────────────────────────────────────
    # Definition formatter
    # ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _format_definition(obj_data: dict) -> str:
        obj_type = obj_data.get("type", "")
        coords = obj_data.get("coordinates", {})
        name = obj_data.get("name", "?")

        if obj_type == "Point":
            x = coords.get("x", 0.0)
            y = coords.get("y", 0.0)
            return f"{name} = ({x:.2f}, {y:.2f})"

        elif obj_type == "Circle":
            cx = coords.get("cx", 0.0)
            cy = coords.get("cy", 0.0)
            r = coords.get("r", 1.0)
            # use Unicode superscript 2
            cx_str = f"{abs(cx):.2f}"
            cy_str = f"{abs(cy):.2f}"
            x_eq_sign = "-" if cx >= 0 else "+"
            y_eq_sign = "-" if cy >= 0 else "+"
            return f"(x {x_eq_sign} {cx_str})\u00b2 + " f"(y {y_eq_sign} {cy_str})\u00b2 = {r:.2f}\u00b2"

        elif obj_type == "Segment":
            x1 = coords.get("x1", 0.0)
            y1 = coords.get("y1", 0.0)
            x2 = coords.get("x2", 0.0)
            y2 = coords.get("y2", 0.0)
            return f"({x1:.2f}, {y1:.2f}) \u2192 ({x2:.2f}, {y2:.2f})"

        elif obj_type == "Polygon":
            points = obj_data.get("points", [])
            n = len(points)
            return f"{n} vertices"

        else:
            return str(coords)
