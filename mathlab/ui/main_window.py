from PySide6.QtCore import QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QMainWindow

from mathlab.core.ai_manager import AIManager
from mathlab.core.algo_animator import AlgoAnimator
from mathlab.core.async_workers import (
    AIClusterWorker,
    AIFitWorker,
    AIGeneratePointsWorker,
    AIRecognizeWorker,
    TaskManager,
)
from mathlab.core.cas_provider import CASProvider
from mathlab.core.command_manager import Command, CommandManager
from mathlab.core.error_manager import AutoSaver
from mathlab.core.extension_api import MathLabAPI

# ── 核心引擎导入（统一使用绝对导入） ──────────────────────────────────────
from mathlab.core.geometry_engine import GeometryEngine
from mathlab.core.ipc_client import JupyterIPCClient
from mathlab.core.ipc_server import JupyterIPCServer
from mathlab.core.plugin_manager import PluginManager
from mathlab.core.python_repl import PythonREPL
from mathlab.core.sandbox import SandboxManager
from mathlab.data.project import ProjectManager
from mathlab.ui.omni_bar import OmniBar

# ── JupyterLab 嵌入组件（软依赖：WebEngine 不存在时降级为占位面板） ──────────
try:
    from mathlab.core.jupyter_manager import JupyterManager
    from mathlab.ui.jupyter_panel import JupyterPanel
except ImportError:
    JupyterPanel = None
    JupyterManager = None

try:
    from mathlab.ui.preferences_dialog import PreferencesDialog
except ImportError:
    PreferencesDialog = None

from mathlab.utils.i18n_manager import get_i18n, t
from mathlab.utils.logger import get_logger
from mathlab.utils.theme_manager import get_current_theme

logger = get_logger(__name__)


from mathlab.ui._mixin_ai import AIMixin
from mathlab.ui._mixin_commands import CommandsMixin
from mathlab.ui._mixin_dialogs import DialogsMixin
from mathlab.ui._mixin_file_io import FileIOMixin
from mathlab.ui._mixin_menus import MenusMixin
from mathlab.ui._mixin_signals import SignalsMixin
from mathlab.ui._mixin_ui_setup import UISetupMixin


