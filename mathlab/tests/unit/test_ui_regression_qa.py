"""QA 回归补充测试（第 1 轮 — UI/UX 改造独立验证）。

覆盖缺口（基于 test_undo_stack / test_theme_tokens / test_canvas_theme /
test_theme_manager 现状分析）：
1. 全部 18 种 GeometricObject.TYPES 的 snapshot→restore→snapshot 幂等
   （现有测试仅覆盖 11 种）。
2. U-2 深链级联删除：中间节点 → 级联 → undo → 下游坐标回滚 + DAG 传播存活。
3. 防抖合并器边界：事件重启计时器 / 手势期间不捕获 / scene_restored 停表 /
   cancel_gesture 回滚 / undo 后新操作清 redo / set_enabled 往返。
4. 三主题 render_qss 无 ``${`` 残留、THEMES 兼容视图键完整性、
   ui/theme_tokens 垫片同一性、accent 覆写派生色、set_theme 信号链。
5. 会话持久化（session_state.py 此前零测试）：save/restore 往返、
   schemaVersion 篡改/缺失回落默认布局、白纸开关持久化。
6. 画布 theme_changed 重刷 + user_color 保留（§3.4）。

QSettings / settings.json 副作用均通过 fixture 隔离到 tmp_path，
不污染真实用户配置与仓库 settings.json。
"""

from __future__ import annotations

import json

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QDockWidget, QMainWindow, QTabWidget, QWidget

# ── QSettings / settings 副作用隔离 ────────────────────────────────────────────


@pytest.fixture
def isolated_qsettings(tmp_path):
    """把 IniFormat UserScope 的落盘路径重定向到 tmp_path，保护真实用户配置。"""
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    yield tmp_path
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, "")


@pytest.fixture
def no_settings_io(monkeypatch):
    """阻断 theme_manager 对仓库 settings.json 的读写（load/save 全部隔离）。"""
    import mathlab.utils.theme_manager as tm

    state: dict = {"theme": "dark", "accent": ""}

    monkeypatch.setattr(tm, "load_settings", lambda: dict(state))
    monkeypatch.setattr(tm, "save_settings", lambda patch: state.update(patch))
    return state


@pytest.fixture(autouse=True)
def _reset_theme_cache():
    """每个测试结束后清空 theme_manager 的主题缓存，避免跨测试泄漏。"""
    yield
    import mathlab.utils.theme_manager as tm

    tm._cached_theme = None


# ── 1. 全类型 snapshot → restore → snapshot 幂等（R-2） ───────────────────────


def _make_full_scene():
    """构建覆盖引擎可创建的全部 15 种类型的场景。"""
    from mathlab.core.geometry_engine import GeometryEngine

    eng = GeometryEngine()
    p1 = eng.add_point(0, 0, 0, name="P1")
    p2 = eng.add_point(4, 0, 0, name="P2")
    p3 = eng.add_point(2, 3, 1, name="P3")
    eng.add_segment(p1, p2, name="S1")
    eng.add_line(p1, p2, name="L1")
    eng.add_circle(p1, 2.5, name="C1")
    eng.add_polygon([p1, p2, p3], name="Gon1")
    eng.add_intersection(p2, p1, 0, name="I1")
    eng.add_sphere(p1, 1.5, name="Sp1")
    eng.add_ellipse(p1, 3.0, 2.0, name="E1")
    eng.add_hyperbola(p2, 1.0, 1.0, name="H1")
    eng.add_parabola(p2, 1.0, name="Pb1")
    eng.add_conic_section(1, 0, 1, 0, 0, -4, name="Cs1")
    eng.add_function_plot("sin(x)", name="F1")
    eng.add_implicit_plot("x**2 + y**2 - 9", name="Imp1")
    eng.add_polar_plot("1 + 0.5*cos(3*t)", name="Pol1")
    eng.add_locus(p2, p3, name="Lo1")
    return eng


