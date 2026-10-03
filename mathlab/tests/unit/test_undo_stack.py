"""Unit tests for mathlab.core.undo_stack — 快照/恢复/栈深/合并器（T05/N8）。

核心回归（R-2）：18 类型 snapshot → restore → snapshot 幂等；
Point._symbolic_expr 懒加载不被触发；Locus trail 不丢；DAG 依赖传播不破坏。
"""

import pytest

from mathlab.core.geometry_engine import GeometryEngine
from mathlab.core.undo_stack import GeometrySnapshot, UndoStack


def build_complex_scene() -> GeometryEngine:
    """构建包含依赖链的复合场景：点 → 线段/圆/多边形 → 交点。"""
    engine = GeometryEngine()
    p1 = engine.add_point(0, 0, name="P1")
    p2 = engine.add_point(4, 0, name="P2")
    p3 = engine.add_point(2, 3, name="P3")
    engine.add_segment(p1, p2)
    engine.add_circle(p1, 2.5)
    engine.add_polygon([p1, p2, p3])
    engine.add_function_plot("sin(x)")
    engine.add_conic_section(1, 0, 1, 0, 0, -4)
    engine.add_implicit_plot("x**2 + y**2 - 9")
    engine.add_polar_plot("1 + 0.5*cos(3*t)")
    engine.add_ellipse(p1, 3.0, 2.0)
    engine.add_parabola(p2, 1.0)
    engine.add_locus(p2, p3)
    return engine


class TestSnapshotRestore:
    @pytest.mark.unit
    def test_snapshot_restore_snapshot_idempotent(self):
        """R-2 核心：snapshot → restore → snapshot 必须与首个快照一致。"""
        engine = build_complex_scene()
        snap1 = engine.snapshot()
        engine.restore_snapshot(snap1)
        snap2 = engine.snapshot()
        assert snap1 == snap2

    @pytest.mark.unit
    def test_restore_rebuilds_objects_and_dag(self):
        engine = build_complex_scene()
        snap = engine.snapshot()
        count = len(engine.objects)
        edge_count = len(snap.edges)

        engine.clear()
        assert len(engine.objects) == 0

        engine.restore_snapshot(snap)
        assert len(engine.objects) == count
        assert len(engine.snapshot().edges) == edge_count

        # DAG 依赖传播不破坏（U-2 核心）：拖动 P1 应级联更新线段/圆
        p1 = next(o for o in engine.objects.values() if o.name == "P1")
        engine.update_point(p1.id, x=10.0, y=10.0)
        seg = next(o for o in engine.objects.values() if o.type == "Segment")
        assert seg.coordinates["x1"] == 10.0
        assert seg.coordinates["y1"] == 10.0

    @pytest.mark.unit
    def test_restore_rebuilds_name_counters_and_free_pool(self):
        engine = GeometryEngine()
        p1 = engine.add_point(0, 0)
        engine.remove_object(p1)  # 名称回收进空闲池
        snap = engine.snapshot()

        engine.clear()
        engine.restore_snapshot(snap)

        snap2 = engine.snapshot()
        assert snap.free_names == snap2.free_names
        assert snap.name_counters == snap2.name_counters

        # 回收的名称应被复用
        new_id = engine.add_point(1, 1)
        assert engine.objects[new_id].name == "P1"

    @pytest.mark.unit
    def test_point_lazy_symbolic_expr_not_forced(self):
        """Point._symbolic_expr 懒加载不能被快照/恢复触发为 SymPy 符号。"""
        engine = GeometryEngine()
        engine.add_point(1, 2)
        point = next(iter(engine.objects.values()))
        assert point._symbolic_expr is None

        engine.restore_snapshot(engine.snapshot())
        restored = next(iter(engine.objects.values()))
        assert restored._symbolic_expr is None

    @pytest.mark.unit
    def test_locus_trail_preserved(self):
        """Locus 引用与轨迹数据不能丢（R-2）。"""
        engine = build_complex_scene()
        locus = next(o for o in engine.objects.values() if o.type == "Locus")
        locus.add_trail_point(1.0, 1.0)
        locus.add_trail_point(2.0, 2.0)
        trail_before = list(locus.trail_points)

        engine.restore_snapshot(engine.snapshot())
        restored_locus = engine.objects[locus.id]
        # JSON 往返后元组会变成列表，归一化后比较
        assert [tuple(p) for p in restored_locus.trail_points] == list(trail_before)
        assert restored_locus.tracer_point_id == locus.tracer_point_id
        assert restored_locus.driver_point_id == locus.driver_point_id

    @pytest.mark.unit
    def test_scene_restored_event_emitted(self):
        engine = GeometryEngine()
        engine.add_point(0, 0)
        events = []
        engine.geometry_event.connect(lambda et, d: events.append(et))
        engine.restore_snapshot(engine.snapshot())
        assert "scene_restored" in events


