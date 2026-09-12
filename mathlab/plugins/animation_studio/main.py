# mathlab/plugins/animation_studio/main.py
"""动画演示插件 — 几何变换动画、函数参数动画、轨迹追踪动画。"""

import math
import re

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from mathlab.core.extension_api import MathLabAPI
from mathlab.core.plugin_base import MathLabPlugin
from mathlab.utils.i18n_manager import t


class AnimationPanelWidget(QWidget):
    """动画演示侧边栏面板"""

    def __init__(self, api: MathLabAPI, parent=None):
        super().__init__(parent)
        self.api = api
        self._timer = QTimer()
        self._timer.timeout.connect(self._on_tick)
        self._anim_state = {
            "type": None,  # "translate" | "rotate" | "scale" | "param_func"
            "elapsed": 0.0,
            "duration": 4.0,  # 秒
            "point_ids": [],  # 受动画影响的点 ID
            "orig_coords": [],  # 原始坐标 [(x, y), ...]
            "func_id": None,  # 函数参数动画时的 FunctionPlot ID
            "func_expr": "",  # 原始表达式模板 (含参数 a)
            "center": (0.0, 0.0),  # 旋转/缩放中心
        }
        self._is_playing = False
        self._init_ui()

    # ──────────────────────────────────────────────────────────────
    # UI 构建
    # ──────────────────────────────────────────────────────────────
    def _init_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setSpacing(8)
        layout.setContentsMargins(8, 8, 8, 8)

        # ── 标题 ──
        title = QLabel(t("plugins.animation_studio") or "Animation Studio")
        title.setStyleSheet("font-weight: bold; font-size: 14px; color: #ffffff; margin-bottom: 6px;")
        layout.addWidget(title)

        # ── 动画类型 ──
        type_group = QGroupBox(t("animation.type") or "Animation Type")
        type_layout = QVBoxLayout(type_group)
        self.combo_type = QComboBox()
        self.combo_type.addItem(t("animation.translate") or "Translation", "translate")
        self.combo_type.addItem(t("animation.rotate") or "Rotation", "rotate")
        self.combo_type.addItem(t("animation.scale") or "Scaling", "scale")
        self.combo_type.addItem(t("animation.param_func") or "Function Parameter", "param_func")
        self.combo_type.currentIndexChanged.connect(self._on_type_changed)
        type_layout.addWidget(self.combo_type)
        layout.addWidget(type_group)

        # ── 参数区域 ──
        self.param_group = QGroupBox(t("animation.parameters") or "Parameters")
        self.param_layout = QFormLayout(self.param_group)
        layout.addWidget(self.param_group)

        # 通用参数
        self.spin_duration = QDoubleSpinBox()
        self.spin_duration.setRange(0.5, 60.0)
        self.spin_duration.setDecimals(1)
        self.spin_duration.setValue(4.0)
        self.spin_duration.setSuffix("s")

        # 平移参数
        self.spin_tx = QDoubleSpinBox()
        self.spin_tx.setRange(-50, 50)
        self.spin_tx.setValue(5.0)
        self.spin_ty = QDoubleSpinBox()
        self.spin_ty.setRange(-50, 50)
        self.spin_ty.setValue(0.0)

        # 旋转参数
        self.spin_rot_cx = QDoubleSpinBox()
        self.spin_rot_cx.setRange(-100, 100)
        self.spin_rot_cx.setValue(0.0)
        self.spin_rot_cy = QDoubleSpinBox()
        self.spin_rot_cy.setRange(-100, 100)
        self.spin_rot_cy.setValue(0.0)
        self.spin_rot_angle = QDoubleSpinBox()
        self.spin_rot_angle.setRange(-720, 720)
        self.spin_rot_angle.setValue(360.0)
        self.spin_rot_angle.setSuffix("°")

        # 缩放参数
        self.spin_scale_cx = QDoubleSpinBox()
        self.spin_scale_cx.setRange(-100, 100)
        self.spin_scale_cx.setValue(0.0)
        self.spin_scale_cy = QDoubleSpinBox()
        self.spin_scale_cy.setRange(-100, 100)
        self.spin_scale_cy.setValue(0.0)
        self.spin_scale_factor = QDoubleSpinBox()
        self.spin_scale_factor.setRange(0.01, 10.0)
        self.spin_scale_factor.setDecimals(2)
        self.spin_scale_factor.setValue(2.0)

        # 函数参数动画
        self.input_func_expr = QLineEdit()
        self.input_func_expr.setPlaceholderText("e.g. sin(a*x), a*x**2")
        self.spin_param_start = QDoubleSpinBox()
        self.spin_param_start.setRange(-100, 100)
        self.spin_param_start.setDecimals(3)
        self.spin_param_start.setValue(0.1)
        self.spin_param_end = QDoubleSpinBox()
        self.spin_param_end.setRange(-100, 100)
        self.spin_param_end.setDecimals(3)
        self.spin_param_end.setValue(3.0)

        # 速度滑块
        self.slider_speed = QSlider(Qt.Orientation.Horizontal)
        self.slider_speed.setRange(10, 300)
        self.slider_speed.setValue(50)
        self.label_speed_val = QLabel("50ms")
        self.slider_speed.valueChanged.connect(lambda v: self.label_speed_val.setText(f"{v}ms"))

        # ── 速度控制 ──
        speed_group = QGroupBox(t("animation.speed") or "Speed (frame interval)")
        speed_layout = QHBoxLayout(speed_group)
        speed_layout.addWidget(self.slider_speed)
        speed_layout.addWidget(self.label_speed_val)
        layout.addWidget(speed_group)

        # ── 播放控制 ──
        ctrl_group = QGroupBox(t("animation.controls") or "Controls")
        ctrl_layout = QHBoxLayout(ctrl_group)

        self.btn_play = QPushButton("▶")
        self.btn_play.setFixedWidth(40)
        self.btn_play.setStyleSheet(self._btn_style("#2d7a2d", "#1f5a1f"))
        self.btn_play.clicked.connect(self._on_play)

        self.btn_pause = QPushButton("⏸")
        self.btn_pause.setFixedWidth(40)
        self.btn_pause.setStyleSheet(self._btn_style("#7a7a2d", "#5a5a1f"))
        self.btn_pause.clicked.connect(self._on_pause)

        self.btn_stop = QPushButton("⏹")
        self.btn_stop.setFixedWidth(40)
        self.btn_stop.setStyleSheet(self._btn_style("#7a2d2d", "#5a1f1f"))
        self.btn_stop.clicked.connect(self._on_stop)

        ctrl_layout.addWidget(self.btn_play)
        ctrl_layout.addWidget(self.btn_pause)
        ctrl_layout.addWidget(self.btn_stop)
        layout.addWidget(ctrl_group)

        # ── 状态显示 ──
        self.label_status = QLabel(t("animation.status_ready") or "Status: Ready")
        self.label_status.setStyleSheet("color: #aaa; font-size: 12px;")
        layout.addWidget(self.label_status)

        # ── 提示 ──
        hint = QLabel(t("animation.hint") or "Tip: Select points on canvas first, then play.")
        hint.setStyleSheet("color: #777; font-size: 11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addStretch()

        # 初始参数显示 (必须在所有 UI 控件创建后调用，因为 _on_type_changed 会触发 _on_stop)
        self._on_type_changed(0)

        scroll.setWidget(inner)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _btn_style(self, bg: str, hover: str) -> str:
        return f"""
            QPushButton {{
                background-color: {bg};
                color: white;
                border-radius: 4px;
                padding: 6px;
                font-size: 14px;
            }}
            QPushButton:hover {{
                background-color: {hover};
            }}
            QPushButton:disabled {{
                background-color: #555;
                color: #aaa;
            }}
        """

    # ──────────────────────────────────────────────────────────────
    # 类型切换 — 动态重建参数区
    # ──────────────────────────────────────────────────────────────
    def _clear_param_layout(self):
        """清空参数布局但不删除控件本身 (removeRow 会删除控件 C++ 对象)"""
        while self.param_layout.count() > 0:
            item = self.param_layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)

    def _on_type_changed(self, index: int):
        self._clear_param_layout()
        self._on_stop()  # 切换类型时停止动画
        mode = self.combo_type.currentData()

        if mode == "translate":
            self.param_layout.addRow("Δx:", self.spin_tx)
            self.param_layout.addRow("Δy:", self.spin_ty)
            self.param_layout.addRow(t("animation.duration") or "Duration:", self.spin_duration)
        elif mode == "rotate":
            self.param_layout.addRow(t("animation.center_x") or "Center X:", self.spin_rot_cx)
            self.param_layout.addRow(t("animation.center_y") or "Center Y:", self.spin_rot_cy)
            self.param_layout.addRow(t("animation.angle") or "Angle:", self.spin_rot_angle)
            self.param_layout.addRow(t("animation.duration") or "Duration:", self.spin_duration)
        elif mode == "scale":
            self.param_layout.addRow(t("animation.center_x") or "Center X:", self.spin_scale_cx)
            self.param_layout.addRow(t("animation.center_y") or "Center Y:", self.spin_scale_cy)
            self.param_layout.addRow(t("animation.factor") or "Factor:", self.spin_scale_factor)
            self.param_layout.addRow(t("animation.duration") or "Duration:", self.spin_duration)
        elif mode == "param_func":
            self.param_layout.addRow(t("animation.expression") or "f(a,x):", self.input_func_expr)
            self.param_layout.addRow(t("animation.param_start") or "a start:", self.spin_param_start)
            self.param_layout.addRow(t("animation.param_end") or "a end:", self.spin_param_end)
            self.param_layout.addRow(t("animation.duration") or "Duration:", self.spin_duration)

    # ──────────────────────────────────────────────────────────────
    # 引擎访问
    # ──────────────────────────────────────────────────────────────
    def _get_engine(self):
        mw = getattr(self.api, "_main_window", None)
        return getattr(mw, "geometry_engine", None) if mw else None

    def _get_selected_points(self):
        """从几何引擎中获取所有 Point 类型的对象 ID"""
        engine = self._get_engine()
        if engine is None:
            return []
        points = engine.get_objects_by_type("Point")
        return [p.id for p in points]

    # ──────────────────────────────────────────────────────────────
    # 播放控制
    # ──────────────────────────────────────────────────────────────
    def _on_play(self):
        if self._is_playing:
            return

        mode = self.combo_type.currentData()
        engine = self._get_engine()
        if engine is None:
            self._set_status("Error: Engine not available")
            return

        if mode == "param_func":
            if not self._start_param_func(engine):
                return
        else:
            point_ids = self._get_selected_points()
            if not point_ids:
                self._set_status(t("animation.no_points") or "No points found on canvas.")
                return
            self._start_transform(engine, mode, point_ids)

        self._is_playing = True
        interval = self.slider_speed.value()
        self._timer.start(interval)
        self._set_status(t("animation.status_playing") or "Status: Playing...")

    def _on_pause(self):
        if self._timer.isActive():
            self._timer.stop()
            self._is_playing = False
            self._set_status(t("animation.status_paused") or "Status: Paused")

    def _on_stop(self):
        self._timer.stop()
        self._is_playing = False
        # 恢复原始位置
        engine = self._get_engine()
        if engine and self._anim_state["orig_coords"]:
            self._restore_originals(engine)
        self._anim_state["elapsed"] = 0.0
        self._set_status(t("animation.status_ready") or "Status: Ready")

    def _set_status(self, text: str):
        if hasattr(self, "label_status"):
            self.label_status.setText(text)

    # ──────────────────────────────────────────────────────────────
    # 动画启动
    # ──────────────────────────────────────────────────────────────
    def _start_transform(self, engine, mode: str, point_ids: list):
        """启动几何变换动画"""
        orig_coords = []
        for pid in point_ids:
            obj = engine.get_object(pid)
            if obj and obj.type == "Point":
                orig_coords.append((obj.coordinates.get("x", 0.0), obj.coordinates.get("y", 0.0)))
            else:
                orig_coords.append(None)

        self._anim_state.update(
            {
                "type": mode,
                "elapsed": 0.0,
                "duration": self.spin_duration.value(),
                "point_ids": point_ids,
                "orig_coords": orig_coords,
                "center": (
                    self.spin_rot_cx.value()
                    if mode == "rotate"
                    else self.spin_scale_cx.value() if mode == "scale" else (0.0, 0.0)
                ),
            }
        )
        if mode == "rotate":
            self._anim_state["center"] = (
                self.spin_rot_cx.value(),
                self.spin_rot_cy.value(),
            )
        elif mode == "scale":
            self._anim_state["center"] = (
                self.spin_scale_cx.value(),
                self.spin_scale_cy.value(),
            )

    def _start_param_func(self, engine):
        """启动函数参数动画。返回 True 表示成功启动，False 表示参数无效。"""
        expr_template = self.input_func_expr.text().strip()
        if not expr_template:
            self._set_status("Error: Please enter a function expression")
            return False

        # 如果之前有函数对象，先删除
        if self._anim_state.get("func_id"):
            try:
                engine.remove_object(self._anim_state["func_id"])
            except Exception:
                pass

        self._anim_state.update(
            {
                "type": "param_func",
                "elapsed": 0.0,
                "duration": self.spin_duration.value(),
                "func_expr": expr_template,
                "func_id": None,
            }
        )
        return True

    # ──────────────────────────────────────────────────────────────
    # 动画帧回调
    # ──────────────────────────────────────────────────────────────
    def _on_tick(self):
        interval_ms = self.slider_speed.value()
        dt = interval_ms / 1000.0
        self._anim_state["elapsed"] += dt

        progress = self._anim_state["elapsed"] / max(self._anim_state["duration"], 0.01)
        if progress >= 1.0:
            progress = 1.0
            self._timer.stop()
            self._is_playing = False
            self._set_status(t("animation.status_complete") or "Status: Complete")

        engine = self._get_engine()
        if engine is None:
            self._timer.stop()
            self._is_playing = False
            return

        # 使用 ease-in-out 缓动函数
        t_eased = self._ease_in_out(progress)

        mode = self._anim_state["type"]
        if mode == "translate":
            self._apply_translate(engine, t_eased)
        elif mode == "rotate":
            self._apply_rotate(engine, t_eased)
        elif mode == "scale":
            self._apply_scale(engine, t_eased)
        elif mode == "param_func":
            self._apply_param_func(engine, t_eased)

    @staticmethod
    def _ease_in_out(t: float) -> float:
        """缓动函数：ease-in-out (sinusoidal)"""
        return 0.5 * (1.0 - math.cos(math.pi * t))

    def _apply_translate(self, engine, t: float):
        dx = self.spin_tx.value() * t
        dy = self.spin_ty.value() * t
        point_ids = self._anim_state["point_ids"]
        orig_coords = self._anim_state["orig_coords"]

        engine.block_signals(True)
        for i, pid in enumerate(point_ids):
            orig = orig_coords[i]
            if orig is None:
                continue
            engine.update_point(pid, x=orig[0] + dx, y=orig[1] + dy)
        engine.block_signals(False)
        # 手动通知一次更新
        for i, pid in enumerate(point_ids):
            obj = engine.get_object(pid)
            if obj:
                engine._notify("object_updated", obj.serialize())

    def _apply_rotate(self, engine, t: float):
        total_angle = math.radians(self.spin_rot_angle.value()) * t
        cx, cy = self._anim_state["center"]
        cos_a = math.cos(total_angle)
        sin_a = math.sin(total_angle)
        point_ids = self._anim_state["point_ids"]
        orig_coords = self._anim_state["orig_coords"]

        engine.block_signals(True)
        for i, pid in enumerate(point_ids):
            orig = orig_coords[i]
            if orig is None:
                continue
            ox, oy = orig[0] - cx, orig[1] - cy
            new_x = cx + ox * cos_a - oy * sin_a
            new_y = cy + ox * sin_a + oy * cos_a
            engine.update_point(pid, x=new_x, y=new_y)
        engine.block_signals(False)
        for i, pid in enumerate(point_ids):
            obj = engine.get_object(pid)
            if obj:
                engine._notify("object_updated", obj.serialize())

    def _apply_scale(self, engine, t: float):
        factor = 1.0 + (self.spin_scale_factor.value() - 1.0) * t
        cx, cy = self._anim_state["center"]
        point_ids = self._anim_state["point_ids"]
        orig_coords = self._anim_state["orig_coords"]

        engine.block_signals(True)
        for i, pid in enumerate(point_ids):
            orig = orig_coords[i]
            if orig is None:
                continue
            new_x = cx + (orig[0] - cx) * factor
            new_y = cy + (orig[1] - cy) * factor
            engine.update_point(pid, x=new_x, y=new_y)
        engine.block_signals(False)
        for i, pid in enumerate(point_ids):
            obj = engine.get_object(pid)
            if obj:
                engine._notify("object_updated", obj.serialize())

    def _apply_param_func(self, engine, t: float):
        a_start = self.spin_param_start.value()
        a_end = self.spin_param_end.value()
        a_val = a_start + (a_end - a_start) * t
        expr_template = self._anim_state["func_expr"]

        # 替换参数 a 的值：必须使用词边界匹配，
        # 否则 atan/abs/tan 等函数名中的字母 a 也会被替换导致表达式损坏
        expr = re.sub(r"\ba\b", f"({a_val})", expr_template)

        # 删除旧的函数图并创建新的
        old_id = self._anim_state.get("func_id")
        if old_id:
            try:
                engine.remove_object(old_id)
            except Exception:
                pass

        try:
            new_id = engine.add_function_plot(expr, x_range=(-10, 10))
            self._anim_state["func_id"] = new_id
        except Exception as e:
            self.api.print_to_console(f"[Animation] Function plot error: {e}", "error")

    # ──────────────────────────────────────────────────────────────
    # 恢复与清理
    # ──────────────────────────────────────────────────────────────
    def _restore_originals(self, engine):
        """恢复点到动画前的位置"""
        point_ids = self._anim_state["point_ids"]
        orig_coords = self._anim_state["orig_coords"]

        engine.block_signals(True)
        for i, pid in enumerate(point_ids):
            orig = orig_coords[i]
            if orig is None:
                continue
            engine.update_point(pid, x=orig[0], y=orig[1])
        engine.block_signals(False)
        for i, pid in enumerate(point_ids):
            obj = engine.get_object(pid)
            if obj:
                engine._notify("object_updated", obj.serialize())

        self._anim_state["orig_coords"] = []
        self._anim_state["point_ids"] = []

    def cleanup(self):
        """面板销毁时清理资源"""
        self._timer.stop()
        self._is_playing = False
        engine = self._get_engine()
        if engine and self._anim_state["orig_coords"]:
            self._restore_originals(engine)
        # 清理函数参数动画创建的对象
        func_id = self._anim_state.get("func_id")
        if func_id and engine:
            try:
                engine.remove_object(func_id)
            except Exception:
                pass