class TestFullTypeIdempotency:
    """R-2：全部 18 类型（含引擎不可直建的 Ray/Angle/Plane3D）快照幂等。"""

    @pytest.mark.unit
    def test_all_engine_types_snapshot_idempotent(self):
        eng = _make_full_scene()
        types_present = {o.type for o in eng.objects.values()}
        expected = {
            "Point",
            "Segment",
            "Line",
            "Circle",
            "Polygon",
            "Intersection",
            "Sphere",
            "Ellipse",
            "Hyperbola",
            "Parabola",
            "ConicSection",
            "FunctionPlot",
            "ImplicitPlot",
            "PolarPlot",
            "Locus",
        }
        assert types_present == expected, f"场景类型不全: {expected - types_present}"

        snap1 = eng.snapshot()
        eng.restore_snapshot(snap1)
        snap2 = eng.snapshot()
        assert snap1 == snap2, "snapshot → restore → snapshot 不幂等"

    @pytest.mark.unit
    def test_fallback_types_ray_angle_plane3d_idempotent(self):
        """Ray / Angle / Plane3D 无专属引擎工厂，经 deserialize 兜底路径验证。"""
        from mathlab.core.geometry_engine import GeometryEngine
        from mathlab.core.models import GeometricObject

        eng = GeometryEngine()
        base = {
            "coordinates": {},
            "symbolic_expr": None,
            "constraints": [],
            "depends_on": [],
            "is_draft": False,
        }
        injected = {}
        for i, t in enumerate(["Ray", "Angle", "Plane3D"]):
            data = {
                **base,
                "id": f"fallback-{i}",
                "name": f"FB{i}",
                "type": t,
                "coordinates": ({"A": 1, "B": 0, "C": 1, "D": 0} if t == "Plane3D" else {}),
            }
            obj = GeometricObject.deserialize(data)
            eng.objects[obj.id] = obj
            injected[obj.id] = data

        snap1 = eng.snapshot()
        eng.restore_snapshot(snap1)
        snap2 = eng.snapshot()
        assert snap1 == snap2
        # 兜底类型的关键属性（point1_id 等）在恢复后仍可访问
        for oid, data in injected.items():
            restored = eng.objects[oid]
            assert restored.type == data["type"]
            assert restored.name == data["name"]

    @pytest.mark.unit
    def test_snapshot_json_roundtrip(self):
        from mathlab.core.undo_stack import snapshot_to_json

        eng = _make_full_scene()
        snap = eng.snapshot()
        assert snap.approx_size() > 0
        payload = json.loads(snapshot_to_json(snap))
        assert len(payload["objects"]) == len(eng.objects)
        assert payload["objects"][0][0] in dict(snap.objects)


# ── 2. U-2 深链级联删除恢复（QA 最高优先） ────────────────────────────────────


