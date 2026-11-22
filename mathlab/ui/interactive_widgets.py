from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSlider, QWidget


class MathSlider(QWidget):
    # 信号：发射变量名和最新的浮点数值
    value_changed = Signal(str, float)

    def __init__(self, name, min_val, max_val, current_val, parent=None):
        super().__init__(parent)
        self.name = name
        self.min_val = min_val
        self.max_val = max_val
        # QSlider 只能处理整数，所以我们放大 100 倍来实现 0.01 的精度
        self.scale_factor = 100.0

        self.init_ui(current_val)

    def init_ui(self, current_val):
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(10, 5, 10, 5)

        # 1. 变量名
        self.label_name = QLabel(f"<b>{self.name}</b>")
        self.label_name.setObjectName("mathSliderName")

        # 2. 滑块本体（样式由全局 styles.qss QSlider 提供）
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setMinimum(int(self.min_val * self.scale_factor))
        self.slider.setMaximum(int(self.max_val * self.scale_factor))
        self.slider.setValue(int(current_val * self.scale_factor))

        # 3. 实时数值显示
        self.label_val = QLabel(f"{current_val:.2f}")
        self.label_val.setObjectName("mathSliderValue")
        self.label_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.layout.addWidget(self.label_name)
        self.layout.addWidget(self.slider)
        self.layout.addWidget(self.label_val)

        # 🌟 监听拖动事件 🌟
        self.slider.valueChanged.connect(self.on_slider_move)

    def on_slider_move(self, int_val):
        float_val = int_val / self.scale_factor
        self.label_val.setText(f"{float_val:.2f}")
        # 通知外界：“用户把这个参数改了！”
        self.value_changed.emit(self.name, float_val)
