from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from mathlab.ui.geogebra_algebra_panel import GeoGebraAlgebraPanel
from mathlab.ui.geogebra_canvas import GeoGebraCanvas, ToolMode


class GeometryPanel(QWidget):
    """几何引擎的完整 UI 容器：顶部工具栏 + 底部(代数区/画板区)"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

    def init_ui(self):
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        # ── 1. 顶部工具栏 ──
        self.toolbar = QWidget()
        self.toolbar.setObjectName("geogebraToolbar")
        self.toolbar.setFixedHeight(45)
        tb_layout = QHBoxLayout(self.toolbar)
        tb_layout.setContentsMargins(10, 0, 10, 0)
        tb_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)

        self.btn_group = QButtonGroup(self)
        self.btn_group.setExclusive(True)

        from mathlab.utils.i18n_manager import get_i18n

        t = get_i18n().t

        tools = [
            (f"👆 {t('geogebra.tool_move') or 'Move'}", ToolMode.SELECT),
            (f"⏺ {t('geogebra.tool_point') or 'Point'}", ToolMode.POINT),
            (f"📏 {t('geogebra.tool_line') or 'Line'}", ToolMode.LINE),
            (f"❌ {t('geogebra.tool_intersect') or 'Intersect'}", ToolMode.INTERSECT),
        ]

        for text, mode in tools:
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda checked, m=mode: self.canvas.set_tool_mode(m))
            self.btn_group.addButton(btn)
            tb_layout.addWidget(btn)

        self.btn_group.buttons()[0].setChecked(True)
        self.layout.addWidget(self.toolbar)

        # ── 2. 核心分割视窗 (左代数，右几何) ──
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setObjectName("geogebraSplitter")

        self.algebra_view = GeoGebraAlgebraPanel(self)
        self.canvas = GeoGebraCanvas(self)

        self.splitter.addWidget(self.algebra_view)
        self.splitter.addWidget(self.canvas)

        self.splitter.setSizes([250, 750])

        self.layout.addWidget(self.splitter)

        # ── 3. ✨ 世纪握手：双向绑定核心逻辑 ✨ ──
        self.canvas.on_engine_updated = self._sync_algebra_view
        self.algebra_view.user_edit_requested.connect(self._handle_user_algebra_edit)

    def _sync_algebra_view(self):
        self.algebra_view.sync_from_engine(self.canvas.engine)

    def _handle_user_algebra_edit(self, entity_id: str, new_text: str):
        entity = self.canvas.engine.entities.get(entity_id)
        if entity and entity.update_from_string(new_text):
            entity.notify_update()
            self.canvas.sync_ui_from_engine()

    def retranslate_ui(self) -> None:
        """更新所有 UI 文本为当前语言"""
        from mathlab.utils.i18n_manager import get_i18n

        t = get_i18n().t
        tools = [
            (f"👆 {t('geogebra.tool_move') or 'Move'}", ToolMode.SELECT),
            (f"⏺ {t('geogebra.tool_point') or 'Point'}", ToolMode.POINT),
            (f"📏 {t('geogebra.tool_line') or 'Line'}", ToolMode.LINE),
            (f"❌ {t('geogebra.tool_intersect') or 'Intersect'}", ToolMode.INTERSECT),
        ]
        for btn, (text, _) in zip(self.btn_group.buttons(), tools):
            btn.setText(text)
        if hasattr(self, "algebra_view") and hasattr(self.algebra_view, "retranslate_ui"):
            self.algebra_view.retranslate_ui()