class TestCascadeDeleteRestore:
    """U-2 深链：P1 → {Segment, Circle} → Intersection，删 P1 级联 3 对象。"""

    @pytest.fixture
    def chain_scene(self):
        from mathlab.core.geometry_engine import GeometryEngine

        eng = GeometryEngine()
        p1 = eng.add_point(0, 0, name="P1")
        p2 = eng.add_point(4, 0, name="P2")
        seg = eng.add_segment(p1, p2, name="S1")
        cir = eng.add_circle(p1, 3.0, name="C1")
        inter = eng.add_intersection(seg, cir, 0, name="I1")
        return eng, p1, p2, seg, cir, inter

    @pytest.mark.unit
    def test_intermediate_delete_cascades_and_undo_restores_all(self, chain_scene):
        eng, p1, p2, seg, cir, inter = chain_scene
        from mathlab.core.undo_stack import UndoStack

        stack = UndoStack(eng)
        inter_before = dict(eng.objects[inter].coordinates)

        stack.begin_gesture("delete")
        eng.remove_object(p1)
        stack.end_gesture()
        # 级联：P1 + Segment + Circle + Intersection 全部删除，P2 保留
        assert len(eng.objects) == 1
        assert eng.objects[p2].name == "P2"

        assert stack.undo() is True
        assert len(eng.objects) == 5
        # 子树完整恢复：类型、数量
        types = {o.type for o in eng.objects.values()}
        assert types == {"Point", "Segment", "Circle", "Intersection"}
        # 下游坐标回滚：交点坐标与删除前一致
        assert dict(eng.objects[inter].coordinates) == inter_before

    @pytest.mark.unit
    def test_dag_propagation_alive_after_undo(self, chain_scene):
        """撤销后 DAG 传播不失效（★设计文档 6.6 QA 必测点）。"""
        eng, p1, p2, seg, cir, inter = chain_scene
        from mathlab.core.undo_stack import UndoStack

        stack = UndoStack(eng)
        stack.begin_gesture("delete")
        eng.remove_object(p1)
        stack.end_gesture()
        stack.undo()

        inter_before = eng.objects[inter].coordinates.get("x")
        # 拖动 P1 → Segment / Circle 更新 → Intersection（二级下游）必须跟随
        eng.update_point(p1, x=10.0, y=0.0)
        seg_coords = eng.objects[seg].coordinates
        assert seg_coords["x1"] == 10.0, "撤销后 Segment 未跟随 P1"
        inter_after = eng.objects[inter].coordinates.get("x")
        assert inter_after is not None
        assert inter_after != inter_before, "撤销后二级下游 Intersection 不再随 DAG 传播"

    @pytest.mark.unit
    def test_names_and_counters_consistent_after_cascade_undo(self, chain_scene):
        eng, p1, p2, seg, cir, inter = chain_scene
        from mathlab.core.undo_stack import UndoStack

        stack = UndoStack(eng)
        snap_before = eng.snapshot()
        stack.begin_gesture("delete")
        eng.remove_object(p1)
        stack.end_gesture()
        stack.undo()
        assert eng.snapshot() == snap_before, "级联撤销后场景快照与删除前不一致"

        # 命名计数器/空闲池一致：新建 Point 应回收 P1 的名称
        new_id = eng.add_point(7, 7)
        assert eng.objects[new_id].name == "P1"

    @pytest.mark.unit
    def test_redo_reapplies_cascade_delete(self, chain_scene):
        eng, p1, p2, seg, cir, inter = chain_scene
        from mathlab.core.undo_stack import UndoStack

        stack = UndoStack(eng)
        stack.begin_gesture("delete")
        eng.remove_object(p1)
        stack.end_gesture()
        stack.undo()
        assert len(eng.objects) == 5
        assert stack.redo() is True
        assert len(eng.objects) == 1
        assert stack.undo() is True
        assert len(eng.objects) == 5


# ── 3. 防抖合并器边界 ─────────────────────────────────────────────────────────


