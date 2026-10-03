"""Qt 信号定义模块。

所有核心模块的事件信号在此集中定义，替代分散的手写监听器。
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
