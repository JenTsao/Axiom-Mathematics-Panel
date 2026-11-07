"""Qt 信号定义模块（DEPRECATED 兼容层 + 主题总线）。

**本模块不是全仓的集中信号总线**——这是历史设计意图，不是代码事实：

* 唯一仍在使用的是 :class:`ThemeSignals` 及模块级单例 ``theme_signals``：
  ``theme_manager.set_theme()`` 发射，``ui/canvas.py`` 订阅。
* ``GeometrySignals`` / ``ConsoleSignals`` / ``AlgorithmSignals`` / ``AISignals``
  全仓**没有任何 emit / connect**，仅为兼容 ``mathlab.core.__init__`` 的
  re-export（``__all__`` + ``__getattr__`` 映射）而保留。新代码不要使用它们，
  也不要把它们当成"新增信号应该放这里"的位置。
* 真实跨模块信号分散定义于 ``geometry_engine.py``（内置 4 个信号）、
  ``ai_engine_worker.py``、``async_workers.py``、``agent_bridge.py``、
  ``undo_stack.py``、``octave_bridge.py`` 等处。
* 接线同样不集中：全 ``ui/`` 有 200+ 处 ``.connect(``，
  ``SignalsMixin.connect_signals()`` 只占其中一小部分。详见 AGENTS.md §4.4。
"""

from PySide6.QtCore import QObject, Signal


class GeometrySignals(QObject):
    """几何引擎信号（已被 GeometryEngine 内置信号替代，保留用于兼容）。"""

    object_added = Signal(dict)
    object_updated = Signal(dict)
    object_removed = Signal(object)
    selection_changed = Signal(str)
    equation_changed = Signal(str, str)
    signals_blocked_changed = Signal(bool)


class ConsoleSignals(QObject):
    """控制台信号。"""

    output_received = Signal(str)
    error_received = Signal(str)
    prompt_ready = Signal()


class AlgorithmSignals(QObject):
    """算法动画信号。"""

    step_ready = Signal(object)
    animation_finished = Signal()
    progress_updated = Signal(int)


class AISignals(QObject):
    """AI 操作信号。"""

    prediction_ready = Signal(object)
    training_progress = Signal(int, float)
    training_finished = Signal(object)
    error_occurred = Signal(str)


class ThemeSignals(QObject):
    """主题变更信号（UI_SYSTEM_DESIGN.md §1.2 / M12）。

    由 ``theme_manager.set_theme()`` 在样式应用**之后**发射；
    订阅方只做「取新 token + 重绘」，不得反向调用 ``set_theme``。
    """

    theme_changed = Signal(str)


# 模块级单例：跨模块主题订阅统一入口
theme_signals = ThemeSignals()