class TestDebounceMergerBoundaries:
    @pytest.mark.unit
    def test_rapid_events_within_window_merge_to_one(self, qtbot):
        """事件重启 500ms 计时器：窗口内连续事件合并为 1 条。"""
        from mathlab.core.geometry_engine import GeometryEngine
        from mathlab.core.undo_stack import UndoStack

        eng = GeometryEngine()
        stack = UndoStack(eng)
        eng.add_point(1, 1)
        qtbot.wait(300)  # 计时器剩余 200ms
        eng.add_point(2, 2)  # 重启计时器
        qtbot.waitUntil(lambda: stack.depth == 1, timeout=2000)
        assert stack.depth == 1
        # undo 一次回到空场景（两条添加合并为一条命令）
        stack.undo()
        assert len(eng.objects) == 0

    @pytest.mark.unit
    def test_no_auto_command_after_closed_gesture(self, qtbot):
        """手势收口后防抖不产生第二条自动命令。"""
        from mathlab.core.geometry_engine import GeometryEngine
        from mathlab.core.undo_stack import UndoStack

        eng = GeometryEngine()
        stack = UndoStack(eng)
        stack.begin_gesture("move")
        eng.add_point(1, 1)
        stack.end_gesture()
        assert stack.depth == 1
        qtbot.wait(700)
        assert stack.depth == 1, "手势收口后不应有自动命令"

    @pytest.mark.unit
    def test_events_during_gesture_not_double_counted(self):
        """手势打开时引擎事件不触发防抖（由 end_gesture 统一收口）。"""
        from mathlab.core.geometry_engine import GeometryEngine
        from mathlab.core.undo_stack import UndoStack

        eng = GeometryEngine()
        stack = UndoStack(eng)
        stack.begin_gesture("add_point")
        for i in range(5):
            eng.add_point(float(i), 0.0)
        assert stack.depth == 0
        assert stack.end_gesture() is True
        assert stack.depth == 1

    @pytest.mark.unit
    def test_scene_restored_stops_pending_debounce(self, qtbot):
        """scene_restored 停掉未决防抖计时器（§6.3 恢复期间不记录）。"""
        from mathlab.core.geometry_engine import GeometryEngine
        from mathlab.core.undo_stack import UndoStack

        eng = GeometryEngine()
        stack = UndoStack(eng)
        eng.add_point(1, 1)  # 防抖计时器启动
        eng.restore_snapshot(eng.snapshot())  # 发 scene_restored → 停表
        qtbot.wait(700)
        assert stack.depth == 0, "scene_restored 后防抖不应再收口自动命令"

    @pytest.mark.unit
    def test_cancel_gesture_rolls_back_engine(self):
        from mathlab.core.geometry_engine import GeometryEngine
        from mathlab.core.undo_stack import UndoStack

        eng = GeometryEngine()
        stack = UndoStack(eng)
        stack.begin_gesture("risky")
        eng.add_point(1, 1)
        stack.cancel_gesture()
        assert len(eng.objects) == 0
        assert stack.depth == 0
        assert stack.gesture_active is False

    @pytest.mark.unit
    def test_new_operation_clears_redo_branch(self):
        from mathlab.core.geometry_engine import GeometryEngine
        from mathlab.core.undo_stack import UndoStack

        eng = GeometryEngine()
        stack = UndoStack(eng)
        stack.begin_gesture("a")
        eng.add_point(1, 1)
        stack.end_gesture()
        stack.undo()
        assert stack.redo() is True
        stack.undo()
        stack.begin_gesture("b")
        eng.add_point(2, 2)
        stack.end_gesture()
        assert stack.redo() is False, "新操作后 redo 分支必须清空"

    @pytest.mark.unit
    def test_set_enabled_roundtrip(self):
        from mathlab.core.geometry_engine import GeometryEngine
        from mathlab.core.undo_stack import UndoStack

        eng = GeometryEngine()
        stack = UndoStack(eng)
        stack.begin_gesture("a")
        eng.add_point(1, 1)
        stack.end_gesture()
        assert stack.depth == 1

        stack.set_enabled(False)
        assert stack.depth == 0
        assert stack.undo() is False

        stack.set_enabled(True)
        stack.begin_gesture("b")
        eng.add_point(2, 2)
        assert stack.end_gesture() is True

    @pytest.mark.unit
    def test_custom_max_depth_evicts_oldest(self):
        from mathlab.core.geometry_engine import GeometryEngine
        from mathlab.core.undo_stack import UndoStack

        eng = GeometryEngine()
        stack = UndoStack(eng, max_depth=3)
        for i in range(5):
            stack.begin_gesture("add")
            eng.add_point(float(i), 0.0)
            stack.end_gesture()
        assert stack.depth == 3
        # 最早的 2 条已被逐出：undo 3 次后场景应剩 2 个点（第 2 次操作之后的状态）
        for _ in range(3):
            assert stack.undo() is True
        assert len(eng.objects) == 2
        assert stack.undo() is False


# ── 4. 三主题渲染 / 兼容垫片 / accent 覆写 / set_theme 信号链 ─────────────────


