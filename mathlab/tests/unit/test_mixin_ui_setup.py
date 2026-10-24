"""Tests for UISetupMixin — UI 布局组装与 Dock 面板管理（此前 0% 覆盖）。

覆盖 ``mathlab/ui/_mixin_ui_setup.py``：
- ``setup_docks``：7 个静态 Dock 的 objectName / 停靠区 / Tab 合并 / 默认显隐 /
  标题本地化 / REPL 注入 / 控制台信号接线 / 命令面板快捷键；
- ``setup_ui``：中央 Tab 顺序契约（R-08 冷启动落画板）、Jupyter 标签页装配与优雅跳过；
- ``add_dynamic_panel``：插件动态面板注册约定（objectName / 停靠区 / Tab 合并）；
- ``toggle_*``：面板显隐切换（淡出动画结束后真正隐藏）；
- ``_refresh_notebook_ui``：Notebook 清空并重建单个 CODE Cell。

约定（AGENTS.md §7）：全部为 ``qt`` 标记用例；``qtbot.addWidget`` 管理生命周期；
``qtbot.waitUntil`` 等待动画，禁 ``time.sleep``，禁构造第二个 QApplication。
重型面板（WebEngine / Jupyter / Octave）以桩替身隔离，另留真实面板构造冒烟用例。
"""

import types

import pytest
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QShortcut
from PySide6.QtWidgets import QDockWidget, QMainWindow, QVBoxLayout, QWidget

from mathlab.ui._mixin_ui_setup import UISetupMixin

# 7 个静态 Dock 的 objectName → 停靠区契约（§5.3 / R-14 / R-15）
EXPECTED_DOCKS = {
    "dockAlgebra": Qt.DockWidgetArea.LeftDockWidgetArea,
    "dockProperties": Qt.DockWidgetArea.RightDockWidgetArea,
    "dockConsole": Qt.DockWidgetArea.BottomDockWidgetArea,
    "dockMathConsole": Qt.DockWidgetArea.BottomDockWidgetArea,
    "dockFunctionExplorer": Qt.DockWidgetArea.LeftDockWidgetArea,
    "dockAlgoVis": Qt.DockWidgetArea.RightDockWidgetArea,
    "dockAITools": Qt.DockWidgetArea.RightDockWidgetArea,
}


# ── 桩替身 ────────────────────────────────────────────────────────────────


class _StubDock(QDockWidget):
    """轻量 Dock 桩：记录 set_python_repl 注入，供 mixin 装配逻辑测试复用。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.repl = None

    def set_python_repl(self, repl):
        self.repl = repl


class _StubBridgeSignals(QObject):
    plot_requested = Signal(dict)


class _StubMathConsole(_StubDock):
    """带 bridge.signals 的数学控制台桩（setup_docks 会向 plot_requested 接线）。

    注意：与其余 6 个 Dock 不同，math_console 的窗口标题由面板自身 __init__
    设置（mixin 不代劳），桩需复刻该行为以保持"标题全部走 i18n"的契约断言有效。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        from mathlab.utils.i18n_manager import t

        self.setWindowTitle(t("math_console.title"))
        self.bridge = types.SimpleNamespace(signals=_StubBridgeSignals())


class _TestWindow(QMainWindow, UISetupMixin):
    """最小主窗口：QMainWindow + UISetupMixin + mixin 依赖的宿主属性与槽。"""

    def __init__(self):
        super().__init__()
        from mathlab.core.python_repl import PythonREPL

        self.python_repl = PythonREPL()
        self.cmd_manager = types.SimpleNamespace()  # CommandPalette 仅持有引用
        self.ipc_client = None
        self.plot_calls = []
        self.explain_calls = []
        self.palette_shown = 0

    def handle_ai_explain(self, *args, **kwargs):
        self.explain_calls.append((args, kwargs))

    def handle_console_plot(self, payload):
        self.plot_calls.append(payload)

    def _show_command_palette(self):
        self.palette_shown += 1


class _FakeJupyterManager:
    """假 JupyterManager：记录 start() 调用并返回失败（走主线程错误提示分支）。"""

    _default_timeout = 1

    def __init__(self):
        self.url = "http://127.0.0.1:8899"
        self.port = 8899
        self.started = False

    def start(self, timeout=None):
        self.started = True
        return False


class _FakeJupyterPanel(QWidget):
    def __init__(self, url, parent=None):
        super().__init__(parent)
        self.url = url


class _FakeNotebook:
    """假 Notebook：真实 QLayout + 记录 add_new_cell 调用。"""

    def __init__(self):
        self.canvas_layout = QVBoxLayout()
        self.canvas_layout.addWidget(QWidget())
        self.canvas_layout.addWidget(QWidget())
        self.canvas_layout.addStretch()
        self.ui_cells = ["cell-a", "cell-b"]
        self.added = []

    def add_new_cell(self, cell_type):
        self.added.append(cell_type)


