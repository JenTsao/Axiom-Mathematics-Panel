import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from mathlab.core.async_workers import TaskManager
from mathlab.core.cs_complex_engine import get_cs_complex


class ComplexPanel(QWidget):
    """
    分形探索器 (复平面动态迭代)
    支持无限缩放与丝滑拖拽
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mandelbrot Explorer")

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(self.image_label)

        # 初始视口范围 (经典的 Mandelbrot 初始视图)
        self.x_min = -2.5
        self.x_max = 1.0
        self.y_min = -1.0
        self.y_max = 1.0

        self.max_iter = 256
        self.task_manager = TaskManager()
        self.is_dragging = False

        # 缓存当前的 QImage 以避免被垃圾回收
        self._current_qimage = None

        # 延迟到窗口显示后再初次渲染，以获得正确的尺寸

    def _request_render(self):
        width, height = self.width(), self.height()
        if width <= 10 or height <= 10:
            return

        # 使用 TaskManager 抛入后台线程
        # group_id="mandelbrot_render" 确保我们在疯狂滚轮/拖拽时，
        # 旧的任务会被覆盖，只渲染最新的一帧，杜绝队列堆积与卡顿！
        self.task_manager.submit(
            fn=self._render_task,
            x_min=self.x_min,
            x_max=self.x_max,
            y_min=self.y_min,
            y_max=self.y_max,
            width=width,
            height=height,
            max_iter=self.max_iter,
            on_success=self._on_render_success,
            group_id="mandelbrot_render",
        )

    def _render_task(self, x_min, x_max, y_min, y_max, width, height, max_iter):
        """此方法在子线程 (QThreadPool) 中执行，吃满 CPU 进行高强度复数计算"""
        engine = get_cs_complex()
        if engine is None:
            raise RuntimeError("C# 分形引擎不可用（pythonnet / .NET 缺失）")
        rgb_matrix = engine.generate_smooth_mandelbrot(x_min, x_max, y_min, y_max, width, height, max_iter=max_iter)
        return rgb_matrix, width, height

    def _on_render_success(self, result):
        """此方法在主线程中执行，用于刷新 UI"""
        rgb_matrix, width, height = result
        bytes_per_line = 3 * width

        # 终极魔法：NumPy RGB 矩阵直接封送为 QImage
        # 注意：必须保持 numpy array 的引用，否则 QImage 可能会崩溃。
        # 我们这里把 rgb_matrix 绑定到 _current_qimage 对象上。
        self._current_qimage = QImage(rgb_matrix.data, width, height, bytes_per_line, QImage.Format_RGB888)
        self._current_qimage.ndarray = rgb_matrix  # 强引用，防 GC

        self.image_label.setPixmap(QPixmap.fromImage(self._current_qimage))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._request_render()

    def wheelEvent(self, event):
        """鼠标滚轮实现平滑缩放 (无限深潜)"""
        # 滚轮向上放大 (0.8)，向下缩小 (1.2)
        zoom_factor = 0.8 if event.angleDelta().y() > 0 else 1.2

        # 获取鼠标在组件上的相对位置
        mouse_pos = event.position()
        px = mouse_pos.x() / self.width()
        py = mouse_pos.y() / self.height()

        # 计算鼠标此时对应的复平面精确坐标
        cx = self.x_min + px * (self.x_max - self.x_min)
        cy = self.y_max - py * (self.y_max - self.y_min)  # 注意 Y 轴方向是反的

        # 缩放整个视口的宽高
        new_w = (self.x_max - self.x_min) * zoom_factor
        new_h = (self.y_max - self.y_min) * zoom_factor

        # 重新推算 x_min, x_max, y_min, y_max，保证鼠标所在的复平面坐标不动
        self.x_min = cx - px * new_w
        self.x_max = self.x_min + new_w

        self.y_max = cy + py * new_h
        self.y_min = self.y_max - new_h

        self._request_render()

    def mousePressEvent(self, event):
        """按住左键准备拖拽"""
        if event.button() == Qt.LeftButton:
            self.last_mouse_pos = event.position()
            self.is_dragging = True

    def mouseMoveEvent(self, event):
        """鼠标拖拽实现丝滑平移"""
        if self.is_dragging:
            current_pos = event.position()
            dx = current_pos.x() - self.last_mouse_pos.x()
            dy = current_pos.y() - self.last_mouse_pos.y()

            # 将屏幕像素位移转换为复平面标量位移
            scale_x = (self.x_max - self.x_min) / self.width()
            scale_y = (self.y_max - self.y_min) / self.height()

            # 注意位移方向，鼠标往右拖 (dx>0)，视口坐标其实是往左移
            self.x_min -= dx * scale_x
            self.x_max -= dx * scale_x
            self.y_min += dy * scale_y
            self.y_max += dy * scale_y

            self.last_mouse_pos = current_pos
            self._request_render()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.is_dragging = False
