# mathlab/plugins/plugin_3d_viewer/main.py
import json
import os

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView

from mathlab.core.cs_mesh_engine import cs_mesh_3d
from mathlab.core.plugin_base import MathLabPlugin
from mathlab.utils.i18n_manager import t

from .bridge import ThreeJSBridge


class ThreeJSViewerPlugin(MathLabPlugin):
    name = "3D Geometry Viewer"
    version = "2.0.0"
    author = "MathLab Team"
    description = "原生支持 MathLab 3D 拓扑约束的动态空间几何画板。"

    def on_activate(self, api):
        self.api = api
        self.web_view = QWebEngineView()

        self.channel = QWebChannel()
        self.bridge = ThreeJSBridge(api)
        self.channel.registerObject("py_bridge", self.bridge)
        self.web_view.page().setWebChannel(self.channel)

        html_path = os.path.join(os.path.dirname(__file__), "web", "index.html")
        self.web_view.load(QUrl.fromLocalFile(html_path))

        # 核心：将 3D 面板挂载到主窗口
        self.dock = api.add_sidebar_panel(t("plugins.3d_viewer"), self.web_view)

        # 核心：监听底层几何引擎的拓扑变化！
        # 先移除旧的同名监听再注册，保证重复激活时不会累积回调
        if hasattr(self.api, "geometry_engine"):
            engine = self.api.geometry_engine
            engine.remove_listener(self.on_geometry_event)
            engine.add_listener(self.on_geometry_event)

        # =================================================================
        # 高性能 3D 动态波纹驱动 (C# + WebGL)
        # =================================================================
        self.time_elapsed = 0.0

        # 每秒刷新 60 次的超高清定时器
        self.render_timer = QTimer()
        self.render_timer.timeout.connect(self._render_frame)
        self.render_timer.start(16)  # ~60 FPS

    def _render_frame(self):
        self.time_elapsed += 0.05

        if not hasattr(cs_mesh_3d, "_engine") or cs_mesh_3d._engine is None:
            return

        # 1. 呼叫 C# 暴力计算 150x150 密度的波纹曲面网格点 (共产生 405,000 个浮点数)
        # 这在纯 Python 下要跑死，但 C# 只需要 1ms！
        flat_vertices = cs_mesh_3d.get_ripple_mesh_data(
            x_range=(-10, 10),
            y_range=(-10, 10),
            x_seg=150,
            y_seg=150,
            time_val=self.time_elapsed,
            freq=1.5,
        )

        # 2. 将数据作为参数直接打入 WebGL 页面中执行
        # 利用 QWebEngineView 的 runJavaScript 瞬间传过跨界通道
        js_cmd = f"updateSurfaceGeometry({flat_vertices});"
        self.web_view.page().runJavaScript(js_cmd)

    def on_geometry_event(self, event_type, data):
        """当引擎中添加、移动或删除物体时，立即同步给 Three.js"""
        # 如果是 JS 本身发起的拖拽更新，则不要再推回去（防止无限踢皮球）
        if hasattr(self, "bridge") and getattr(self.bridge, "_is_syncing_from_js", False):
            return

        # 无论发生什么事件，直接把整棵依赖树的所有坐标打包发给前端
        self.sync_scene()

    def sync_scene(self):
        """序列化当前 GeometryEngine 中的所有对象，推送到 JS"""
        if not hasattr(self.api, "geometry_engine"):
            return

        objects = self.api.geometry_engine.get_all_objects()
        payload = [obj.serialize() for obj in objects]

        # 将 JSON 转为字符串并转义，防止 JS 解析报错
        json_str = json.dumps(payload).replace("\\", "\\\\").replace("'", "\\'")
        js_code = f"if (window.updateScene) window.updateScene('{json_str}');"

        self.web_view.page().runJavaScript(js_code)

    def on_deactivate(self):
        # 停止 60FPS 渲染定时器，避免插件卸载后仍持续消耗 CPU 与 WebEngine 渲染资源
        if getattr(self, "render_timer", None) is not None:
            self.render_timer.stop()
            self.render_timer = None

        # 移除几何引擎事件监听，避免悬垂回调与内存泄漏
        if hasattr(self, "api") and hasattr(self.api, "geometry_engine"):
            try:
                self.api.geometry_engine.remove_listener(self.on_geometry_event)
            except Exception:
                pass

        # 释放 WebEngine 视图资源
        if getattr(self, "web_view", None) is not None:
            try:
                self.web_view.setParent(None)
                self.web_view.deleteLater()
            except Exception:
                pass
            self.web_view = None

        if getattr(self, "dock", None) is not None:
            self.dock.close()
            self.dock = None
