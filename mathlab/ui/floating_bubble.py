from PySide6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsProxyWidget, QLabel, QVBoxLayout, QWidget


class FloatingBubbleWidget(QWidget):
    """纯 UI 层的气泡卡片，带有小尾巴和阴影"""

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)

        self.label = QLabel(text)
        self.label.setObjectName("floatingBubbleLabel")
        self.label.setWordWrap(True)
        # 样式由 styles.qss `QLabel#floatingBubbleLabel` 提供（三主题自适应）
        # 注意：高级做法是用 paintEvent 画一个带箭头的气泡框，这里用圆角矩形平替
        layout.addWidget(self.label)
        self.setMaximumWidth(250)  # 限制气泡宽度，防止遮挡过多画面


class FloatingBubbleProxy(QGraphicsProxyWidget):
    """
    画板里的物理气泡代理，负责追踪目标图形的位置
    """

    def __init__(self, target_item, text, scene):
        super().__init__()
        self.target_item = target_item
        self.scene = scene

        # 实例化 UI 并包装进 Proxy
        self.bubble_ui = FloatingBubbleWidget(text)
        self.setWidget(self.bubble_ui)

        # 确保气泡永远浮在所有图形的最上层
        self.setZValue(99999)
        self.scene.addItem(self)

        # 初始透明度为 0
        self.setOpacity(0.0)
        self.update_position()
        self._pop_animation()

    def update_position(self):
        """动态计算位置：永远贴在目标图形的右上角"""
        if not self.target_item:
            return

        # 获取目标图形的包围盒中心
        target_rect = self.target_item.sceneBoundingRect()
        target_center = target_rect.center()

        # 偏移量：向右上方偏移
        offset_x = target_rect.width() / 2 + 10
        offset_y = -self.bubble_ui.height() / 2

        self.setPos(target_center.x() + offset_x, target_center.y() + offset_y)

    def _pop_animation(self):
        """气泡弹出的 Q 弹动效"""
        self.anim = QPropertyAnimation(self, b"opacity")
        self.anim.setDuration(300)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.setEasingCurve(QEasingCurve.Type.OutBack)  # 带有轻微回弹效果
        self.anim.start()
