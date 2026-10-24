import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from mathlab.core.async_workers import TaskManager
from mathlab.core.cs_complex_engine import get_cs_complex


class FractalExplorer(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("双生分形引擎 (C# 加速)")
        layout = QHBoxLayout(self)

        # 图像分辨率设定 (为了 60fps 实时性，Julia 面板分辨率可以先设低一点，比如 400x400)
        self.img_w, self.img_h = 400, 400

        # 左侧：Mandelbrot 面板
        self.label_mandel = QLabel()
        self.label_mandel.setFixedSize(self.img_w, self.img_h)
        self.label_mandel.setMouseTracking(True)  # 开启鼠标追踪

        # 右侧：Julia 面板
        self.label_julia = QLabel()
        self.label_julia.setFixedSize(self.img_w, self.img_h)

        layout.addWidget(self.label_mandel)
        layout.addWidget(self.label_julia)

        # Mandelbrot 的复平面视口范围
        self.m_xmin, self.m_xmax = -2.0, 1.0
        self.m_ymin, self.m_ymax = -1.5, 1.5

        # 使用 TaskManager 保持 60fps 极限丝滑且不阻塞主线程
        self.task_manager = TaskManager()

        # 保存 QImage 强引用防止崩溃
        self._qimages = {}

        # 初始化渲染左侧的 Mandelbrot
        self._render_mandelbrot()

        # 节流控制
        self._last_mouse_time = 0

        # 绑定鼠标移动事件
        self.label_mandel.mouseMoveEvent = self.on_mandel_mouse_move

    def _render_mandelbrot(self):
        # 静态 Mandelbrot，直接同步渲染即可，只执行一次
        engine = get_cs_complex()
        if engine is None:
            return
        rgb_matrix = engine.generate_smooth_mandelbrot(
            self.m_xmin, self.m_xmax, self.m_ymin, self.m_ymax, self.img_w, self.img_h
        )
        self._update_label_from_numpy(self.label_mandel, rgb_matrix, "mandel")

    def on_mandel_mouse_move(self, event):
        """捕获鼠标，实时计算 Julia"""
        import time

        current_time = time.time()
        # [BUG修复] 增加 16ms 节流(约 60FPS)，防止事件洪水导致主线程卡顿
        if current_time - self._last_mouse_time < 0.016:
            return
        self._last_mouse_time = current_time

        # 1. 获取鼠标在像素控件上的位置
        px = event.position().x()
        py = event.position().y()

        # 2. 将屏幕像素坐标映射回复平面坐标 C (注意 Y 轴翻转)
        c_real = self.m_xmin + (px / self.img_w) * (self.m_xmax - self.m_xmin)
        c_imag = self.m_ymax - (py / self.img_h) * (self.m_ymax - self.m_ymin)

        # 3. 呼叫底层极速渲染 Julia 集合 (实时！使用后台线程以保证绝对不掉帧)
        self.task_manager.submit(
            fn=self._render_julia_task,
            c_real=c_real,
            c_imag=c_imag,
            on_success=self._on_julia_success,
            group_id="julia_render",
        )

    def _render_julia_task(self, c_real, c_imag):
        engine = get_cs_complex()
        if engine is None:
            raise RuntimeError("C# 分形引擎不可用（pythonnet / .NET 缺失）")
        julia_matrix = engine.generate_julia_image(
            -2.0,
            2.0,
            -2.0,
            2.0,  # Julia 通常在 -2 到 2 之间
            self.img_w,
            self.img_h,
            c_real,
            c_imag,
        )
        return julia_matrix

    def _on_julia_success(self, julia_matrix):
        self._update_label_from_numpy(self.label_julia, julia_matrix, "julia")

    def _update_label_from_numpy(self, label, rgb_matrix, key):
        """共用的 numpy 转 QPixmap 工具"""
        height, width, _ = rgb_matrix.shape
        bytes_per_line = 3 * width

        # 保持引用防止崩溃
        q_img = QImage(rgb_matrix.data, width, height, bytes_per_line, QImage.Format_RGB888)
        q_img.ndarray = rgb_matrix
        self._qimages[key] = q_img

        label.setPixmap(QPixmap.fromImage(q_img))
