from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QPropertyAnimation,
    QSequentialAnimationGroup,
    Qt,
)
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QLabel,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class SmoothCollapsibleBox(QWidget):
    """
    极具现代感的平滑折叠面板 (Apple 风格)
    """

    def __init__(self, title="", parent=None):
        super().__init__(parent)
        self.toggle_btn = QToolButton(self)
        self.toggle_btn.setObjectName("collapsibleToggle")
        self.toggle_btn.setText(title)
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setChecked(True)
        self.toggle_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle_btn.setArrowType(Qt.ArrowType.DownArrow)
        self.toggle_btn.clicked.connect(self.on_toggle)

        # 内容区容器
        self.content_area = QScrollArea(self)
        self.content_area.setObjectName("collapsibleContent")
        self.content_area.setSizePolicy(
            self.content_area.sizePolicy().Policy.Expanding,
            self.content_area.sizePolicy().Policy.Fixed,
        )
        self.content_area.setFrameShape(QScrollArea.Shape.NoFrame)

        # 内部挂载点
        self.content_layout = QVBoxLayout()
        self.content_layout.setContentsMargins(0, 5, 0, 0)

        content_widget = QWidget()
        content_widget.setLayout(self.content_layout)
        self.content_area.setWidget(content_widget)
        self.content_area.setWidgetResizable(True)

        # 核心：高度属性动画
        self.animation = QPropertyAnimation(self.content_area, b"maximumHeight")
        self.animation.setDuration(350)  # 350ms 是人眼感觉最舒适的展开速度
        # 使用 InOutExpo 缓动曲线，实现“先慢、中间极快、结尾平滑刹车”的高级阻尼感
        self.animation.setEasingCurve(QEasingCurve.Type.InOutExpo)

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.toggle_btn)
        main_layout.addWidget(self.content_area)

    def set_content_layout(self, layout):
        """外部调用此方法注入具体内容"""
        # 移除旧布局
        QWidget().setLayout(self.content_layout)
        self.content_layout = layout
        self.content_area.widget().setLayout(self.content_layout)

    def on_toggle(self):
        checked = self.toggle_btn.isChecked()
        self.toggle_btn.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)

        # 动态计算内容物展开时所需的真实高度
        content_height = self.content_layout.sizeHint().height()

        self.animation.setStartValue(0 if checked else content_height)
        self.animation.setEndValue(content_height if checked else 0)
        self.animation.start()

    def collapse_silently(self):
        """静默折叠（供外部程序自动触发）"""
        if self.toggle_btn.isChecked():
            self.toggle_btn.setChecked(False)
            self.on_toggle()

    def expand_silently(self):
        """静默展开"""
        if not self.toggle_btn.isChecked():
            self.toggle_btn.setChecked(True)
            self.on_toggle()


class BreathingLabel(QLabel):
    """
    带呼吸灯特效的状态文本框 (用于表达 AI 思考中)
    """

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)

        # 组合动画：渐暗 -> 渐亮
        self.anim_group = QSequentialAnimationGroup(self)

        fade_out = QPropertyAnimation(self.opacity_effect, b"opacity")
        fade_out.setDuration(800)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.3)
        fade_out.setEasingCurve(QEasingCurve.Type.InOutSine)

        fade_in = QPropertyAnimation(self.opacity_effect, b"opacity")
        fade_in.setDuration(800)
        fade_in.setStartValue(0.3)
        fade_in.setEndValue(1.0)
        fade_in.setEasingCurve(QEasingCurve.Type.InOutSine)

        self.anim_group.addAnimation(fade_out)
        self.anim_group.addAnimation(fade_in)
        # 无限循环律动
        self.anim_group.setLoopCount(-1)

    def start_breathing(self):
        self.anim_group.start()

    def stop_breathing(self):
        self.anim_group.stop()
        self.opacity_effect.setOpacity(1.0)  # 恢复常亮
