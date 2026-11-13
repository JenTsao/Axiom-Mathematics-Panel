from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


class AlgebraItemWidget(QFrame):
    """代数视图中的单行条目"""

    value_changed_by_user = Signal(str, str)

    def __init__(self, entity_id, name, is_editable, initial_text, parent=None):
        super().__init__(parent)
        self.entity_id = entity_id

        self.setFixedHeight(36)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)

        self.lbl_name = QLabel(f"<b>{name}</b>")
        self.lbl_name.setObjectName("ggbAlgebraItemName")
        self.lbl_name.setFixedWidth(30)

        self.editor = QLineEdit(initial_text)
        self.editor.setObjectName("ggbAlgebraEditor")
        self.editor.setReadOnly(not is_editable)

        if is_editable:
            self.editor.returnPressed.connect(self._on_enter_pressed)

        layout.addWidget(self.lbl_name)
        layout.addWidget(self.editor)

    def _on_enter_pressed(self):
        self.editor.clearFocus()
        self.value_changed_by_user.emit(self.entity_id, self.editor.text())

    def update_text_silently(self, new_text):
        if self.editor.text() != new_text:
            self.editor.setText(new_text)


class GeoGebraAlgebraPanel(QWidget):
    """左侧代数总面板"""

    user_edit_requested = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.item_widgets = {}
        self.init_ui()

    def init_ui(self):
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        from mathlab.utils.i18n_manager import get_i18n

        t = get_i18n().t
        header = QLabel(t("geogebra.algebra_title") or "Algebra")
        header.setObjectName("ggbAlgebraHeader")

        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("ggbAlgebraScroll")
        self.scroll_area.setWidgetResizable(True)

        self.list_container = QWidget()
        self.list_container.setObjectName("ggbAlgebraList")
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(0)
        self.list_layout.addStretch()

        self.scroll_area.setWidget(self.list_container)

        self.layout.addWidget(header)
        self.layout.addWidget(self.scroll_area)

    def sync_from_engine(self, engine):
        for entity_id, entity in engine.entities.items():
            text = entity.get_algebra_string()

            if entity_id in self.item_widgets:
                self.item_widgets[entity_id].update_text_silently(text)
            else:
                is_editable = not entity.parents
                item_widget = AlgebraItemWidget(entity_id, entity.name, is_editable, text)

                item_widget.value_changed_by_user.connect(self.user_edit_requested.emit)

                self.item_widgets[entity_id] = item_widget
                self.list_layout.insertWidget(self.list_layout.count() - 1, item_widget)

    def retranslate_ui(self) -> None:
        """更新所有 UI 文本为当前语言"""
        from mathlab.utils.i18n_manager import get_i18n

        t = get_i18n().t
        header = self.layout.itemAt(0).widget()
        if header and isinstance(header, QLabel):
            header.setText(t("geogebra.algebra_title") or "Algebra")
