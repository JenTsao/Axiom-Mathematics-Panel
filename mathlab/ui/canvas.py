from PySide6.QtCore import (
    QEasingCurve,
    QLineF,
    QPointF,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QWheelEvent,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtSvgWidgets import QGraphicsSvgItem
from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsPolygonItem,
    QGraphicsScene,
    QGraphicsSceneMouseEvent,
    QGraphicsTextItem,
    QGraphicsView,
    QMenu,
)

from mathlab.core.geometry_helpers import MagnetSnapper
from mathlab.core.smart_guides import SmartGuideManager

# 实例化吸附引擎 (全局复用)
snapper = MagnetSnapper(snap_threshold_pixels=10)

# 导入 LaTeX 渲染缓存
try:
    from mathlab.utils.latex_renderer import (
        SharedSvgRendererCache,
        is_latex_rendering_available,
    )
except ImportError:
    SharedSvgRendererCache = None
    is_latex_rendering_available = lambda: False

# ── 网格画笔缓存 ─────────────────────────────────────────────────────────────
# drawBackground 在滚动/缩放/拖动时高频触发，进程级复用画笔避免重复构造 QPen/QColor
_GRID_PEN = None
_ORIGIN_PEN = None


def _get_grid_pen() -> QPen:
    global _GRID_PEN
    if _GRID_PEN is None:
        _GRID_PEN = QPen(QColor("#d3e4fe"), 0.5)
        _GRID_PEN.setStyle(Qt.DashLine)
    return _GRID_PEN


def _get_origin_pen() -> QPen:
    global _ORIGIN_PEN
    if _ORIGIN_PEN is None:
        _ORIGIN_PEN = QPen(QColor("#737686"), 1)
    return _ORIGIN_PEN


class MathGraphicsItem(QGraphicsSvgItem):
    """
    支持 LaTeX 公式渲染的图形项

    采用混合渲染策略：
    - 静态时：使用 SVG 渲染高质量的 LaTeX 公式
    - 拖拽时：降级为普通文本，保证 60 FPS 流畅度

    特性：
    - LRU 缓存：相同公式只渲染一次
    - 共享渲染器：多个实例共享同一个 QSvgRenderer
    - 设备坐标缓存：防止拖动时重新光栅化
    """

    def __init__(self, text: str, parent=None, use_latex: bool = True):
        """
        Args:
            text: 显示文本，可以是普通文本或 LaTeX 公式
            parent: 父图形项
            use_latex: 是否启用 LaTeX 渲染（默认启用）
        """
        super().__init__(parent)
        self._text = text
        self._use_latex = use_latex and is_latex_rendering_available()
        self._fallback_item = None  # 降级渲染的文本项
        self._is_dragging = False

        # 开启图形缓存，防止拖动画布时重新光栅化
        self.setCacheMode(QGraphicsItem.DeviceCoordinateCache)

        self._update_rendering()

    def _update_rendering(self):
        """更新渲染内容"""
        if self._use_latex and not self._is_dragging:
            # 尝试使用 LaTeX SVG 渲染
            renderer = SharedSvgRendererCache.get_renderer(self._text)
            if renderer is not None:
                self.setSharedRenderer(renderer)
                self.setVisible(True)
                # 隐藏降级文本
                if self._fallback_item:
                    self._fallback_item.setVisible(False)
                return

        # 降级：使用普通文本渲染
        self._create_fallback_text()

    def _create_fallback_text(self):
        """创建降级文本项"""
        if self._fallback_item is None:
            self._fallback_item = QGraphicsTextItem(self)
            self._fallback_item.setFont(QFont("Arial", 12, QFont.Bold))
            self._fallback_item.setDefaultTextColor(QColor("#0b1c30"))

        self._fallback_item.setPlainText(self._text)
        self._fallback_item.setVisible(True)
        # 隐藏 SVG 项
        self.setVisible(False)

    def set_text(self, new_text: str):
        """更新显示文本"""
        if self._text != new_text:
            self._text = new_text
            self._update_rendering()

    def set_dragging(self, is_dragging: bool):
        """
        设置拖拽状态

        拖拽时降级为普通文本以保证帧率，
        松开后恢复 LaTeX 渲染。
        """
        if self._is_dragging != is_dragging:
            self._is_dragging = is_dragging
            if is_dragging:
                # 拖拽中：立即切换到降级渲染
                self._create_fallback_text()
            else:
                # 拖拽结束：恢复 LaTeX 渲染
                self._update_rendering()

    def text(self) -> str:
        """返回当前文本"""
        return self._text

    def boundingRect(self) -> QRectF:
        """返回边界矩形"""
        if self._fallback_item and self._fallback_item.isVisible():
            return self._fallback_item.boundingRect()
        return super().boundingRect()


class GeometryPointItem(QGraphicsEllipseItem):
    """
    带磁吸特性的控制点
    """

    def __init__(self, x, y, w, h, obj_id, canvas, *args, **kwargs):
        super().__init__(x, y, w, h, *args, **kwargs)
        self.obj_id = obj_id
        self.canvas = canvas
        # 必须开启 ItemSendsGeometryChanges 标志位，否则捕获不到坐标改变
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)

        # 内部状态标志位
        self._is_dragging = False

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        super().mousePressEvent(event)
        self._is_dragging = True

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent):
        # 让父类优先处理拖拽，它会触发 itemChange 更新 self.pos()
        super().mouseMoveEvent(event)

        if self._is_dragging and self.scene():
            view = self.canvas

            # 获取管理实例
            manager = getattr(self.canvas, "guide_manager", None)

            if manager and view:
                scale_factor = view.transform().m11()
                # 动态阈值：物理像素 5px 对应的逻辑坐标差异
                logical_threshold = 5.0 / scale_factor if scale_factor > 0 else 0.01

                # 性能优化：从缓存的点图元集合中提取，避免遍历全部场景对象
                other_points = [item.scenePos() for item in self.canvas._point_item_set if item != self]

                # 调用绘制
                manager.draw_guides(
                    current_pos=self.scenePos(),  # 此时获取的是已经被磁吸修正过的最新坐标
                    other_points=other_points,
                    logical_threshold=logical_threshold,
                )

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        super().mouseReleaseEvent(event)
        self._is_dragging = False

        # 拖拽结束，擦除所有辅助线
        manager = getattr(self.canvas, "guide_manager", None)
        if manager:
            manager.clear()

    def itemChange(self, change, value):
        # 拦截拖拽时产生的新坐标分配
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and self.scene():
            view = self.canvas
            if view:
                scale_factor = view.transform().m11()

                # 性能优化：从缓存的点图元集合中提取，避免遍历全部场景对象
                other_points = [item.scenePos() for item in self.canvas._point_item_set if item != self]

                # 送入引擎，计算最终修饰过的吸附坐标
                snapped_pos = snapper.snap(
                    raw_logical_pos=value,
                    scale_factor=scale_factor,
                    existing_points=other_points,
                    grid_size=1.0,
                )

                # 同步文本跟随
                if self.obj_id in self.canvas.object_map:
                    text_item = self.canvas.object_map[self.obj_id].get("text")
                    if text_item:
                        text_item.setPos(snapped_pos.x() + 8, snapped_pos.y() - 12)

                # 触发向上传递的坐标更新信号
                self.canvas.object_moved.emit(self.obj_id, snapped_pos.x(), snapped_pos.y())

                return snapped_pos

        return super().itemChange(change, value)