class TestThemeRenderAndShim:
    @pytest.mark.unit
    @pytest.mark.parametrize("theme", ["light", "dark", "sepia"])
    def test_render_qss_no_placeholder_residue(self, theme):
        """T01 验收：三主题渲染产物无 ``${`` 残留。"""
        from mathlab.utils.theme_manager import render_qss

        qss = render_qss(theme)
        assert "${" not in qss, f"{theme} 渲染后仍有未替换占位符"
        assert len(qss) > 500

    @pytest.mark.unit
    def test_qss_template_file_exists(self):
        import os

        from mathlab.utils.theme_manager import QSS_TEMPLATE_FILE

        assert os.path.exists(QSS_TEMPLATE_FILE)

    @pytest.mark.unit
    def test_themes_legacy_view_complete_and_valid(self):
        """§1.7 兼容垫片：全部旧键存在且为合法 HEX（存量消费者不炸）。"""
        from mathlab.utils.theme_manager import _TOKEN_TO_LEGACY, THEMES
        from mathlab.utils.theme_tokens import THEME_TOKENS

        for theme_name, view in THEMES.items():
            for legacy_key, token_key in _TOKEN_TO_LEGACY.items():
                value = view[legacy_key]
                expected = THEME_TOKENS[theme_name][token_key]
                if expected.startswith("#"):
                    assert value == expected
                    QColor(value)  # 非 DEBUG 构建不抛错，用 isValid 显式断言
                    assert QColor(value).isValid(), f"{theme_name}.{legacy_key} = {value!r} 非法"
            assert view["name"]  # 显示名存在

    @pytest.mark.unit
    def test_ui_theme_tokens_shim_is_same_object(self):
        """PRD 命名垫片 mathlab/ui/theme_tokens.py 再导出同一数据源。"""
        import mathlab.ui.theme_tokens as ui_shim
        import mathlab.utils.theme_tokens as ssot

        assert ui_shim.THEME_TOKENS is ssot.THEME_TOKENS
        assert ui_shim.get_tokens is ssot.get_tokens

    @pytest.mark.unit
    def test_accent_override_derives_hover_and_pressed(self, monkeypatch):
        """§11 O-2：用户强调色覆写 base，并派生 hover（亮）/pressed（暗）。"""
        import mathlab.utils.theme_manager as tm
        from mathlab.utils.theme_tokens import THEME_TOKENS

        monkeypatch.setattr(tm, "load_settings", lambda: {"accent": "#FF0000"})
        tokens = dict(THEME_TOKENS["dark"])
        tm._apply_user_accent_override(tokens)
        assert tokens["accent.base"] == "#FF0000"
        hover_l = QColor(tokens["accent.hover"]).getHslF()[2]
        pressed_l = QColor(tokens["accent.pressed"]).getHslF()[2]
        assert hover_l > pressed_l
        # SSOT 不被污染（set_theme 传入的是副本）
        assert THEME_TOKENS["dark"]["accent.base"] == "#3B82F6"

    @pytest.mark.unit
    @pytest.mark.parametrize("bad_accent", ["", None, "not-a-color", 123])
    def test_accent_override_ignores_invalid(self, monkeypatch, bad_accent):
        import mathlab.utils.theme_manager as tm
        from mathlab.utils.theme_tokens import THEME_TOKENS

        monkeypatch.setattr(tm, "load_settings", lambda: {"accent": bad_accent})
        tokens = dict(THEME_TOKENS["dark"])
        original = dict(tokens)
        tm._apply_user_accent_override(tokens)
        assert tokens == original

    @pytest.mark.unit
    def test_get_theme_colors_unknown_falls_back_to_light(self):
        from mathlab.utils.theme_manager import get_theme_colors

        colors = get_theme_colors("nonexistent")
        assert colors["name"] == "Light"

    @pytest.mark.unit
    def test_set_theme_loop_emits_signal_and_applies_qss(self, qapp, no_settings_io, qtbot):
        """三主题循环切换：每次 app 级注入唯一且 theme_changed 同步发射。"""
        import mathlab.utils.theme_manager as tm
        from mathlab.core.signals import theme_signals

        received = []
        theme_signals.theme_changed.connect(received.append)
        try:
            for theme in ("dark", "light", "sepia", "dark"):
                assert tm.set_theme(theme) is True
                assert received[-1] == theme
                qss = qapp.styleSheet()
                assert "${" not in qss
                bg = tm.THEME_TOKENS[theme]["bg.base"]
                assert bg in qss, f"{theme} 的 bg.base 未注入 styleSheet"
                assert qapp.property("current_theme") == theme
            assert len(received) == 4
        finally:
            theme_signals.theme_changed.disconnect(received.append)

    @pytest.mark.unit
    def test_set_theme_unknown_returns_false(self, no_settings_io):
        import mathlab.utils.theme_manager as tm

        assert tm.set_theme("neon-pink") is False

    @pytest.mark.unit
    def test_theme_singleton_signal(self):
        """theme_signals 是模块级单例（订阅方与 set_theme 用同一实例）。"""
        from mathlab.core.signals import ThemeSignals, theme_signals

        assert isinstance(theme_signals, ThemeSignals)
        import mathlab.core.signals as s

        assert theme_signals is s.theme_signals


# ── 5. 会话持久化（session_state.py — 此前零测试） ────────────────────────────


