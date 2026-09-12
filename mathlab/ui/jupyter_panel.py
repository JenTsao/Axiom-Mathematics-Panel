"""
jupyter_panel.py
────────────────
嵌入式 JupyterLab 交互面板

使用 PySide6.QtWebEngineWidgets.QWebEngineView 将本地 JupyterLab
完整渲染在 Qt 窗口内部，包含：
  - 加载动画（旋转进度指示器）
  - 加载完成后平滑淡入
  - 加载失败时错误提示 + 重试按钮
  - 右键菜单策略设置（允许 Jupyter 内部右键正常工作）
"""

from __future__ import annotations

import socket
import urllib.error
import urllib.parse
import urllib.request

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPropertyAnimation,
    Qt,
    QTimer,
    QUrl,
    Signal,
    Slot,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

try:
    from PySide6.QtWebEngineCore import (
        QWebEnginePage,
        QWebEngineSettings,
    )
    from PySide6.QtWebEngineWidgets import QWebEngineView

    _WEBENGINE_AVAILABLE = True
except ImportError:
    _WEBENGINE_AVAILABLE = False


# ── 加载占位卡片 ─────────────────────────────────────────────────────────────


class _LoadingCard(QFrame):
    """启动期间显示的深色渐变占位卡片"""

    _STYLE = """
        QFrame {
            background: qlineargradient(
                x1:0, y1:0, x2:1, y2:1,
                stop:0 #0D1117,
                stop:1 #161B22
            );
            border-radius: 12px;
        }
        QLabel#title {
            color: #58A6FF;
            font-size: 18px;
            font-weight: 700;
            font-family: 'Segoe UI', 'Inter', sans-serif;
        }
        QLabel#sub {
            color: #8B949E;
            font-size: 13px;
            font-family: 'Segoe UI', 'Inter', sans-serif;
        }
        QPushButton#retry_btn {
            background: #21262D;
            color: #58A6FF;
            border: 1px solid #30363D;
            border-radius: 6px;
            padding: 6px 18px;
            font-size: 13px;
        }
        QPushButton#retry_btn:hover {
            background: #30363D;
            border-color: #58A6FF;
        }
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(self._STYLE)

        root = QVBoxLayout(self)
        root.setAlignment(Qt.AlignCenter)
        root.setSpacing(12)

        self.spinner_lbl = QLabel("◌")
        self.spinner_lbl.setAlignment(Qt.AlignCenter)
        self.spinner_lbl.setStyleSheet("color: #58A6FF; font-size: 36px;")
        root.addWidget(self.spinner_lbl)

        self.title_lbl = QLabel("🌌  正在启动 JupyterLab 内核…")
        self.title_lbl.setObjectName("title")
        self.title_lbl.setAlignment(Qt.AlignCenter)
        root.addWidget(self.title_lbl)

        self.sub_lbl = QLabel("本地微服务已在后台就绪，浏览器引擎正在挂载工作区")
        self.sub_lbl.setObjectName("sub")
        self.sub_lbl.setAlignment(Qt.AlignCenter)
        root.addWidget(self.sub_lbl)

        btn_row = QHBoxLayout()
        btn_row.setAlignment(Qt.AlignCenter)
        self.retry_btn = QPushButton("⟳  重新加载")
        self.retry_btn.setObjectName("retry_btn")
        self.retry_btn.hide()
        btn_row.addWidget(self.retry_btn)
        root.addLayout(btn_row)

        # 旋转动画（用定时器轮换字符模拟）
        self._frames = ["◜", "◝", "◞", "◟", "◌", "●", "◌"]
        self._frame_idx = 0
        self._spin_timer = QTimer(self)
        self._spin_timer.timeout.connect(self._tick)
        self._spin_timer.start(120)

    def _tick(self) -> None:
        self._frame_idx = (self._frame_idx + 1) % len(self._frames)
        self.spinner_lbl.setText(self._frames[self._frame_idx])

    def show_error(self, msg: str = "") -> None:
        self._spin_timer.stop()
        self.spinner_lbl.setText("✕")
        self.spinner_lbl.setStyleSheet("color: #F85149; font-size: 36px;")
        self.title_lbl.setText("❌  Jupyter 页面加载失败")
        self.sub_lbl.setText(msg or "请检查后台进程是否正常启动")
        self.retry_btn.show()

    def show_success_hint(self) -> None:
        self._spin_timer.stop()


# ── 主面板 ───────────────────────────────────────────────────────────────────


class JupyterPanel(QWidget):
    """
    嵌入式 JupyterLab 交互面板

    用法::

        mgr = JupyterManager()
        mgr.start()
        panel = JupyterPanel(mgr.url)
        panel.load_workspace()
    """

    # 后台诊断线程 → 主线程 UI 的信号（跨线程 emit 自动排队到接收者线程）
    _diagnosis_ready = Signal(str)

    def __init__(self, jupyter_url: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.jupyter_url = jupyter_url
        self._diagnosis_ready.connect(self._show_diagnosis)
        self._setup_ui()

    def _show_diagnosis(self, msg: str) -> None:
        """在主线程展示诊断结果（诊断本身在后台线程执行）。"""
        self._card.show_error(msg)

    # ── UI 构建 ──────────────────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        if not _WEBENGINE_AVAILABLE:
            self._show_no_webengine_error(layout)
            return

        # 加载卡片
        self._card = _LoadingCard(self)
        layout.addWidget(self._card)

        # Web 引擎视图
        self._browser = QWebEngineView(self)
        self._browser.hide()
        layout.addWidget(self._browser)

        # 配置 WebEngine 安全策略（允许本地 localhost 的混合内容）
        settings = self._browser.page().settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.AllowRunningInsecureContent, True)

        # 允许 Jupyter 内部右键菜单正常工作
        self._browser.setContextMenuPolicy(Qt.NoContextMenu)

        self._browser.loadFinished.connect(self._on_load_finished)

        # 重试按钮
        self._card.retry_btn.clicked.connect(self._reload)

    def _show_no_webengine_error(self, layout: QVBoxLayout) -> None:
        lbl = QLabel(
            "⚠️  缺少 PySide6-WebEngine 模块\n\n"
            "请运行：\n"
            "  pip install PySide6-WebEngine\n\n"
            "（PySide6 6.x 版本需要单独安装 WebEngine）"
        )
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet("color: #F0B429; font-size: 14px; padding: 40px;" "background: #1A1A2E; border-radius: 8px;")
        layout.addWidget(lbl)

    # ── 公开 API ─────────────────────────────────────────────────────────────

    @Slot()
    def load_workspace(self) -> None:
        """开始加载 JupyterLab 工作区页面。

        标记为 Qt 槽：主窗口在后台启动线程中通过
        QMetaObject.invokeMethod(..., QueuedConnection) 调用本方法，
        普通 Python 方法无法被元对象系统识别，会导致加载永不执行。
        """
        if not _WEBENGINE_AVAILABLE:
            return
        self._browser.load(QUrl(self.jupyter_url))

    def update_url(self, new_url: str) -> None:
        """动态更新目标 URL 并重新加载"""
        self.jupyter_url = new_url
        self.load_workspace()

    # ── 私有回调 ─────────────────────────────────────────────────────────────

    def _on_load_finished(self, success: bool) -> None:
        if success:
            # 🌟 核心：注入自定义 CSS，实现完美视觉融合 🌟
            magic_css = """
            /* 1. 隐藏顶部菜单栏 (File, Edit, View...) */
            #jp-TopPanel { display: none !important; }

            /* 2. 隐藏左侧文件浏览器和侧边栏 */
            #jp-left-stack, .jp-SideBar { display: none !important; }

            /* 3. 隐藏底部状态栏 */
            #jp-bottom-panel { display: none !important; }

            /* 4. 统一全局背景色，完美匹配 Qt 的 #1e1e1e */
            body, .jp-LabShell, .jp-NotebookPanel {
                background-color: #1e1e1e !important;
            }

            /* 5. 调整 Notebook 内部的间距，让它看起来更像原生文本框 */
            .jp-Cell { padding-left: 10px !important; padding-right: 10px !important; }
            .jp-Toolbar { display: none !important; } /* 隐藏 Notebook 自己的小工具栏 */
            """

            # 将 CSS 包装成一段 JavaScript 执行
            js_code = f"""
            var style = document.createElement('style');
            style.type = 'text/css';
            style.innerHTML = `{magic_css}`;
            document.head.appendChild(style);
            """

            # 在 Web 引擎中静默执行
            self._browser.page().runJavaScript(js_code)

            self._card.show_success_hint()
            # 淡入 browser，淡出 card
            self._card.hide()
            self._browser.show()
        else:
            # 判断是否真的失败（Jupyter 有时会重定向到 /lab/tree，仍属成功）
            current_url = self._browser.url().toString()
            if "localhost" in current_url and "/lab" in current_url:
                self._card.hide()
                self._browser.show()
            else:
                # 诊断包含 socket/HTTP 探测（最坏阻塞约 5 秒），必须放到后台线程，
                # 否则 WebEngine 加载失败时整个主界面会冻结。
                self._card.show_error("正在诊断失败原因…")
                import threading

                def _diagnose_worker():
                    msg = self._diagnose_failure()
                    self._diagnosis_ready.emit(msg)

                threading.Thread(target=_diagnose_worker, daemon=True, name="JupyterDiagnose").start()

    def _diagnose_failure(self) -> str:
        """诊断加载失败的原因，返回详细的错误描述"""
        # 解析端口号
        port = None
        try:
            from urllib.parse import urlparse

            parsed = urlparse(self.jupyter_url)
            port = parsed.port
        except Exception:
            pass

        if port is None:
            return f"无法解析目标 URL\n目标：{self.jupyter_url}"

        # 检查 1: 端口是否在监听
        port_open = False
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(2)
                port_open = s.connect_ex(("127.0.0.1", port)) == 0
        except Exception:
            pass

        if not port_open:
            return (
                f"端口 {port} 未监听，JupyterLab 服务器可能未成功启动\n"
                f"目标：{self.jupyter_url}\n\n"
                f"建议：\n"
                f"  1. 检查 jupyterlab 是否已安装 (pip install jupyterlab)\n"
                f"  2. 查看日志是否有启动错误\n"
                f"  3. 点击重新加载按钮重试"
            )

        # 检查 2: HTTP 是否可访问
        api_url = f"http://127.0.0.1:{port}/api/status"

        # 安全检查：验证 URL 协议和主机
        parsed_url = urllib.parse.urlparse(api_url)
        if parsed_url.scheme not in ("http", "https") or parsed_url.hostname not in (
            "localhost",
            "127.0.0.1",
        ):
            return f"不允许的 URL 访问: {api_url}"

        try:
            req = urllib.request.Request(api_url)
            with urllib.request.urlopen(req, timeout=3) as resp:  # nosec B310 - 已验证仅访问本地地址
                if resp.status == 200:
                    return (
                        f"服务器 HTTP 正常，但页面加载失败\n"
                        f"目标：{self.jupyter_url}\n"
                        f"这可能是 WebEngine 兼容性问题"
                    )
        except urllib.error.HTTPError as e:
            return f"服务器返回 HTTP {e.code}\n" f"目标：{self.jupyter_url}"
        except Exception:
            pass

        return f"页面响应异常\n目标：{self.jupyter_url}"

    def _reload(self) -> None:
        """重试加载"""
        self._card.setVisible(True)
        self._card.spinner_lbl.setText("◌")
        self._card.spinner_lbl.setStyleSheet("color: #58A6FF; font-size: 36px;")
        self._card.title_lbl.setText("🌌  正在重新连接 JupyterLab…")
        self._card.retry_btn.hide()
        self._card._spin_timer.start(120)
        self._browser.hide()
        self.load_workspace()