class AnimationStudioPlugin(MathLabPlugin):
    name = "Animation Studio"
    version = "1.0.0"
    author = "MathLab Team"
    description = "Geometric transformation, function parameter, and trajectory animations."

    def __init__(self):
        self.api = None
        self.widget = None

    def on_activate(self, api: MathLabAPI):
        self.api = api
        self.widget = AnimationPanelWidget(api)
        api.add_sidebar_panel(t("plugins.animation_studio") or "Animation Studio", self.widget)

        # 注册命令
        api.register_command(
            id="animation.translate",
            title=t("animation.cmd_translate") or "Animation: Translation",
            action=lambda: self._quick_action("translate"),
            category="动画",
        )
        api.register_command(
            id="animation.rotate",
            title=t("animation.cmd_rotate") or "Animation: Rotation",
            action=lambda: self._quick_action("rotate"),
            category="动画",
        )
        api.register_command(
            id="animation.scale",
            title=t("animation.cmd_scale") or "Animation: Scaling",
            action=lambda: self._quick_action("scale"),
            category="动画",
        )
        api.register_command(
            id="animation.param_func",
            title=t("animation.cmd_param_func") or "Animation: Function Parameter",
            action=lambda: self._quick_action("param_func"),
            category="动画",
        )
        api.register_command(
            id="animation.stop",
            title=t("animation.cmd_stop") or "Animation: Stop",
            action=self._stop_animation,
            category="动画",
        )

        api.print_to_console("[Animation Studio] Plugin activated.", color_or_level="info")

    def _quick_action(self, mode: str):
        """命令面板快捷入口"""
        if self.widget is None:
            return
        idx = self.widget.combo_type.findData(mode)
        if idx >= 0:
            self.widget.combo_type.setCurrentIndex(idx)
        self.widget._on_play()

    def _stop_animation(self):
        if self.widget is not None:
            self.widget._on_stop()

    def on_deactivate(self):
        if self.widget is not None:
            self.widget.cleanup()
            self.widget = None
