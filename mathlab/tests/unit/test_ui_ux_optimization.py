"""UI/UX 优化专项单元测试与 Qt 回归测试。

覆盖本轮四项 UI/UX 升级：
1. 三主题 Design Token 的 WCAG 2.1 AA（≥4.5:1）文字对比度与 styles.qss 模板无残留；
2. ToastManager / ToastCard 非模态通知服务（堆叠上限、自动/手动关闭、语义等级、锚定）；
3. ShortcutRegistry 集中快捷键注册、冲突检测与 WebEngine 焦点保护；
4. OmniBar 延迟初始化（冷启动不创建 QWebEngineView）；
5. 主题入口统一（show_theme_dialog → Preferences 外观页）与三主题循环切换；
6. B3 令牌化面板（FloatingBubble / SmoothCollapsibleBox / MathSlider / QuizCard /
   AlgoVisPanel / FunctionExplorerPanel / AIToolsPanel 加载条）在三主题下无内联硬编码。
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QMainWindow, QWidget

from mathlab.utils.theme_tokens import THEME_TOKENS


def _relative_luminance(hex_color: str) -> float:
    """按 WCAG 2.1 规范计算 sRGB HEX 颜色的相对亮度。"""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) / 255.0 for i in (0, 2, 4))

    def _linear(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * _linear(r) + 0.7152 * _linear(g) + 0.0722 * _linear(b)


def _contrast_ratio(fg_hex: str, bg_hex: str) -> float:
    l1 = _relative_luminance(fg_hex)
    l2 = _relative_luminance(bg_hex)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


class TestWCAGContrastAndQSS:
    @pytest.mark.unit
    @pytest.mark.parametrize("theme_name", ["dark", "light", "sepia"])
    def test_text_tokens_meet_wcag_aa(self, theme_name: str):
        tokens = THEME_TOKENS[theme_name]
        for bg_key in ("bg.base", "bg.surface"):
            bg = tokens[bg_key]
            for fg_key in ("fg.primary", "fg.secondary", "fg.muted"):
                ratio = _contrast_ratio(tokens[fg_key], bg)
                assert ratio >= 4.5, f"{theme_name}: {fg_key}({tokens[fg_key]}) on {bg_key}({bg}) = {ratio:.2f} < 4.5"

    @pytest.mark.unit
    @pytest.mark.parametrize("theme_name", ["dark", "light", "sepia"])
    def test_rendered_qss_contains_toast_and_b3_selectors_without_placeholders(self, theme_name: str):
        from mathlab.utils.theme_manager import render_qss

        qss = render_qss(theme_name)
        assert "${" not in qss
        for selector in (
            "QFrame#toastCard",
            "QLabel#floatingBubbleLabel",
            "QToolButton#collapsibleToggle",
            "QFrame#aiLoadingBanner",
            "QFrame#nbToolbar",
            "QPushButton#fePlotBtn",
            "QFrame#jupyterLoadingCard",
        ):
            assert selector in qss, f"styles.qss 缺少关键选择器 {selector}"


class TestToastService:
    @pytest.mark.qt
    def test_toast_show_levels_and_manual_dismiss(self, qtbot):
        from mathlab.ui.toast import ToastManager

        host = QMainWindow()
        host.resize(800, 600)
        qtbot.addWidget(host)
        host.show()

        mgr = ToastManager(host)
        assert mgr.show_toast("   ") is None
        assert mgr.active_count == 0

        card = mgr.success("Saved!", duration_ms=0)
        assert card is not None
        assert card.property("toastLevel") == "success"
        assert mgr.active_count == 1
        assert card.x() > 0 and card.y() > 0

        card.dismiss()
        qtbot.waitUntil(lambda: mgr.active_count == 0, timeout=3000)

    @pytest.mark.qt
    def test_toast_respects_max_visible_stack(self, qtbot):
        from mathlab.ui.toast import ToastManager

        host = QMainWindow()
        host.resize(800, 600)
        qtbot.addWidget(host)

        mgr = ToastManager(host)
        for i in range(6):
            mgr.info(f"Message {i}", duration_ms=0)

        assert mgr.active_count <= ToastManager.MAX_VISIBLE
        mgr.clear()
        assert mgr.active_count == 0


class TestShortcutRegistry:
    @pytest.mark.qt
    def test_conflict_detection_and_webengine_focus_guard(self, qtbot, monkeypatch):
        import mathlab.ui.shortcut_registry as sr

        host = QWidget()
        qtbot.addWidget(host)
        reg = sr.ShortcutRegistry(host)

        called: list[str] = []
        reg.register("cmd.a", "Ctrl+Shift+P", lambda: called.append("a"))
        assert reg.get_conflicts() == {}

        reg.register("cmd.b", "Ctrl+Shift+P", lambda: called.append("b"))
        conflicts = reg.get_conflicts()
        assert "Ctrl+Shift+P" in conflicts
        assert conflicts["Ctrl+Shift+P"] == ["cmd.a", "cmd.b"]

        # 模拟 WebEngine 获得焦点：受保护快捷键不触发
        monkeypatch.setattr(sr, "is_webengine_focused", lambda widget=None: True)
        reg.get("cmd.a").shortcut.activated.emit()
        assert called == []

        # 焦点回到原生 Qt 控件：正常触发
        monkeypatch.setattr(sr, "is_webengine_focused", lambda widget=None: False)
        reg.get("cmd.a").shortcut.activated.emit()
        assert called == ["a"]


class TestOmniBarLazyInit:
    @pytest.mark.qt
    def test_lazy_init_defers_webengine_creation(self, qtbot):
        from mathlab.ui.omni_bar import OmniBar

        bar = OmniBar(lazy=True)
        qtbot.addWidget(bar)
        assert bar._web_initialized is False
        assert bar.web_view is None


class TestUnifiedThemeEntry:
    @pytest.mark.qt
    def test_toggle_theme_cycles_all_three_themes(self, monkeypatch):
        import mathlab.ui._mixin_dialogs as md
        from mathlab.ui._mixin_dialogs import DialogsMixin

        state = {"theme": "dark"}
        applied: list[str] = []
        toasts: list[str] = []

        monkeypatch.setattr(md, "get_current_theme", lambda: state["theme"])

        class _Host(DialogsMixin):
            def apply_theme(self, key: str) -> None:
                state["theme"] = key
                applied.append(key)

            def show_toast(self, message: str, level: str = "info", duration_ms: int = 3200) -> None:
                toasts.append(message)

        host = _Host()
        host._toggle_theme()
        host._toggle_theme()
        host._toggle_theme()

        assert applied == ["light", "sepia", "dark"]
        assert len(toasts) == 3

    @pytest.mark.unit
    def test_show_theme_dialog_delegates_to_preferences_appearance_tab(self):
        from mathlab.ui._mixin_dialogs import DialogsMixin

        opened_tabs: list[int] = []

        class _Host(DialogsMixin):
            def show_preferences_dialog(self, initial_tab: int = 0) -> None:
                opened_tabs.append(initial_tab)

        host = _Host()
        host.show_theme_dialog()
        assert opened_tabs == [0]


class TestB3TokenizedWidgets:
    @pytest.mark.qt
    def test_b3_widgets_use_object_names_and_theme_tokens(self, qtbot):
        from mathlab.core.signals import theme_signals
        from mathlab.ui.algo_vis_panel import AlgoVisPanel
        from mathlab.ui.animated_widgets import SmoothCollapsibleBox
        from mathlab.ui.floating_bubble import FloatingBubbleWidget
        from mathlab.ui.function_explorer_panel import FunctionExplorerPanel
        from mathlab.ui.interactive_widgets import MathSlider
        from mathlab.ui.quiz_panel import QuizCardWidget

        bubble = FloatingBubbleWidget("Hint")
        qtbot.addWidget(bubble)
        assert bubble.label.objectName() == "floatingBubbleLabel"
        assert bubble.label.styleSheet() == ""

        box = SmoothCollapsibleBox("Plan")
        qtbot.addWidget(box)
        assert box.toggle_btn.objectName() == "collapsibleToggle"
        assert box.toggle_btn.styleSheet() == ""

        slider = MathSlider("k", 0.0, 10.0, 2.5)
        qtbot.addWidget(slider)
        assert slider.label_name.objectName() == "mathSliderName"
        assert slider.slider.styleSheet() == ""

        quiz = QuizCardWidget(
            {
                "knowledge_point": "Geometry",
                "question_text": "1 + 1 = ?",
                "question_type": "multiple_choice",
                "options": ["1", "2"],
                "correct_answer": "B",
            },
            ai_manager=None,
        )
        qtbot.addWidget(quiz)
        assert quiz.styleSheet() == ""

        fe = FunctionExplorerPanel()
        qtbot.addWidget(fe)
        assert fe.plot_btn.objectName() == "fePlotBtn"
        assert fe.plot_btn.styleSheet() == ""

        algo = AlgoVisPanel()
        qtbot.addWidget(algo)
        algo.update_visualization({"type": "sorting", "array": [3, 1, 2], "comparing": [0], "sorted": [2]})
        theme_signals.theme_changed.emit("light")
        assert algo.scene.backgroundBrush().color().name().upper() == THEME_TOKENS["light"]["bg.canvas"].upper()
        theme_signals.theme_changed.emit("dark")
        assert algo.scene.backgroundBrush().color().name().upper() == THEME_TOKENS["dark"]["bg.canvas"].upper()


class TestEventFilterTeardownSafety:
    """回归：PySide6 析构/样式广播期间 eventFilter 不应因属性已清空抛 AttributeError。"""

    @pytest.mark.qt
    def test_event_filters_safe_when_attributes_cleared(self, qtbot):
        from PySide6.QtCore import QEvent

        from mathlab.ui.command_bar import CommandPalette
        from mathlab.ui.console import PythonConsole
        from mathlab.ui.math_console import MathConsole
        from mathlab.ui.toast import ToastManager

        ev = QEvent(QEvent.Type.StyleChange)

        palette = CommandPalette(command_manager=None)
        qtbot.addWidget(palette)
        del palette._input
        assert palette.eventFilter(QWidget(), ev) is False

        console = PythonConsole()
        qtbot.addWidget(console)
        del console.input_line
        assert console.eventFilter(QWidget(), ev) is False

        mc = MathConsole()
        qtbot.addWidget(mc)
        del mc._input
        assert mc.eventFilter(QWidget(), ev) is False

        host = QWidget()
        qtbot.addWidget(host)
        mgr = ToastManager(host)
        del mgr._host
        assert mgr.eventFilter(host, ev) is False