class _StubMainWindow(QMainWindow):
    """最小主窗口桩：central_tabs + 两个带 objectName 的 Dock。"""

    def __init__(self):
        super().__init__()
        self.central_tabs = QTabWidget()
        self.central_tabs.addTab(QWidget(), "Canvas")
        self.central_tabs.addTab(QWidget(), "Notebook")
        self.setCentralWidget(self.central_tabs)

        self.dock_a = QDockWidget("Algebra", self)
        self.dock_a.setObjectName("dockAlgebra")
        self.dock_a.setWidget(QWidget())
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.dock_a)
        self.dock_b = QDockWidget("Console", self)
        self.dock_b.setObjectName("dockConsole")
        self.dock_b.setWidget(QWidget())
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock_b)


class TestSessionState:
    @pytest.mark.unit
    def test_save_restore_roundtrip(self, qapp, isolated_qsettings):
        from mathlab.ui import session_state as ss

        win = _StubMainWindow()
        # 注意：offscreen 虚拟屏幕较小（~800x600），保存超出屏幕的几何会在
        # restoreGeometry 时被 Qt 钳制，故使用屏幕内尺寸且不 show()。
        win.resize(500, 400)
        win.move(40, 50)
        win.central_tabs.setCurrentIndex(1)
        ss.save_session(win)

        win2 = _StubMainWindow()
        assert ss.restore_session(win2) is True
        assert win2.central_tabs.currentIndex() == 1
        # 几何恢复（save/restore 往返一致）
        assert win2.width() == win.width()
        assert win2.height() == win.height()
        win.close()
        win2.close()

    @pytest.mark.unit
    def test_schema_version_mismatch_falls_back_to_default(self, qapp, isolated_qsettings):
        from mathlab.ui import session_state as ss

        win = _StubMainWindow()
        ss.save_session(win)

        settings = ss.make_settings()
        settings.setValue(ss.KEY_SCHEMA_VERSION, 999)
        settings.sync()

        win2 = _StubMainWindow()
        win2.central_tabs.setCurrentIndex(1)
        assert ss.restore_session(win2) is False, "schema 不符必须回落默认布局"
        assert win2.central_tabs.currentIndex() == 0, "默认布局应落在第一个 Tab（R-08）"
        win.close()
        win2.close()

    @pytest.mark.unit
    def test_missing_schema_version_falls_back_to_default(self, qapp, isolated_qsettings):
        from mathlab.ui import session_state as ss

        win2 = _StubMainWindow()
        assert ss.restore_session(win2) is False
        assert win2.central_tabs.currentIndex() == 0
        win2.close()

    @pytest.mark.unit
    def test_dock_visibility_persisted(self, qapp, isolated_qsettings):
        from mathlab.ui import session_state as ss

        win = _StubMainWindow()
        win.dock_b.hide()
        win.show()
        ss.save_session(win)
        settings = ss.make_settings()
        settings.sync()
        # objectName 与 save_session 写入侧一致（dockAlgebra / dockConsole）
        assert settings.value(ss.KEY_DOCK_VISIBLE.format(name="dockConsole"), None, type=bool) is False
        assert settings.value(ss.KEY_DOCK_VISIBLE.format(name="dockAlgebra"), None, type=bool) is True
        win.close()

    @pytest.mark.unit
    def test_white_paper_switch_persists(self, qapp, isolated_qsettings):
        """D-2：白纸开关写入 QSettings 后可重新读取（模拟重启）。"""
        from mathlab.ui import session_state as ss

        assert ss.get_white_paper() is False  # 默认关
        ss.set_white_paper(True)
        # 新建 QSettings 实例模拟进程重启
        assert ss.make_settings().value(ss.KEY_WHITE_PAPER, False, type=bool) is True
        assert ss.get_white_paper() is True
        ss.set_white_paper(False)
        assert ss.get_white_paper() is False

    @pytest.mark.unit
    def test_reset_session_clears_and_applies_default(self, qapp, isolated_qsettings):
        from mathlab.ui import session_state as ss

        win = _StubMainWindow()
        ss.save_session(win)
        ss.reset_session(win)
        settings = ss.make_settings()
        assert settings.value(ss.KEY_GEOMETRY) is None, "reset 后几何数据应被清除"
        assert win.central_tabs.currentIndex() == 0
        win.close()

    @pytest.mark.unit
    def test_save_restore_key_sets_are_consistent(self, qapp, isolated_qsettings):
        """save/restore 双侧 key 一致性：save 写入的全部 key restore 均可读。"""
        from mathlab.ui import session_state as ss

        win = _StubMainWindow()
        win.show()
        ss.save_session(win)
        settings = ss.make_settings()
        settings.sync()

        expected_keys = {
            ss.KEY_SCHEMA_VERSION,
            ss.KEY_GEOMETRY,
            ss.KEY_WINDOW_STATE,
            ss.KEY_LAST_TAB,
            ss.KEY_FIRST_RUN,
        }
        for key in expected_keys:
            assert settings.value(key) is not None, f"save_session 未写入 {key}"
        # KEY_WHITE_PAPER 不属于 save_session（由 set_white_paper 单独管理，§5.1 边界）
        assert ss.KEY_WHITE_PAPER not in settings.allKeys()
        win.close()