def _patch_stub_panels(monkeypatch):
    """把 _mixin_ui_setup 的 7 个面板类替换为桩，聚焦 mixin 装配逻辑。"""
    import mathlab.ui._mixin_ui_setup as mod

    for name, stub in {
        "AlgebraPanel": _StubDock,
        "PropertiesPanel": _StubDock,
        "PythonConsole": _StubDock,
        "MathConsole": _StubMathConsole,
        "FunctionExplorerPanel": _StubDock,
        "AlgoVisPanel": _StubDock,
        "AIToolsPanel": _StubDock,
    }.items():
        monkeypatch.setattr(mod, name, stub)


def _patch_no_jupyter(monkeypatch):
    import mathlab.ui._mixin_ui_setup as mod

    monkeypatch.setattr(mod, "JupyterManager", None)
    monkeypatch.setattr(mod, "JupyterPanel", None)


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def host(qtbot):
    """最小主窗口（未组装 Dock）。"""
    win = _TestWindow()
    qtbot.addWidget(win)
    return win


@pytest.fixture
def docked(host, monkeypatch):
    """组装全部静态 Dock（面板为桩）。"""
    _patch_stub_panels(monkeypatch)
    host.setup_docks()
    return host


# ── setup_docks ───────────────────────────────────────────────────────────


@pytest.mark.qt
def test_setup_docks_creates_all_static_docks(docked):
    names = {d.objectName() for d in docked.findChildren(QDockWidget)}
    assert names == set(EXPECTED_DOCKS), f"Dock 集合不符契约: {names}"


@pytest.mark.qt
def test_dock_areas_match_layout_contract(docked):
    for name, area in EXPECTED_DOCKS.items():
        dock = docked.findChild(QDockWidget, name)
        assert dock is not None, f"缺少 Dock: {name}"
        assert docked.dockWidgetArea(dock) == area, f"{name} 停靠区错误"


@pytest.mark.qt
def test_bottom_and_right_dock_tab_pairs(docked):
    assert docked.math_console in docked.tabifiedDockWidgets(docked.console)
    assert docked.ai_tools_panel in docked.tabifiedDockWidgets(docked.algo_vis_panel)


@pytest.mark.qt
def test_function_explorer_hidden_by_default(docked):
    """函数探索器默认隐藏（§5.3），其余 6 个默认可见。"""
    assert docked.function_explorer.isHidden()
    for name in EXPECTED_DOCKS:
        if name == "dockFunctionExplorer":
            continue
        assert not docked.findChild(QDockWidget, name).isHidden(), f"{name} 应默认可见"


@pytest.mark.qt
def test_dock_titles_localized(docked):
    from mathlab.utils.i18n_manager import t

    title_keys = {
        "dockAlgebra": "algebra_panel.title",
        "dockProperties": "properties_panel.title",
        "dockConsole": "console.title",
        "dockMathConsole": "math_console.title",
        "dockFunctionExplorer": "function_explorer.title",
        "dockAlgoVis": "algo_vis.title",
        "dockAITools": "ai_tools.title",
    }
    for name, key in title_keys.items():
        assert docked.findChild(QDockWidget, name).windowTitle() == t(key), f"{name} 标题未走 i18n"


@pytest.mark.qt
def test_console_receives_host_python_repl(docked):
    assert docked.console.repl is docked.python_repl


@pytest.mark.qt
def test_math_console_plot_signal_wired_to_host(docked):
    """math_console.bridge.signals.plot_requested 必须接到 host.handle_console_plot。"""
    payload = {"x": [0, 1], "y": [0, 1], "type": "line", "title": "t"}
    docked.math_console.bridge.signals.plot_requested.emit(payload)
    assert docked.plot_calls == [payload]


@pytest.mark.qt
def test_command_palette_and_shortcuts_registered(docked):
    from mathlab.ui.command_bar import CommandPalette

    assert isinstance(docked.cmd_palette, CommandPalette)
    sequences = {s.key().toString() for s in docked.findChildren(QShortcut)}
    assert "Ctrl+Shift+P" in sequences
    assert "Ctrl+P" in sequences


# ── setup_ui ──────────────────────────────────────────────────────────────


@pytest.mark.qt
def test_setup_ui_tab_order_canvas_first(host, monkeypatch):
    """R-08：Tab 序为 画板 → Notebook，冷启动落在几何画板。"""
    from mathlab.ui.canvas import GeometryCanvas

    _patch_no_jupyter(monkeypatch)
    host.setup_ui()

    assert host.central_tabs.objectName() == "central_tabs"
    assert host.centralWidget() is host.central_tabs
    assert host.central_tabs.widget(0) is host.central_widget
    assert isinstance(host.central_widget, GeometryCanvas)
    assert host.central_tabs.widget(1) is host.notebook