class GeometryCanvas(QGraphicsView):
    # 原有信号：由 main_window 连接，触发模型层写入
    point_added = Signal(float, float)
    segment_added = Signal(str, str)  # 保留，供外部兼容使用
    circle_added = Signal(str, float)  # 保留，供外部兼容使用
    object_selected = Signal(str)
    object_moved = Signal(str, float, float)

    # BUG2 修复：新增坐标信号，替代 add_segment/circle/polygon 中的直接绘制
    segment_added_coords = Signal(float, float, float, float)  # x1, y1, x2, y2
    circle_added_coords = Signal(float, float, float)  # cx, cy, radius
    polygon_added_coords = Signal(list)  # [(x,y), ...]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene_obj = QGraphicsScene(self)
        self.setScene(self.scene_obj)

        # 初始化辅助线管理器
        self.guide_manager = SmartGuideManager(self.scene_obj)

        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.NoDrag)

        import time

        self._is_panning = False
        self._last_pan_pos = QPointF()
        self._last_pan_time = 0.0
        self._velocity_x = 0.0
        self._velocity_y = 0.0
        self._inertia_timer = QTimer(self)
        self._inertia_timer.setInterval(16)
        self._inertia_timer.timeout.connect(self._apply_inertia)
        self._friction = 0.92
        self._stop_threshold = 0.5

        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        # 性能优化：禁用不必要的渲染更新
        self.setOptimizationFlag(QGraphicsView.DontAdjustForAntialiasing, True)
        self.setViewportUpdateMode(QGraphicsView.MinimalViewportUpdate)

        self.scene_obj.setBackgroundBrush(QColor("#ffffff"))
        self.scene_obj.setSceneRect(-500, -500, 1000, 1000)

        self.current_tool = "select"
        self.selected_item = None
        self.object_map = {}
        self.drawing_points = []

        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)

        self._current_scale = 1.0
        self._target_scale = 1.0
        self.min_zoom = 0.1
        self.max_zoom = 10.0

        # 细节优化 2：配置 200ms 平滑缓动动画
        self._zoom_animation = QVariantAnimation(self)
        self._zoom_animation.setDuration(200)  # 严格限制 200ms 响应时间
        self._zoom_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._zoom_animation.valueChanged.connect(self._on_zoom_animation_step)

        # 保留字典，供将来可能的其他用途；不在 add_* 方法中填充
        self.point_items = {}
        self.segment_items = {}
        self.circle_items = {}
        self.polygon_items = {}
        self.curve_items = {}  # 存储所有曲线类型（圆锥曲线、函数绘图等）
        self.preview_item = None

        # 性能优化：维护点图元集合，拖拽时直接遍历点集合而非全部场景对象
        self._point_item_set = set()

        # ------------------------------------------------------------------
        # 混合渲染优化：防抖定时器和待渲染队列
        # ------------------------------------------------------------------
        self.latex_render_timer = QTimer()
        self.latex_render_timer.setSingleShot(True)
        self.latex_render_timer.timeout.connect(self._flush_latex_rendering)
        self.pending_latex_updates = {}  # {obj_id: latex_str}
        self._is_dragging = False  # 全局拖拽状态标记
        self.active_bubbles = []  # 活跃的空间气泡
        self.analysis_items = []  # 临时微积分分析图形（阴影、切线等）

    def spawn_spatial_bubble(self, obj_id: str, text: str):
        """在目标元素旁生成讲解气泡"""
        if obj_id not in self.object_map:
            print(f"找不到目标图形 ID {obj_id}，无法生成气泡")
            return

        target_item = self.object_map[obj_id].get("item")
        if not target_item:
            return

        from mathlab.ui.floating_bubble import FloatingBubbleProxy

        # 生成并挂载气泡
        bubble = FloatingBubbleProxy(target_item, text, self.scene_obj)
        self.active_bubbles.append(bubble)

    def clear_active_bubbles(self):
        """清除所有悬浮气泡"""
        if hasattr(self, "active_bubbles"):
            for bubble in self.active_bubbles:
                if bubble.scene() == self.scene_obj:
                    self.scene_obj.removeItem(bubble)
            self.active_bubbles.clear()

    # ------------------------------------------------------------------
    # 网格绘制（重写 drawBackground，只绘制可见区域，无独立 Item 开销）
    # ------------------------------------------------------------------
    def drawBackground(self, painter: QPainter, rect: QRectF):
        """重写背景绘制：使用单次 Painter 调用绘制网格，替代 404 个 QGraphicsLineItem"""
        super().drawBackground(painter, rect)

        grid_pen = _get_grid_pen()
        painter.setPen(grid_pen)

        # 计算可见区域范围内的网格线（避免绘制不可见区域）
        grid_spacing = 20
        left = int(rect.left() // grid_spacing) * grid_spacing
        right = int(rect.right() // grid_spacing + 1) * grid_spacing
        top = int(rect.top() // grid_spacing) * grid_spacing
        bottom = int(rect.bottom() // grid_spacing + 1) * grid_spacing

        # 批量绘制垂直线
        path_v = QPainterPath()
        for x in range(left, right + 1, grid_spacing):
            path_v.moveTo(x, top)
            path_v.lineTo(x, bottom)
        painter.drawPath(path_v)

        # 批量绘制水平线
        path_h = QPainterPath()
        for y in range(top, bottom + 1, grid_spacing):
            path_h.moveTo(left, y)
            path_h.lineTo(right, y)
        painter.drawPath(path_h)

        # 坐标轴
        painter.setPen(_get_origin_pen())
        painter.drawLine(QLineF(0, top, 0, bottom))
        painter.drawLine(QLineF(left, 0, right, 0))

    # ------------------------------------------------------------------
    # 缩放
    # ------------------------------------------------------------------
    def wheelEvent(self, event: QWheelEvent):
        """拦截滚轮事件，转化为动画驱动"""
        angle_delta = event.angleDelta().y()
        if angle_delta == 0:
            return

        factor = 1.2 if angle_delta > 0 else 1.0 / 1.2
        self.apply_zoom(factor)
        event.accept()

    def apply_zoom(self, zoom_factor: float):
        new_target = self._target_scale * zoom_factor

        # 细节优化 3：设置严格的缩放边界
        new_target = max(self.min_zoom, min(self.max_zoom, new_target))

        if new_target != self._target_scale:
            self._target_scale = new_target

            # 从当前瞬时状态平滑过渡到最新的目标状态
            self._zoom_animation.stop()
            self._zoom_animation.setStartValue(self._current_scale)
            self._zoom_animation.setEndValue(self._target_scale)
            self._zoom_animation.start()

    def _on_zoom_animation_step(self, value: float):
        """动画每帧回调：计算增量并应用缩放"""
        if self._current_scale == 0:
            return

        factor = value / self._current_scale
        self.scale(factor, factor)
        self._current_scale = value

    def zoom_in(self):
        self.apply_zoom(1.2)

    def zoom_out(self):
        self.apply_zoom(1.0 / 1.2)

    # ------------------------------------------------------------------
    # BUG3 修复：set_tool 根据工具类型设置正确的拖动模式
    #   pan    -> ScrollHandDrag   （平移画布）
    #   select -> RubberBandDrag   （框选对象）
    #   其他   -> NoDrag           （几何绘制，避免拖动干扰点击坐标）
    # ------------------------------------------------------------------
    def set_tool(self, tool):
        self.current_tool = tool
        if tool == "select":
            self.setDragMode(QGraphicsView.RubberBandDrag)
        else:
            self.setDragMode(QGraphicsView.NoDrag)

    # ------------------------------------------------------------------
    # 鼠标事件
    # ------------------------------------------------------------------
    def mousePressEvent(self, event):
        is_pan_trigger = event.button() == Qt.MiddleButton or (
            event.button() == Qt.LeftButton and self.current_tool == "pan"
        )
        if is_pan_trigger:
            import time

            self._is_panning = True
            self._last_pan_pos = event.position()
            self._last_pan_time = time.time()
            self._inertia_timer.stop()
            self._velocity_x = 0.0
            self._velocity_y = 0.0
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return

        scene_pos = self.mapToScene(event.pos())

        # 清除任何活动的空间气泡
        self.clear_active_bubbles()

        if self.current_tool == "select":
            super().mousePressEvent(event)
            return

        # 多边形：右键完成绘制
        if event.button() == Qt.RightButton and self.current_tool == "polygon" and len(self.drawing_points) >= 3:
            self.add_polygon()
            return

        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return

        if self.current_tool == "point":
            self.add_point(scene_pos.x(), scene_pos.y())

        elif self.current_tool == "segment":
            self.drawing_points.append((scene_pos.x(), scene_pos.y()))
            if len(self.drawing_points) == 2:
                self.add_segment()
                self.drawing_points.clear()

        elif self.current_tool == "circle":
            if len(self.drawing_points) == 0:
                self.drawing_points.append((scene_pos.x(), scene_pos.y()))
            else:
                dx = scene_pos.x() - self.drawing_points[0][0]
                dy = scene_pos.y() - self.drawing_points[0][1]
                radius = (dx**2 + dy**2) ** 0.5
                self.add_circle(self.drawing_points[0], radius)
                self.drawing_points.clear()

        elif self.current_tool == "polygon":
            self.drawing_points.append((scene_pos.x(), scene_pos.y()))
            if len(self.drawing_points) >= 2:
                self.update_polygon_preview()

        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._is_panning:
            import time

            current_pos = event.position()
            current_time = time.time()

            delta_pos = current_pos - self._last_pan_pos
            delta_time = current_time - self._last_pan_time

            self.horizontalScrollBar().setValue(int(self.horizontalScrollBar().value() - delta_pos.x()))
            self.verticalScrollBar().setValue(int(self.verticalScrollBar().value() - delta_pos.y()))

            if delta_time > 0:
                # 计算真实的物理速度 (像素/秒)
                instant_vx = delta_pos.x() / delta_time
                instant_vy = delta_pos.y() / delta_time

                # 转换为每帧 (16ms) 的标度速度，供 _apply_inertia 使用
                frame_vx = instant_vx * 0.016
                frame_vy = instant_vy * 0.016

                self._velocity_x = self._velocity_x * 0.2 + frame_vx * 0.8
                self._velocity_y = self._velocity_y * 0.2 + frame_vy * 0.8

            self._last_pan_pos = event.position()
            self._last_pan_time = current_time
            event.accept()
            return

        scene_pos = self.mapToScene(event.pos())

        if self.current_tool == "segment" and len(self.drawing_points) == 1:
            self.update_segment_preview(scene_pos)
        elif self.current_tool == "circle" and len(self.drawing_points) == 1:
            self.update_circle_preview(scene_pos)
        elif self.current_tool == "polygon" and len(self.drawing_points) >= 1:
            self.update_polygon_preview(scene_pos)

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._is_panning:
            import time

            self._is_panning = False
            self.setCursor(Qt.ArrowCursor)

            if time.time() - self._last_pan_time > 0.05:
                self._velocity_x = 0.0
                self._velocity_y = 0.0

            if abs(self._velocity_x) > self._stop_threshold or abs(self._velocity_y) > self._stop_threshold:
                self._inertia_timer.start()

            event.accept()
            return

        super().mouseReleaseEvent(event)

    def _apply_inertia(self):
        self.horizontalScrollBar().setValue(int(self.horizontalScrollBar().value() - self._velocity_x))
        self.verticalScrollBar().setValue(int(self.verticalScrollBar().value() - self._velocity_y))

        self._velocity_x *= self._friction
        self._velocity_y *= self._friction

        if abs(self._velocity_x) < self._stop_threshold and abs(self._velocity_y) < self._stop_threshold:
            self._inertia_timer.stop()
            self._velocity_x = 0.0
            self._velocity_y = 0.0

    # ------------------------------------------------------------------
    # BUG2 修复：add_point 只发射信号，不直接绘制
    #   实际绘制由 main_window.on_point_added -> draw_object 统一完成
    # ------------------------------------------------------------------
    def add_point(self, x, y):
        self.point_added.emit(x, y)

    # ------------------------------------------------------------------
    # BUG2 修复：add_segment 移除预览项，只发射坐标信号，不直接绘制
    # ------------------------------------------------------------------
    def add_segment(self):
        if len(self.drawing_points) != 2:
            return

        # 移除预览线
        if self.preview_item is not None:
            self.scene_obj.removeItem(self.preview_item)
            self.preview_item = None

        p1, p2 = self.drawing_points
        self.segment_added_coords.emit(p1[0], p1[1], p2[0], p2[1])

    # ------------------------------------------------------------------
    # BUG2 修复：add_circle 移除预览项，只发射坐标信号，不直接绘制
    # ------------------------------------------------------------------
    def add_circle(self, center, radius):
        # 移除预览圆
        if self.preview_item is not None:
            self.scene_obj.removeItem(self.preview_item)
            self.preview_item = None

        cx, cy = center
        self.circle_added_coords.emit(cx, cy, radius)

    # ------------------------------------------------------------------
    # BUG1 + BUG2 修复：
    #   - 先保存点列表再清空（BUG1）
    #   - 移除预览项（清理）
    #   - 只发射信号，不直接绘制（BUG2）
    # ------------------------------------------------------------------
    def add_polygon(self):
        if len(self.drawing_points) < 3:
            return

        # BUG1 修复：先保存，再清空，最后用保存的列表发射信号
        saved_points = self.drawing_points.copy()
        self.drawing_points.clear()

        # 移除预览多边形
        if self.preview_item is not None:
            self.scene_obj.removeItem(self.preview_item)
            self.preview_item = None

        self.polygon_added_coords.emit(saved_points)

    # ------------------------------------------------------------------
    # 预览辅助方法（绘制虚线预览，不写入 object_map）
    # ------------------------------------------------------------------
    def update_segment_preview(self, scene_pos):
        if len(self.drawing_points) != 1:
            return

        p1 = self.drawing_points[0]
        if self.preview_item is not None:
            self.scene_obj.removeItem(self.preview_item)

        self.preview_item = QGraphicsLineItem(p1[0], p1[1], scene_pos.x(), scene_pos.y())
        self.preview_item.setPen(QPen(QColor("#4b41e1"), 2, Qt.DashLine))
        self.scene_obj.addItem(self.preview_item)

    def update_circle_preview(self, scene_pos):
        if len(self.drawing_points) != 1:
            return

        cx, cy = self.drawing_points[0]
        dx = scene_pos.x() - cx
        dy = scene_pos.y() - cy
        radius = (dx**2 + dy**2) ** 0.5

        if self.preview_item is not None:
            self.scene_obj.removeItem(self.preview_item)

        self.preview_item = QGraphicsEllipseItem(cx - radius, cy - radius, radius * 2, radius * 2)
        self.preview_item.setPen(QPen(QColor("#006058"), 2, Qt.DashLine))
        self.preview_item.setBrush(QBrush(Qt.NoBrush))
        self.scene_obj.addItem(self.preview_item)

    def update_polygon_preview(self, scene_pos=None):
        if len(self.drawing_points) < 1:
            return

        if self.preview_item is not None:
            self.scene_obj.removeItem(self.preview_item)

        polygon = QPolygonF()
        for point in self.drawing_points:
            polygon.append(QPointF(point[0], point[1]))

        if scene_pos:
            polygon.append(QPointF(scene_pos.x(), scene_pos.y()))

        self.preview_item = QGraphicsPolygonItem(polygon)
        self.preview_item.setPen(QPen(QColor("#9333ea"), 2, Qt.DashLine))
        self.preview_item.setBrush(QBrush(QColor("#9333ea"), Qt.Dense4Pattern))
        self.scene_obj.addItem(self.preview_item)

    # ------------------------------------------------------------------
    # 清空画布
    # ------------------------------------------------------------------
    def clear_canvas(self):
        self.scene_obj.clear()
        self.object_map.clear()
        self.point_items.clear()
        self.segment_items.clear()
        self.circle_items.clear()
        self.polygon_items.clear()
        self.curve_items.clear()
        self._point_item_set.clear()
        self.drawing_points.clear()
        self.preview_item = None
        # 重置绘制状态，防止下次 mouseMoveEvent 操作野指针
        # 注意：不强制重置 current_tool，保持用户当前的工具选择（如用户正在连续画点）

    # ------------------------------------------------------------------
    # 由 main_window 调用，统一绘制并写入 object_map
    # ------------------------------------------------------------------
    def draw_object(self, obj_id, obj_data):
        obj_type = obj_data.get("type")
        is_draft = obj_data.get("is_draft", False)

        if obj_type == "Point":
            x = obj_data["coordinates"].get("x", 0)
            y = obj_data["coordinates"].get("y", 0)
            name = obj_data.get("name", "")

            point_item = GeometryPointItem(-5, -5, 10, 10, obj_id, self)
            point_item.setPos(x, y)

            if is_draft:
                point_item.setBrush(QBrush(QColor(0, 120, 215, 100)))
                point_item.setPen(QPen(QColor(0, 120, 215), 1, Qt.DashLine))
                point_item.setOpacity(0.6)
            else:
                point_item.setBrush(QBrush(QColor("#004ac6")))
                point_item.setPen(QPen(QColor("#004ac6"), 1))
            point_item.setZValue(10)

            # 使用 MathGraphicsItem 替代 QGraphicsTextItem，支持 LaTeX 渲染
            text_item = MathGraphicsItem(name, use_latex=True)
            text_item.setPos(x + 8, y - 12)
            text_item.setZValue(11)

            self.scene_obj.addItem(point_item)
            self.scene_obj.addItem(text_item)

            self._point_item_set.add(point_item)
            self.object_map[obj_id] = {"point": point_item, "text": text_item}

        elif obj_type == "Segment":
            x1 = obj_data["coordinates"].get("x1", 0)
            y1 = obj_data["coordinates"].get("y1", 0)
            x2 = obj_data["coordinates"].get("x2", 0)
            y2 = obj_data["coordinates"].get("y2", 0)

            segment_item = QGraphicsLineItem(x1, y1, x2, y2)

            if is_draft:
                segment_item.setPen(QPen(QColor(0, 120, 215), 2.0, Qt.DashLine))
                segment_item.setOpacity(0.6)
            else:
                segment_item.setPen(QPen(QColor("#4b41e1"), 2))
            segment_item.setFlags(QGraphicsItem.ItemIsSelectable)

            self.scene_obj.addItem(segment_item)
            self.object_map[obj_id] = {"segment": segment_item}

        elif obj_type == "Circle":
            cx = obj_data["coordinates"].get("cx", 0)
            cy = obj_data["coordinates"].get("cy", 0)
            r = obj_data["coordinates"].get("r", 1)

            circle_item = QGraphicsEllipseItem(cx - r, cy - r, r * 2, r * 2)

            if is_draft:
                circle_item.setPen(QPen(QColor(0, 120, 215), 2.0, Qt.DashLine))
                circle_item.setOpacity(0.6)
            else:
                circle_item.setPen(QPen(QColor("#006058"), 2))
            circle_item.setBrush(QBrush(Qt.NoBrush))
            circle_item.setFlags(QGraphicsItem.ItemIsSelectable)

            self.scene_obj.addItem(circle_item)
            self.object_map[obj_id] = {"circle": circle_item}

        elif obj_type == "Polygon":
            points = obj_data.get("points", [])
            name = obj_data.get("name", "")

            polygon_item = QGraphicsPolygonItem()
            polygon = QPolygonF()
            for point in points:
                polygon.append(QPointF(point[0], point[1]))
            polygon_item.setPolygon(polygon)

            if is_draft:
                polygon_item.setPen(QPen(QColor(0, 120, 215), 2.0, Qt.DashLine))
                polygon_item.setBrush(QBrush(QColor(0, 120, 215, 50)))
                polygon_item.setOpacity(0.6)
            else:
                polygon_item.setPen(QPen(QColor("#9333ea"), 2))
                polygon_item.setBrush(QBrush(QColor("#9333ea"), Qt.Dense4Pattern))
            polygon_item.setFlags(QGraphicsItem.ItemIsSelectable)

            self.scene_obj.addItem(polygon_item)
            self.object_map[obj_id] = {"polygon": polygon_item}

        # 新增：圆锥曲线和函数绘图
        elif obj_type in [
            "Ellipse",
            "Hyperbola",
            "Parabola",
            "ConicSection",
            "FunctionPlot",
            "ImplicitPlot",
            "PolarPlot",
            "Locus",
        ]:
            points = obj_data.get("points_data", []) or obj_data.get("coordinates", {}).get("points", [])

            if not points:
                return

            # 使用 QPainterPath 绘制平滑曲线
            path = QPainterPath()
            if len(points) > 0:
                path.moveTo(QPointF(points[0][0], points[0][1]))
                for point in points[1:]:
                    path.lineTo(QPointF(point[0], point[1]))

            # 根据类型设置不同颜色
            color_map = {
                "Ellipse": QColor("#ff6b00"),
                "Hyperbola": QColor("#d90429"),
                "Parabola": QColor("#7209b7"),
                "ConicSection": QColor("#f72585"),
                "FunctionPlot": QColor("#4cc9f0"),
                "ImplicitPlot": QColor("#4361ee"),
                "PolarPlot": QColor("#3a0ca3"),
                "Locus": QColor("#f72585"),
            }
            color = color_map.get(obj_type, QColor("#004ac6"))

            if is_draft:
                curve_item = self.scene_obj.addPath(
                    path,
                    QPen(QColor(0, 120, 215), 2.0, Qt.DashLine),
                    QBrush(Qt.NoBrush),
                )
                curve_item.setOpacity(0.6)
            else:
                curve_item = self.scene_obj.addPath(path, QPen(color, 2), QBrush(Qt.NoBrush))
            curve_item.setFlags(QGraphicsItem.ItemIsSelectable)

            self.object_map[obj_id] = {"curve": curve_item}
            self.curve_items[obj_id] = curve_item

    def update_object(self, obj_id, obj_data):
        if obj_id not in self.object_map:
            self.draw_object(obj_id, obj_data)
            return

        obj_type = obj_data.get("type")
        is_draft = obj_data.get("is_draft", False)
        obj_info = self.object_map[obj_id]

        if obj_type == "Point":
            x = obj_data["coordinates"].get("x", 0)
            y = obj_data["coordinates"].get("y", 0)

            obj_info["point"].setPos(x, y)
            if is_draft:
                obj_info["point"].setBrush(QBrush(QColor(0, 120, 215, 100)))
                obj_info["point"].setPen(QPen(QColor(0, 120, 215), 1, Qt.DashLine))
                obj_info["point"].setOpacity(0.6)
            else:
                obj_info["point"].setBrush(QBrush(QColor("#004ac6")))
                obj_info["point"].setPen(QPen(QColor("#004ac6"), 1))
                obj_info["point"].setOpacity(1.0)

            # [P0修复 Bug3] 同步更新关联的文本图元内容
            text_item = obj_info.get("text")
            new_name = obj_data.get("name", "")
            if text_item:
                if hasattr(text_item, "set_text"):
                    text_item.set_text(new_name)
                elif hasattr(text_item, "setPlainText"):
                    text_item.setPlainText(new_name)
                # 同步更新文本的位置，保持相对偏移
                text_item.setPos(x + 8, y - 12)

        elif obj_type == "Segment":
            x1 = obj_data["coordinates"].get("x1", 0)
            y1 = obj_data["coordinates"].get("y1", 0)
            x2 = obj_data["coordinates"].get("x2", 0)
            y2 = obj_data["coordinates"].get("y2", 0)

            obj_info["segment"].setLine(x1, y1, x2, y2)
            if is_draft:
                obj_info["segment"].setPen(QPen(QColor(0, 120, 215), 2.0, Qt.DashLine))
                obj_info["segment"].setOpacity(0.6)
            else:
                obj_info["segment"].setPen(QPen(QColor("#4b41e1"), 2))
                obj_info["segment"].setOpacity(1.0)

        elif obj_type == "Circle":
            cx = obj_data["coordinates"].get("cx", 0)
            cy = obj_data["coordinates"].get("cy", 0)
            r = obj_data["coordinates"].get("r", 1)

            obj_info["circle"].setRect(cx - r, cy - r, r * 2, r * 2)
            if is_draft:
                obj_info["circle"].setPen(QPen(QColor(0, 120, 215), 2.0, Qt.DashLine))
                obj_info["circle"].setOpacity(0.6)
            else:
                obj_info["circle"].setPen(QPen(QColor("#006058"), 2))
                obj_info["circle"].setOpacity(1.0)

        elif obj_type == "Polygon":
            points = obj_data.get("points", [])
            polygon = QPolygonF()
            for point in points:
                polygon.append(QPointF(point[0], point[1]))
            obj_info["polygon"].setPolygon(polygon)
            if is_draft:
                obj_info["polygon"].setPen(QPen(QColor(0, 120, 215), 2.0, Qt.DashLine))
                obj_info["polygon"].setBrush(QBrush(QColor(0, 120, 215, 50)))
                obj_info["polygon"].setOpacity(0.6)
            else:
                obj_info["polygon"].setPen(QPen(QColor("#9333ea"), 2))
                obj_info["polygon"].setBrush(QBrush(QColor("#9333ea"), Qt.Dense4Pattern))
                obj_info["polygon"].setOpacity(1.0)

        # 新增：更新曲线对象
        elif obj_type in [
            "Ellipse",
            "Hyperbola",
            "Parabola",
            "ConicSection",
            "FunctionPlot",
            "ImplicitPlot",
            "PolarPlot",
            "Locus",
        ]:
            # 删除旧曲线并重新绘制
            self.remove_object(obj_id)
            self.draw_object(obj_id, obj_data)

    def remove_object(self, obj_id):
        if obj_id in self.object_map:
            obj_info = self.object_map[obj_id]
            # 从点图元缓存集合中移除
            point_item = obj_info.get("point")
            if point_item:
                self._point_item_set.discard(point_item)
            for item in obj_info.values():
                self.scene_obj.removeItem(item)
            del self.object_map[obj_id]
            # 如果是曲线对象，也从 curve_items 中删除
            if obj_id in self.curve_items:
                del self.curve_items[obj_id]

    def highlight_elements(self, engine, element_names: list, color_name: str):
        """
        触发激光笔特效：让指定的元素呼吸闪烁 3 次
        """
        color_map = {
            "red": QColor(231, 76, 60),
            "blue": QColor(52, 152, 219),
            "green": QColor(46, 204, 113),
            "orange": QColor(230, 126, 34),
        }
        target_color = color_map.get(color_name, QColor(241, 196, 15))

        items_to_highlight = []
        if hasattr(engine, "get_all_objects"):
            objects = engine.get_all_objects()
        elif hasattr(engine, "objects"):
            objects = list(engine.objects.values())
        else:
            objects = []

        target_ids = [obj.id for obj in objects if obj.name in element_names]

        for obj_id in target_ids:
            if obj_id in self.object_map:
                obj_info = self.object_map[obj_id]
                for key, item in obj_info.items():
                    if key != "text":
                        items_to_highlight.append(item)

        if not items_to_highlight:
            return

        self._start_blink_animation(items_to_highlight, target_color)

    def _start_blink_animation(self, items, highlight_color):
        blink_count = 0
        max_blinks = 6

        original_pens = {item: item.pen() for item in items if hasattr(item, "pen")}
        highlight_pen = QPen(highlight_color, 4.0)

        # [BUG修复] 移除 QTimer(self) 避免循环引用，它在结束时会 deleteLater
        timer = QTimer()

        def toggle_color():
            nonlocal blink_count
            is_highlight_phase = blink_count % 2 == 0

            for item in items:
                if hasattr(item, "setPen"):
                    if is_highlight_phase:
                        item.setPen(highlight_pen)
                    else:
                        item.setPen(original_pens.get(item, QPen(Qt.black)))

            blink_count += 1
            if blink_count >= max_blinks:
                timer.stop()
                timer.deleteLater()
                for item in items:
                    # [BUG修复] 动画结束后恢复原始 pen，而不是永久变成高亮颜色
                    if hasattr(item, "setPen"):
                        item.setPen(original_pens.get(item, QPen(Qt.black)))

        timer.timeout.connect(toggle_color)
        timer.start(300)

    def select_object(self, obj_id):
        for item in self.scene_obj.selectedItems():
            item.setSelected(False)

        if obj_id in self.object_map:
            for item in self.object_map[obj_id].values():
                item.setSelected(True)

    def focus_on_object(self, obj_id):
        if obj_id in self.object_map:
            first_item = list(self.object_map[obj_id].values())[0]
            self.centerOn(first_item.sceneBoundingRect().center())

    # ------------------------------------------------------------------
    # 混合渲染优化：降级渲染与防抖机制
    # ------------------------------------------------------------------
    def update_object_equation(self, obj_id: str, new_latex: str):
        """
        更新对象的公式显示（带防抖优化）

        拖拽时疯狂调用这个方法：
        1. 先用普通文本极速占位（降级渲染）
        2. 存入待渲染队列，重启 200ms 的防抖定时器

        Args:
            obj_id: 对象 ID
            new_latex: 新的 LaTeX 公式字符串
        """
        # 1. 立即更新为普通文本占位符（极速）
        self._set_fast_fallback_text(obj_id, new_latex)

        # 2. 存入待渲染队列，重启防抖定时器
        self.pending_latex_updates[obj_id] = new_latex
        self.latex_render_timer.start(200)  # 200ms 防抖

    def _set_fast_fallback_text(self, obj_id: str, text: str):
        """
        设置快速降级文本（拖拽时使用）

        Args:
            obj_id: 对象 ID
            text: 显示文本
        """
        if obj_id not in self.object_map:
            return

        obj_info = self.object_map[obj_id]
        text_item = obj_info.get("text")

        if text_item is None:
            return

        # 如果是 MathGraphicsItem，设置为拖拽模式
        if isinstance(text_item, MathGraphicsItem):
            text_item.set_dragging(True)
            text_item.set_text(text)
        elif isinstance(text_item, QGraphicsTextItem):
            # 兼容旧的 QGraphicsTextItem
            text_item.setPlainText(text)

    def _flush_latex_rendering(self):
        """
        鼠标停下 200ms 后执行：将占位符替换为真正的高清 LaTeX SVG
        """
        if not self.pending_latex_updates:
            return

        for obj_id, latex_str in self.pending_latex_updates.items():
            if obj_id in self.object_map:
                obj_info = self.object_map[obj_id]
                text_item = obj_info.get("text")

                if text_item is None:
                    continue

                # 如果是 MathGraphicsItem，恢复 LaTeX 渲染
                if isinstance(text_item, MathGraphicsItem):
                    text_item.set_dragging(False)
                    text_item.set_text(latex_str)

        self.pending_latex_updates.clear()

    # ------------------------------------------------------------------
    # AI 双光标动画系统 (Dual Cursor)
    # ------------------------------------------------------------------
    def execute_commands_with_animation(self, engine, commands: list):
        """接收 AI 下发的指令，加入排期队列"""
        if not hasattr(self, "ai_cursor"):
            from mathlab.ui.ai_cursor import AICursorItem

            self.ai_cursor = AICursorItem()
            self.scene_obj.addItem(self.ai_cursor)
            self._command_queue = []
            self._is_animating = False

        self._command_queue.extend(commands)
        if not self._is_animating:
            self._process_next_command(engine)

    def _process_next_command(self, engine):
        """递归消费指令队列"""
        if not hasattr(self, "_command_queue") or not self._command_queue:
            self._is_animating = False
            # 队列耗尽，隐藏 AI 光标，深藏功与名
            if hasattr(self, "ai_cursor"):
                QTimer.singleShot(1000, lambda: self.ai_cursor.setVisible(False))
            return

        self._is_animating = True
        cmd = self._command_queue.pop(0)

        op = cmd.get("cmd")
        # 兼容防幻觉重命名
        if op == "draw_point":
            op = "add_point"
        if op == "draw_circle":
            op = "add_circle"
        if op == "draw_segment":
            op = "add_segment"
        if op == "draw_polygon":
            op = "add_polygon"

        try:
            if op == "add_point":
                self._animate_add_point(engine, cmd)
            elif op == "add_segment":
                self._animate_add_segment(engine, cmd)
            else:
                # 其他复杂图形（如圆/多边形），暂时降级为直接渲染
                self._execute_single_instant(engine, cmd, op)
                self._process_next_command(engine)
        except Exception as e:
            print(f"AI 动画执行失败: {e}")
            self._process_next_command(engine)  # 出错也继续下一条

    def _execute_single_instant(self, engine, cmd, op):
        try:
            if op == "add_circle":
                engine.add_circle(cmd["center"], cmd.get("radius", 1))
            elif op == "add_polygon":
                engine.add_polygon(cmd["points"])
        except Exception as e:
            print(f"执行指令 {op} 失败: {e}")

    def _animate_add_point(self, engine, cmd):
        """动作 1：AI 光标飞过去，然后点下一个点"""
        target_pos = QPointF(cmd.get("x", 0), cmd.get("y", 0))
        name = cmd.get("name", "")

        # 让光标飞跃，耗时 600ms
        self.ai_cursor.move_to(target_pos, 600)

        def on_arrive():
            self.ai_cursor.move_anim.finished.disconnect(on_arrive)
            # 到达目标后，真正在画板上生成这个几何点
            engine.add_point(target_pos.x(), target_pos.y(), name)
            # 停顿 200ms 后执行下一条指令，模拟人类写字的节奏
            QTimer.singleShot(200, lambda: self._process_next_command(engine))

        self.ai_cursor.move_anim.finished.connect(on_arrive)

    def _animate_add_segment(self, engine, cmd):
        """动作 2：极其惊艳的连线动画（边移动边画线）"""
        p1_name = cmd.get("p1")
        p2_name = cmd.get("p2")

        start_pos = None
        end_pos = None

        # 通过 engine 获取所有的物体，寻找物理坐标
        if hasattr(engine, "get_all_objects"):
            for obj in engine.get_all_objects():
                if obj.name == p1_name and obj.type == "Point":
                    start_pos = QPointF(obj.coordinates.get("x", 0), obj.coordinates.get("y", 0))
                if obj.name == p2_name and obj.type == "Point":
                    end_pos = QPointF(obj.coordinates.get("x", 0), obj.coordinates.get("y", 0))

        if not start_pos or not end_pos:
            return self._process_next_command(engine)

        # 第一阶段：AI 光标先空降到起点 p1
        self.ai_cursor.move_to(start_pos, 400)

        def on_ready_to_draw():
            self.ai_cursor.move_anim.finished.disconnect(on_ready_to_draw)

            # 创建一条临时的虚线，表示正在画
            temp_line = self.scene_obj.addLine(start_pos.x(), start_pos.y(), start_pos.x(), start_pos.y())
            temp_line.setPen(QPen(QColor(0, 191, 255), 2.0, Qt.PenStyle.DashLine))

            # 绑定实时重绘事件：光标在哪，线就拉到哪
            def update_temp_line():
                cur_pos = self.ai_cursor.scenePos()
                temp_line.setLine(start_pos.x(), start_pos.y(), cur_pos.x(), cur_pos.y())

            self.ai_cursor.cursorPosChanged.connect(update_temp_line)

            # 第二阶段：拖拽光标到终点 p2
            self.ai_cursor.move_to(end_pos, 800)  # 连线动画慢一点，800ms

            def on_draw_finished():
                self.ai_cursor.move_anim.finished.disconnect(on_draw_finished)
                self.ai_cursor.cursorPosChanged.disconnect(update_temp_line)

                # 画完后，销毁临时线，生成真实的几何物理线段
                self.scene_obj.removeItem(temp_line)
                engine.add_segment(p1_name, p2_name)

                # 停顿并执行下一跳
                QTimer.singleShot(200, lambda: self._process_next_command(engine))

            self.ai_cursor.move_anim.finished.connect(on_draw_finished)

        self.ai_cursor.move_anim.finished.connect(on_ready_to_draw)

    def begin_drag_operation(self):
        """
        开始拖拽操作：通知所有 MathGraphicsItem 进入降级模式
        """
        self._is_dragging = True
        for obj_info in self.object_map.values():
            text_item = obj_info.get("text")
            if isinstance(text_item, MathGraphicsItem):
                text_item.set_dragging(True)

    def end_drag_operation(self):
        """
        结束拖拽操作：恢复 LaTeX 渲染
        """
        self._is_dragging = False
        # 触发一次延迟渲染
        if self.pending_latex_updates:
            self._flush_latex_rendering()
        else:
            # 如果没有待更新的公式，直接恢复所有项
            for obj_info in self.object_map.values():
                text_item = obj_info.get("text")
                if isinstance(text_item, MathGraphicsItem):
                    text_item.set_dragging(False)

    # ==================================================================
    # 微积分与高阶分析：动态图象渲染
    # ==================================================================

    def _clear_analysis_items(self):
        """清除上一轮计算残留的阴影和切线"""
        for item in getattr(self, "analysis_items", []):
            if item.scene() == self.scene_obj:
                self.scene_obj.removeItem(item)
        self.analysis_items.clear()

    def render_integral_area(self, expr: str, a: float, b: float, result: float):
        """渲染定积分阴影面积"""
        import numpy as np
        import sympy as sp

        self._clear_analysis_items()

        try:
            x_sym = sp.Symbol("x")
            sp_expr = sp.sympify(expr)
            fast_func = sp.lambdify(x_sym, sp_expr, modules=["math", "numpy"])

            # 由于可能包含数学无定义点，使用安全求值
            x_vals = np.linspace(a, b, 200)

            path = QPainterPath()
            # 起点取 (a, 0)，配合末尾 (b, 0) 形成闭合的面积区域左/右边界
            path.moveTo(a, 0)

            for x in x_vals:
                try:
                    y = float(fast_func(x))
                    if not np.isfinite(y):
                        y = 0
                except Exception:
                    y = 0
                path.lineTo(x, y)

            path.lineTo(b, 0)
            path.closeSubpath()

            # 使用透明蓝色表示积分阴影
            brush = QBrush(QColor(2, 132, 199, 80))  # Tailwind sky-600 with 30% alpha
            pen = QPen(Qt.NoPen)
            area_item = self.scene_obj.addPath(path, pen, brush)
            area_item.setZValue(5)  # 放在网格之上，函数线之下
            self.analysis_items.append(area_item)

            # 在中心添加面积文本
            text_item = MathGraphicsItem(f"Area ≈ {result:.4f}", use_latex=True)
            mid_x = (a + b) / 2
            try:
                mid_y = float(fast_func(mid_x)) / 2
            except:
                mid_y = 0
            text_item.setPos(mid_x, mid_y)
            text_item.setZValue(15)
            self.scene_obj.addItem(text_item)
            self.analysis_items.append(text_item)

        except Exception as e:
            print(f"渲染积分阴影失败: {e}")

    def render_tangent_line(self, expr: str, x0: float, k: float):
        """渲染指定点的切线"""
        import sympy as sp

        self._clear_analysis_items()

        try:
            x_sym = sp.Symbol("x")
            sp_expr = sp.sympify(expr)
            fast_func = sp.lambdify(x_sym, sp_expr, modules=["math", "numpy"])

            try:
                y0 = float(fast_func(x0))
            except:
                print("切点无定义")
                return

            # 画一个突出的切点
            radius = 0.15
            point_item = self.scene_obj.addEllipse(
                x0 - radius,
                y0 - radius,
                radius * 2,
                radius * 2,
                QPen(Qt.NoPen),
                QBrush(QColor(190, 24, 93)),  # Tailwind pink-700
            )
            point_item.setZValue(12)
            self.analysis_items.append(point_item)

            # 画一条横跨视图的切线
            dx = 50.0  # 足够长以超出视口
            x1, y1 = x0 - dx, y0 - k * dx
            x2, y2 = x0 + dx, y0 + k * dx

            pen = QPen(QColor(190, 24, 93), 2, Qt.DashLine)
            line_item = self.scene_obj.addLine(x1, y1, x2, y2, pen)
            line_item.setZValue(11)
            self.analysis_items.append(line_item)

            # 在切点附近添加斜率文本
            text_item = MathGraphicsItem(f"k ≈ {k:.3f}", use_latex=True)
            text_item.setPos(x0 + 0.5, y0 + 0.5)
            text_item.setZValue(15)
            self.scene_obj.addItem(text_item)
            self.analysis_items.append(text_item)

        except Exception as e:
            print(f"渲染切线失败: {e}")
