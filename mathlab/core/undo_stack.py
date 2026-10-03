"""几何真撤销栈（方案 A：整场景快照 — UI_SYSTEM_DESIGN.md §6，D-3）。

设计要点：
- 快照粒度 = **整场景**（objects + DAG edges + 命名计数器 + 空闲名称池），
  复用 ``GeometricObject.serialize()`` / ``restore_snapshot()``，无需为 18 种
  类型写逆操作。
- 所有引擎变更路径（REPL / AI / 脚本 / 命令）都会经 ``_notify`` 发事件 →
  UndoStack 订阅 ``geometry_event``，内置 **500ms 防抖兜底合并器**，无需改调用方。
- 拖拽：拖拽期间 begin_gesture（关闭防抖），``object_move_finished`` →
  end_gesture → 一次拖拽 = 一条撤销。
- 恢复期间（engine._restoring / self._restoring）暂停自动捕获，
  仅监听 ``scene_restored`` 同步基线快照。
- 栈深上限 50（§11 O-5：不暴露到偏好）；单快照 > 2MB 跳过记录。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

from PySide6.QtCore import QObject, QTimer, Signal

from mathlab.utils.logger import get_logger

logger = get_logger(__name__)

# 单快照字节阈值：超过则跳过记录并告警（教室规模场景不应触达）
MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class GeometrySnapshot:
    """整场景不可变快照（frozen dataclass，字段全部为 tuple → 可安全比较）。"""

    objects: tuple[tuple[str, str], ...]  # (obj_id, serialize() 的 JSON 文本)，插入序
    edges: tuple[tuple[str, str], ...]  # DAG (parent_id, child_id)
    name_counters: tuple[tuple[str, int], ...]
    free_names: tuple[tuple[str, tuple[str, ...]], ...]

    def approx_size(self) -> int:
        """快照近似字节数（JSON 文本长度和）。"""
        return sum(len(payload) for _, payload in self.objects)


class UndoCommand:
    """一条可撤销的几何操作 = (before, after, label)。

    text 属性用于菜单 / Toast 文案（i18n key：``undo.op.<label>``）。
    """

    def __init__(self, before: GeometrySnapshot, after: GeometrySnapshot, label: str):
        self.before = before
        self.after = after
        self.label = label

    @property
    def text(self) -> str:
        """操作描述（i18n 键形如 ``undo.op.add_point``）。"""
        return f"undo.op.{self.label}"

    def __repr__(self) -> str:  # pragma: no cover — 调试用
        return f"<UndoCommand label={self.label!r}>"


class UndoStack(QObject):
    """整场景快照撤销栈（纯逻辑层 + Qt 信号，无 GUI 依赖）。"""

    undo_available = Signal(bool)
    redo_available = Signal(bool)
    stack_changed = Signal(int)  # 栈深（调试 / 菜单后缀）

    MAX_DEPTH = 50  # 栈深上限（§11 O-5：常量，不暴露到偏好）

    def __init__(self, engine: Any, max_depth: int = MAX_DEPTH, enabled: bool = True):
        super().__init__()
        self._engine = engine
        self._max_depth = max(1, max_depth)
        self._enabled = enabled

        self._undo: list[UndoCommand] = []
        self._redo: list[UndoCommand] = []
        self._gesture_label: Optional[str] = None  # 打开中的手势（拖拽 / 显式事务）
        self._gesture_before: Optional[GeometrySnapshot] = None
        self._restoring = False  # 撤销/重做恢复期间，抑制事件自捕获
        self._last_snapshot: Optional[GeometrySnapshot] = None  # 兜底合并器基线

        # 500ms 防抖兜底合并器（REPL / 脚本 / AI 直调引擎的路径）
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(500)
        self._debounce_timer.timeout.connect(self._flush_debounce)

        engine.geometry_event.connect(self._on_engine_event)
        # 初始基线（用于兜底合并器的 before 快照）
        self._last_snapshot = engine.snapshot()

    # ── 启用开关（D-3：偏好 enable_undo） ───────────────────────────────

    @property
    def enabled(self) -> bool:
        """撤销栈是否启用。"""
        return self._enabled

    def set_enabled(self, value: bool) -> None:
        """切换启用状态；关闭时清栈并灰置可用信号（零开销）。"""
        self._enabled = bool(value)
        if not self._enabled:
            self.clear()
        self.undo_available.emit(self._enabled and bool(self._undo))
        self.redo_available.emit(self._enabled and bool(self._redo))

    # ── 手势 API（§6.5） ────────────────────────────────────────────────

    @property
    def gesture_active(self) -> bool:
        """是否有打开中的手势。"""
        return self._gesture_label is not None

    def begin_gesture(self, label: str) -> None:
        """开始一个显式手势：记录 before 快照并暂停防抖兜底。

        若上一个手势尚未结束则先收口（防御性，避免快照对错位）。
        """
        if not self._enabled or self._restoring:
            return
        if self._gesture_label is not None:
            self.end_gesture()
        self._debounce_timer.stop()
        self._gesture_label = label
        self._gesture_before = self._engine.snapshot()

    def end_gesture(self) -> bool:
        """结束手势：记录 after；无差异则丢弃。返回是否入栈。"""
        if self._gesture_label is None or self._restoring:
            self._gesture_label = None
            self._gesture_before = None
            return False
        label, before = self._gesture_label, self._gesture_before
        self._gesture_label = None
        self._gesture_before = None
        after = self._engine.snapshot()
        if before is None or after == before:
            self._last_snapshot = after
            return False
        return self._push(UndoCommand(before, after, label))

    def cancel_gesture(self) -> None:
        """异常时回滚手势：丢弃 before/after 对并回滚引擎到 before。"""
        if self._gesture_before is not None and self._gesture_label is not None:
            try:
                self._restoring = True
                self._engine.restore_snapshot(self._gesture_before)
            finally:
                self._restoring = False
                self._last_snapshot = self._engine.snapshot()
        self._gesture_label = None
        self._gesture_before = None
        self._debounce_timer.stop()

    # ── 撤销 / 重做 ─────────────────────────────────────────────────────

    def undo(self) -> bool:
        """撤销最近一条操作：恢复 before 快照。"""
        if not self._enabled or not self._undo:
            return False
        cmd = self._undo.pop()
        self._apply_snapshot(cmd.before)
        self._redo.append(cmd)
        self._emit_state()
        logger.debug("undo %s (stack=%d)", cmd.label, len(self._undo))
        return True

    def redo(self) -> bool:
        """重做最近一条被撤销的操作：恢复 after 快照。"""
        if not self._enabled or not self._redo:
            return False
        cmd = self._redo.pop()
        self._apply_snapshot(cmd.after)
        self._undo.append(cmd)
        self._emit_state()
        logger.debug("redo %s (stack=%d)", cmd.label, len(self._undo))
        return True

    def clear(self) -> None:
        """清空撤销栈（clear 画布 / 打开项目 / 自动存档恢复时调用 — 不可跨越载入语义）。"""
        self._undo.clear()
        self._redo.clear()
        self._gesture_label = None
        self._gesture_before = None
        self._debounce_timer.stop()
        try:
            self._last_snapshot = self._engine.snapshot()
        except Exception:  # pragma: no cover — engine 异常时保底
            self._last_snapshot = None
        self._emit_state()

    @property
    def depth(self) -> int:
        """当前撤销栈深度。"""
        return len(self._undo)

    # ── 内部实现 ────────────────────────────────────────────────────────

    def _push(self, cmd: UndoCommand) -> bool:
        """入栈（含 2MB 阈值与栈深上限）；有新操作时清空 redo 分支。"""
        if cmd.after.approx_size() > MAX_SNAPSHOT_BYTES:
            logger.warning("快照过大（>2MB），跳过撤销记录: %s", cmd.label)
            self._last_snapshot = cmd.after
            return False
        self._redo.clear()
        self._undo.append(cmd)
        while len(self._undo) > self._max_depth:
            self._undo.pop(0)
        self._last_snapshot = cmd.after
        self._emit_state()
        return True

    def _apply_snapshot(self, snap: GeometrySnapshot) -> None:
        """恢复快照（抑制自身事件捕获，恢复后同步基线）。"""
        self._restoring = True
        try:
            self._engine.restore_snapshot(snap)
        finally:
            self._restoring = False
            self._last_snapshot = snap

    def _on_engine_event(self, event_type: str, data: Any) -> None:
        """引擎事件入口：手势打开时不处理；恢复期间仅同步 scene_restored 基线。"""
        if not self._enabled or self._restoring:
            return
        if event_type == "scene_restored":
            self._debounce_timer.stop()
            try:
                self._last_snapshot = self._engine.snapshot()
            except Exception:  # pragma: no cover
                pass
            return
        if event_type == "canvas_cleared":
            # §6.5：清空画布 / 打开项目 / 自动存档恢复 → 清栈（不可跨越「载入」语义）
            self.clear()
            return
        if self._gesture_label is not None:
            return  # 显式手势期间由 end_gesture 统一收口
        if event_type in ("object_added", "object_updated", "object_removed"):
            # 兜底合并器：无打开手势时启动防抖，超时自动收口为一条撤销
            self._debounce_timer.start()

    def _flush_debounce(self) -> None:
        """防抖超时：以「上次基线 → 当前场景」收口为一条自动手势。"""
        if not self._enabled or self._restoring or self._gesture_label is not None:
            return
        before = self._last_snapshot
        after = self._engine.snapshot()
        if before is None or after == before:
            return
        self._push(UndoCommand(before, after, "auto"))
        logger.debug("auto gesture flushed (stack=%d)", len(self._undo))

    def _emit_state(self) -> None:
        """同步可用性信号。"""
        self.undo_available.emit(bool(self._undo))
        self.redo_available.emit(bool(self._redo))
        self.stack_changed.emit(len(self._undo))


def snapshot_to_json(snap: GeometrySnapshot) -> str:
    """快照转 JSON 文本（测试 / 调试用）。"""
    return json.dumps(
        {
            "objects": [list(pair) for pair in snap.objects],
            "edges": [list(edge) for edge in snap.edges],
            "name_counters": [list(pair) for pair in snap.name_counters],
            "free_names": [[k, list(v)] for k, v in snap.free_names],
        },
        ensure_ascii=False,
    )