@pytest.mark.qt
def test_setup_ui_adds_jupyter_tab(host, monkeypatch):
    """Jupyter 可用时：装配标签页并派发后台启动线程（假 manager 不起真实服务）。"""
    import mathlab.ui._mixin_ui_setup as mod

    monkeypatch.setattr(mod, "JupyterManager", _FakeJupyterManager)
    monkeypatch.setattr(mod, "JupyterPanel", _FakeJupyterPanel)
    host.setup_ui()

    assert isinstance(host.jupyter_mgr, _FakeJupyterManager)
    assert isinstance(host.jupyter_workspace, _FakeJupyterPanel)
    assert host.jupyter_workspace.url == "http://127.0.0.1:8899"
    titles = [host.central_tabs.tabText(i) for i in range(host.central_tabs.count())]
    assert any("Jupyter" in title for title in titles)


@pytest.mark.qt
def test_setup_ui_skips_jupyter_when_unavailable(host, monkeypatch):
    """Jupyter 导入失败时：无标签页、无管理器、其余功能不受影响。"""
    _patch_no_jupyter(monkeypatch)
    host.setup_ui()

    assert host.jupyter_mgr is None
    assert host.jupyter_workspace is None
    titles = [host.central_tabs.tabText(i) for i in range(host.central_tabs.count())]
    assert not any("Jupyter" in title for title in titles)
    assert host.central_tabs.count() >= 2


# ── add_dynamic_panel ─────────────────────────────────────────────────────


@pytest.mark.qt
def test_add_dynamic_panel_without_ai_tools(host):
    widget = QWidget()
    dock = host.add_dynamic_panel("demo", widget)

    assert dock.objectName() == "dock_dynamic_demo"
    assert dock.widget() is widget
    assert host.dockWidgetArea(dock) == Qt.DockWidgetArea.RightDockWidgetArea
    assert not dock.isHidden()


@pytest.mark.qt
def test_add_dynamic_panel_tabifies_with_ai_tools(host):
    ai_dock = QDockWidget("AI", host)
    host.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, ai_dock)
    host.ai_tools_panel = ai_dock

    dock = host.add_dynamic_panel("demo", QWidget())
    assert dock in host.tabifiedDockWidgets(ai_dock)


# ── toggle_* ──────────────────────────────────────────────────────────────

_TOGGLE_TARGETS = [
    ("algebra_panel", "toggle_algebra_panel"),
    ("properties_panel", "toggle_properties_panel"),
    ("console", "toggle_console"),
    ("algo_vis_panel", "toggle_algo_vis_panel"),
    ("ai_tools_panel", "toggle_ai_tools_panel"),
    ("function_explorer", "toggle_function_explorer"),
    ("math_console", "toggle_math_console"),
]


@pytest.mark.qt
@pytest.mark.parametrize("attr,method", _TOGGLE_TARGETS)
def test_toggle_methods_show_then_hide(docked, qtbot, attr, method):
    """显隐切换：show 分支立即可见；hide 分支淡出动画结束后真正隐藏。"""
    panel = getattr(docked, attr)
    if attr == "function_explorer":
        assert panel.isHidden(), "函数探索器默认隐藏（§5.3）"

    getattr(docked, method)(True)
    assert not panel.isHidden()

    getattr(docked, method)(False)
    qtbot.waitUntil(lambda: panel.isHidden(), timeout=5000)


@pytest.mark.qt
def test_toggle_notebook_panel_after_setup_ui(host, monkeypatch, qtbot):
    """notebook 由 setup_ui 创建（中央 Tab），其 toggle 同样遵循显隐契约。"""
    _patch_no_jupyter(monkeypatch)
    host.setup_ui()

    host.toggle_notebook_panel(True)
    assert not host.notebook.isHidden()

    host.toggle_notebook_panel(False)
    qtbot.waitUntil(lambda: host.notebook.isHidden(), timeout=5000)


# ── _refresh_notebook_ui ──────────────────────────────────────────────────


@pytest.mark.qt
def test_refresh_notebook_ui_rebuilds_single_code_cell(host):
    from mathlab.core.notebook import CellType

    host.notebook = _FakeNotebook()
    host._refresh_notebook_ui()

    assert host.notebook.canvas_layout.count() == 1, "仅允许剩余结尾弹簧"
    assert host.notebook.ui_cells == []
    assert host.notebook.added == [CellType.CODE]


# ── 真实面板冒烟 ──────────────────────────────────────────────────────────


@pytest.mark.qt
def test_real_panels_construct_and_register(qtbot):
    """7 个真实面板在 offscreen 下可构造，并落入约定的 Dock 布局。"""
    from mathlab.ui.algebra_panel import AlgebraPanel

    win = _TestWindow()
    qtbot.addWidget(win)
    win.setup_docks()

    names = {d.objectName() for d in win.findChildren(QDockWidget)}
    assert names == set(EXPECTED_DOCKS)
    assert isinstance(win.algebra_panel, AlgebraPanel)