class MainWindow(
    UISetupMixin,
    MenusMixin,
    SignalsMixin,
    CommandsMixin,
    AIMixin,
    FileIOMixin,
    DialogsMixin,
    QMainWindow,
):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(t("main_window.title"))
        self.setGeometry(100, 100, 1200, 800)

        self._objects_data: dict = {}
        self.current_function_id = None

        # ── 核心引擎初始化（唯一实例化点，消除双重初始化） ───────────────
        self._init_engines()

        # 命令管理器（必须在 setup_ui 前创建，供各面板注册命令）
        self.cmd_manager = CommandManager()

        # ── IPC 通信（端口可配置化） ────────────────────────────────────
        from mathlab.utils.config_manager import get_config

        ipc_config = get_config("ipc", {})
        ipc_server_port = ipc_config.get("server_port", 45678)
        ipc_client_port = ipc_config.get("client_port", 45679)

        self.ipc_server = JupyterIPCServer(port=ipc_server_port, parent=self)
        self.ipc_server.command_received.connect(self.handle_kernel_command)
        self.ipc_server.start()

        self.ipc_client = JupyterIPCClient(port=ipc_client_port)

        self.setup_ui()

        # 将客户端挂载到画板上，供画板使用
        self.central_widget.ipc_client = self.ipc_client
        self.setup_menus()
        self.setup_toolbar()
        self.setup_docks()

        self.load_stylesheet()

        self.current_project = None

        self.active_workers = set()
        self.fit_worker = None
        self.cluster_worker = None
        self.recognize_worker = None
        self.generate_points_worker = None

        self.connect_signals()
        self._register_commands()

        get_i18n().add_language_change_listener(self._on_language_changed)
        self.apply_theme(get_current_theme())

        # 初始化自动存档与恢复
        self.autosaver = AutoSaver(self)
        self.autosaver.check_and_recover()

        # 挂载画板追踪器
        from mathlab.core.canvas_tracker import CanvasShadowTracker

        self.canvas_tracker = CanvasShadowTracker(self.geometry_engine)

        # 实例化 Omni-Bar，保证生命周期绑定
        self.omni_bar = OmniBar(self)

        # 注册全局快捷键 (Ctrl+K 或 Cmd+K)
        self.shortcut_summon = QShortcut(QKeySequence("Ctrl+K"), self)
        self.shortcut_summon.activated.connect(self.toggle_omni_bar)

        # ── 延迟初始化：窗口显示后再加载非关键模块 ─────────────────────
        # 使用 QTimer.singleShot(0) 确保窗口先绘制完成，再执行重型初始化
        # （AI 集成、ECharts 绑定、插件系统、REPL 命名空间注入）
        QTimer.singleShot(0, self._deferred_init)

    def _deferred_init(self):
        """窗口显示后执行的非关键初始化（不阻塞首屏渲染）。"""
        try:
            # 启动 AI 全局交互集成
            self._setup_ai_integration()

            # 启动 ECharts 集成
            self._setup_echarts_integration()

            # ── 后置初始化（REPL 命名空间、事件监听、插件系统） ─────────────
            self._init_post_setup()
        except Exception as e:
            logger.error("延迟初始化失败: %s", e, exc_info=True)

    def _init_engines(self):
        """创建所有核心引擎实例（唯一的引擎初始化入口）。"""
        self.geometry_engine = GeometryEngine()
        self.cas_provider = CASProvider()
        self.geometry_engine.set_cas_provider(self.cas_provider)
        self.python_repl = PythonREPL()
        self.ai_manager = AIManager()
        self.algo_animator = AlgoAnimator()
        self.project_manager = ProjectManager()
        self.sandbox_manager = SandboxManager()

        # 将 ai_manager 注入给代码编辑器
        from mathlab.ui.code_editor import AutocompleteTextEdit

        self.code_editor = AutocompleteTextEdit(ai_manager=self.ai_manager)

    def _init_post_setup(self):
        """后置初始化：REPL 命名空间注入、事件监听注册、插件系统启动。"""
        # ── 注入 Python REPL 快捷命令命名空间 ───────────────────────────
        self.python_repl.update_namespace(
            {
                "draw_point": lambda x, y: self.geometry_engine.add_point(x, y),
                "draw_segment": lambda p1, p2: self.geometry_engine.add_segment(p1, p2),
                "draw_circle": lambda center, radius: self.geometry_engine.add_circle(center, radius),
                "clear_canvas": lambda: self.geometry_engine.objects.clear(),
                "draw_ellipse": lambda center_id, a=2.0, b=1.0: self.geometry_engine.add_ellipse(center_id, a, b),
                "draw_hyperbola": lambda center_id, a=1.0, b=1.0: self.geometry_engine.add_hyperbola(center_id, a, b),
                "draw_parabola": lambda vertex_id, p=1.0, direction="up": self.geometry_engine.add_parabola(
                    vertex_id, p, direction
                ),
                "draw_conic": lambda A=1, B=0, C=1, D=0, E=0, F=-1: self.geometry_engine.add_conic_section(
                    A, B, C, D, E, F
                ),
                "plot_function": lambda expr, x_range=(
                    -10,
                    10,
                ): self.geometry_engine.add_function_plot(expr, x_range),
                "plot_implicit": lambda expr, x_range=(-10, 10), y_range=(
                    -10,
                    10,
                ): self.geometry_engine.add_implicit_plot(expr, x_range, y_range),
                "plot_polar": lambda expr, theta_range=(
                    0,
                    6.28318,
                ): self.geometry_engine.add_polar_plot(expr, theta_range),
                "create_locus": lambda tracer_id, driver_id: self.geometry_engine.add_locus(tracer_id, driver_id),
                "update_locus": lambda locus_id: self.geometry_engine.update_locus(locus_id),
                "solve": self.cas_provider.solve_equation,
                "simplify": self.cas_provider.simplify,
                "integrate": self.cas_provider.integrate,
                "differentiate": self.cas_provider.differentiate,
                "limit": self.cas_provider.limit,
                "app": self,
            }
        )

        # ── 几何引擎事件监听 ─────────────────────────────────────────────
        # 注：事件监听已在 connect_signals() 中通过 self.on_geometry_event 注册，
        # 此处不再重复注册等价监听器，否则每次事件都会触发两遍 UI 更新。

        # ── 算法动画回调 ─────────────────────────────────────────────────
        def on_algorithm_step(state):
            if hasattr(self, "algo_vis_panel"):
                self.algo_vis_panel.update_visualization(state)

        self.algo_animator.step_ready = on_algorithm_step

        # ── 初始化插件系统 ───────────────────────────────────────────────
        self.mathlab_api = MathLabAPI(self, self.cmd_manager, self.console)
        self.plugin_manager = PluginManager(self.mathlab_api)
        self.plugin_manager.load_all_plugins()

    def toggle_omni_bar(self):
        if self.omni_bar.isVisible() and self.omni_bar.windowOpacity() > 0:
            self.omni_bar.dismiss()
        else:
            # 传入当前主窗口的几何数据，用于 Omni-Bar 计算居中位置
            self.omni_bar.summon(self.geometry())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "omni_bar") and self.omni_bar.isVisible():
            self.omni_bar.dismiss()

    def closeEvent(self, event):
        """在窗口关闭时卸载所有插件，释放资源"""
        if hasattr(self, "autosaver"):
            self.autosaver.clean_up()

        if hasattr(self, "plugin_manager"):
            try:
                self.plugin_manager.unload_all()
            except Exception as e:
                print(f"Error unloading plugins on close: {e}")
        # 清理所有活动的异步任务
        # 注：AI Worker 均为 QRunnable（无 quit()/wait()），统一交由全局线程池等待结束
        from PySide6.QtCore import QThreadPool

        try:
            QThreadPool.globalInstance().waitForDone(2000)
        except Exception:
            pass
        self.active_workers.clear()

        if hasattr(self, "ipc_server") and self.ipc_server is not None:
            self.ipc_server.stop()

        # 🛑 优雅关闭 JupyterLab 后台进程
        if hasattr(self, "jupyter_mgr") and self.jupyter_mgr is not None:
            try:
                self.jupyter_mgr.stop()
            except Exception as e:
                logger.warning("关闭 JupyterLab 后台时出错：%s", e)

        # 🛑 关闭 JupyterSandbox 内核进程，防止资源泄漏
        try:
            from mathlab.core.jupyter_manager import shutdown_jupyter_sandbox

            shutdown_jupyter_sandbox()
        except Exception as e:
            logger.warning("关闭 JupyterSandbox 时出错：%s", e)

        super().closeEvent(event)