class TestUndoStack:
    @pytest.mark.unit
    def test_add_then_undo_redo(self):
        """U-1：画点 → undo → 点消失 → redo → 点恢复。"""
        engine = GeometryEngine()
        stack = UndoStack(engine)
        stack.begin_gesture("add_point")  # 手势包裹引擎调用（与 UI 路径一致）
        engine.add_point(1, 1)
        assert stack.end_gesture() is True
        assert len(engine.objects) == 1

        assert stack.undo() is True
        assert len(engine.objects) == 0

        assert stack.redo() is True
        assert len(engine.objects) == 1

    @pytest.mark.unit
    def test_no_difference_gesture_discarded(self):
        engine = GeometryEngine()
        stack = UndoStack(engine)
        stack.begin_gesture("noop")
        assert stack.end_gesture() is False
        assert stack.depth == 0

    @pytest.mark.unit
    def test_cascaded_delete_and_undo(self):
        """U-2：删除被引用的点（级联）→ undo → 整棵子树恢复。"""
        engine = GeometryEngine()
        p1 = engine.add_point(0, 0)
        p2 = engine.add_point(4, 0)
        engine.add_segment(p1, p2)
        stack = UndoStack(engine)

        stack.begin_gesture("delete")
        engine.remove_object(p1)  # 级联删除线段，p2 保留
        stack.end_gesture()
        assert len(engine.objects) == 1

        assert stack.undo() is True
        assert len(engine.objects) == 3
        # DAG 依赖传播仍工作
        engine.update_point(p1, x=8.0)
        seg = next(o for o in engine.objects.values() if o.type == "Segment")
        assert seg.coordinates["x1"] == 8.0

    @pytest.mark.unit
    def test_drag_merges_into_single_undo(self):
        """U-3：拖拽 30 次 → 一次 end_gesture → 仅 1 条撤销。"""
        engine = GeometryEngine()
        pid = engine.add_point(0, 0)
        stack = UndoStack(engine)

        stack.begin_gesture("move")
        for i in range(30):
            engine.update_point(pid, x=float(i), y=0.0)
        stack.end_gesture()

        assert stack.depth == 1
        stack.undo()
        point = engine.objects[pid]
        assert point.coordinates["x"] == 0.0

    @pytest.mark.unit
    def test_debounce_merger_auto_gesture(self, qtbot):
        """U-4：REPL 直调引擎（无手势）→ 500ms 防抖 → 自动收口为一条撤销。"""
        engine = GeometryEngine()
        stack = UndoStack(engine)
        engine.add_point(1, 1)
        engine.add_point(2, 2)
        # 等待防抖定时器触发
        qtbot.waitUntil(lambda: stack.depth == 1, timeout=2000)
        stack.undo()
        assert len(engine.objects) == 0

    @pytest.mark.unit
    def test_max_depth_50(self):
        """U-5：连续 60 次操作 → 栈深 = 50。"""
        engine = GeometryEngine()
        stack = UndoStack(engine)
        for i in range(60):
            stack.begin_gesture("add_point")
            engine.add_point(float(i), 0.0)
            stack.end_gesture()
        assert stack.depth == 50

    @pytest.mark.unit
    def test_disable_switch(self):
        """U-6：enable_undo 关闭 → undo 无效。"""
        engine = GeometryEngine()
        stack = UndoStack(engine, enabled=False)
        engine.add_point(1, 1)
        stack.begin_gesture("add_point")
        stack.end_gesture()
        assert stack.depth == 0
        assert stack.undo() is False

    @pytest.mark.unit
    def test_clear_on_canvas_cleared(self):
        """§6.5：清空画布 → 撤销栈清空（不可跨越「载入」语义）。"""
        engine = GeometryEngine()
        stack = UndoStack(engine)
        stack.begin_gesture("add_point")
        engine.add_point(1, 1)
        stack.end_gesture()
        assert stack.depth == 1

        engine.clear()
        assert stack.depth == 0
        assert stack.undo() is False

    @pytest.mark.unit
    def test_availability_signals(self, qtbot):
        engine = GeometryEngine()
        stack = UndoStack(engine)
        stack.begin_gesture("add_point")
        with qtbot.waitSignal(stack.undo_available):
            engine.add_point(1, 1)
            stack.end_gesture()

    @pytest.mark.unit
    def test_snapshot_frozen(self):
        engine = GeometryEngine()
        snap = engine.snapshot()
        assert isinstance(snap, GeometrySnapshot)
        with pytest.raises(Exception):
            snap.objects = ()