# ── 6. 画布主题重刷 + user_color 保留（§3.3 / §3.4） ──────────────────────────


class TestCanvasThemeRefresh:
    @pytest.fixture
    def canvas(self, qapp, isolated_qsettings):
        from mathlab.ui.canvas import GeometryCanvas

        c = GeometryCanvas()
        yield c
        c.deleteLater()

    @pytest.mark.unit
    def test_theme_changed_rebuilds_palette_and_background(self, canvas):
        from mathlab.core.signals import theme_signals
        from mathlab.utils.theme_tokens import THEME_TOKENS

        theme_signals.theme_changed.emit("light")
        assert canvas._theme_name == "light"
        assert canvas._palette.paper == THEME_TOKENS["light"]["bg.canvas"]
        bg = canvas.scene_obj.backgroundBrush().color().name()
        assert bg.upper() == THEME_TOKENS["light"]["bg.canvas"].upper()

        theme_signals.theme_changed.emit("sepia")
        assert canvas._palette.paper == THEME_TOKENS["sepia"]["bg.canvas"]

    @pytest.mark.unit
    def test_unknown_theme_signal_falls_back_to_dark_palette(self, canvas):
        from mathlab.core.signals import theme_signals
        from mathlab.utils.theme_tokens import THEME_TOKENS

        theme_signals.theme_changed.emit("no-such-theme")
        assert canvas._theme_name == "no-such-theme"
        assert canvas._palette.paper == THEME_TOKENS["dark"]["bg.canvas"]

    @pytest.mark.unit
    def test_user_color_survives_theme_switch(self, canvas, isolated_qsettings):
        """§3.4：用户改色对象在主题切换后保留用户色（用户意图最高优先）。"""
        from mathlab.core.geometry_engine import GeometryEngine
        from mathlab.core.signals import theme_signals

        eng = GeometryEngine()
        oid = eng.add_point(1, 2, name="P1")
        canvas.resync_from_engine(eng)
        canvas.set_user_color(oid, "#123456")
        assert canvas.object_map[oid]["user_color"] == "#123456"

        theme_signals.theme_changed.emit("light")
        color = canvas._kind_color("point", oid)
        assert color.name().upper() == "#123456"
        # 主题对象色 ≠ 用户色，证明取的确实是 user_color
        assert color.name().upper() != "#004AC6"  # light.obj.point

    @pytest.mark.unit
    def test_user_color_none_falls_back_to_theme(self, canvas, isolated_qsettings):
        from mathlab.core.geometry_engine import GeometryEngine
        from mathlab.core.signals import theme_signals
        from mathlab.utils.theme_tokens import THEME_TOKENS

        eng = GeometryEngine()
        oid = eng.add_point(1, 2, name="P1")
        canvas.resync_from_engine(eng)
        theme_signals.theme_changed.emit("dark")
        assert canvas._kind_color("point", oid).name().upper() == THEME_TOKENS["dark"]["obj.point"].upper()

    @pytest.mark.unit
    def test_resync_from_engine_populates_metadata(self, canvas, isolated_qsettings):
        """§6.6：resync 后 object_map 带 type / user_color 元数据。"""
        from mathlab.core.geometry_engine import GeometryEngine

        eng = GeometryEngine()
        eng.add_point(1, 2, name="P1")
        oid, obj = next(iter(eng.objects.items()))
        canvas.resync_from_engine(eng)
        info = canvas.object_map[oid]
        assert info["type"] == "Point"
        assert info["user_color"] is None
