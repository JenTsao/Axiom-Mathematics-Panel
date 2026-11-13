import os

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QVBoxLayout, QWidget

from mathlab.utils.i18n_manager import t


class FractalGPUExplorer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("errors.fractal_gpu_title"))
        self.resize(1000, 800)

        # 视口状态管理
        self.offset_x = -0.5
        self.offset_y = 0.0
        self.zoom = 3.0
        self.max_iter = 256
        self.is_julia = 0
        self.c_julia = [0.285, 0.01]  # 一个经典的 Julia 种子

        # 鼠标拖拽状态
        self.last_mouse_pos = None

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.web_view = QWebEngineView()

        # 加载刚才写的 GPU html 文件
        html_path = os.path.abspath(
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "plugins",
                "plugin_3d_viewer",
                "web",
                "fractal_gpu.html",
            )
        )
        self.web_view.setUrl(QUrl.fromLocalFile(html_path))

        layout.addWidget(self.web_view)

    def _send_state_to_gpu(self):
        """将当前摄像机视角光速推给 GPU 着色器"""
        js_code = f"""
            if (window.updateFractal) {{
                window.updateFractal({{
                    offsetX: {self.offset_x},
                    offsetY: {self.offset_y},
                    zoom: {self.zoom},
                    maxIter: {self.max_iter},
                    isJulia: {self.is_julia},
                    cJuliaX: {self.c_julia[0]},
                    cJuliaY: {self.c_julia[1]}
                }});
            }}
        """
        self.web_view.page().runJavaScript(js_code)

    # ---------------- 鼠标交互：接管浏览器的事件 ----------------
    # (注意：为了让 PySide6 接管事件，有时需要在网页端 disable 默认的鼠标行为，
    # 或者直接在网页前端写 JS 交互逻辑并通过 QWebChannel 传回。
    # 这里演示的是后端拦截事件的逻辑思想。)

    def wheelEvent(self, event):
        """鼠标滚轮：光速缩放"""
        zoom_factor = 0.85 if event.angleDelta().y() > 0 else 1.15

        # 复杂的数学：确保缩放是向着鼠标指针的位置进行的
        # (简化版：直接对中心缩放)
        self.zoom *= zoom_factor

        # 当缩放越深，需要的迭代次数越多，才能看清细节
        if self.zoom < 0.1:
            self.max_iter = 512
        if self.zoom < 0.001:
            self.max_iter = 1024
        if self.zoom < 0.00001:
            self.max_iter = 2048

        self._send_state_to_gpu()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.last_mouse_pos = event.position().toPoint()

    def mouseMoveEvent(self, event):
        """鼠标拖拽：平移视口"""
        if self.last_mouse_pos is not None:
            current_pos = event.position().toPoint()
            dx = current_pos.x() - self.last_mouse_pos.x()
            dy = current_pos.y() - self.last_mouse_pos.y()

            # 将屏幕像素位移换算为复平面位移
            # (注意 Y 轴的翻转)
            self.offset_x -= (dx / self.width()) * self.zoom
            self.offset_y += (dy / self.height()) * self.zoom * (self.height() / self.width())

            self.last_mouse_pos = current_pos
            self._send_state_to_gpu()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.last_mouse_pos = None

    def keyPressEvent(self, event):
        """按空格键在 Mandelbrot 和 Julia 之间切换"""
        if event.key() == Qt.Key.Key_Space:
            self.is_julia = 1 - self.is_julia
            # 重置视角
            self.offset_x, self.offset_y = 0.0, 0.0
            self.zoom = 3.0
            self._send_state_to_gpu()
