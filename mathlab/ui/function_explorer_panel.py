"""
Dynamic Function Explorer Panel - 动态函数探索器 (微积分强力驱动版)

功能:
1. 函数绘图: 支持输入函数解析式并绘制
2. 参数滑块: 对含参数的函数生成滑块,实时更新图象
3. 图象变换: 展示基础函数的平移、伸缩等变换
4. 高阶分析: 结合 C# 底层引擎实现秒级自适应积分(求面积)与求导(切线)
"""

import re

import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QDoubleValidator, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDockWidget,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from mathlab.utils.i18n_manager import t

# 尝试引入我们的智能微积分求解器 (如果是通过依赖注入或外层调用，也可仅发射信号)
try:
    import sympy as sp

    from mathlab.core.cs_calculus_engine import cs_calculus

    HAS_CALCULUS_ENGINE = True
except ImportError:
    HAS_CALCULUS_ENGINE = False


class ParameterSlider(QWidget):
    """单个参数滑块控件"""

    value_changed = Signal(str, float)  # param_name, value

    def __init__(
        self,
        param_name: str,
        min_val: float = -10.0,
        max_val: float = 10.0,
        default_val: float = 1.0,
        parent=None,
    ):
        super().__init__(parent)
        self.param_name = param_name
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(4)
        header_layout = QHBoxLayout()
        self.name_label = QLabel(f"{param_name} =")
        self.name_label.setFont(QFont("Consolas", 10))
        self.value_label = QLabel(f"{default_val:.2f}")
        self.value_label.setFont(QFont("Consolas", 10, QFont.Bold))
        self.value_label.setStyleSheet("color: #004ac6;")
        header_layout.addWidget(self.name_label)
        header_layout.addStretch()
        header_layout.addWidget(self.value_label)
        layout.addLayout(header_layout)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(int(min_val * 100), int(max_val * 100))
        self.slider.setValue(int(default_val * 100))
        self.slider.setTickPosition(QSlider.TicksBelow)
        self.slider.setTickInterval(int((max_val - min_val) * 10))
        self.slider.valueChanged.connect(self._on_slider_changed)
        layout.addWidget(self.slider)

    def _on_slider_changed(self, value: int):
        float_value = value / 100.0
        self.value_label.setText(f"{float_value:.2f}")
        self.value_changed.emit(self.param_name, float_value)

    def get_value(self) -> float:
        return self.slider.value() / 100.0

    def set_value(self, value: float):
        self.slider.setValue(int(value * 100))


class FunctionExplorerPanel(QDockWidget):
    """动态函数探索器面板"""

    function_added = Signal(dict)
    function_updated = Signal(str, dict)

    # === 新增：微积分交互信号 ===
    # 请求绘制阴影面积: 参数为 (表达式, 下限 a, 上限 b, 面积结果)
    render_integral_area = Signal(str, float, float, float)
    # 请求绘制切线: 参数为 (表达式, 切点 x, 切线斜率 k)
    render_tangent_line = Signal(str, float, float)

    def __init__(self, parent=None):
        super().__init__(t("function_explorer.title"), parent)
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.setMinimumWidth(320)  # 稍微加宽以容纳新的微积分面板

        self.current_function_id = None
        self.parameter_sliders = {}
        self.function_type = "explicit"

        # 参数滑块节流：一次拖动会产生上百次 valueChanged，
        # 合并为 ~80ms 一次的重算/重绘，避免反复重建几何对象造成卡顿
        self._param_update_timer = QTimer(self)
        self._param_update_timer.setSingleShot(True)
        self._param_update_timer.setInterval(80)
        self._param_update_timer.timeout.connect(self._apply_parameter_update)

        self._build_ui()

    def _build_ui(self):
        """构建UI界面"""
        container = QWidget()
        container.setObjectName("function_explorer_container")
        main_layout = QVBoxLayout(container)
        main_layout.setContentsMargins(12, 10, 12, 10)
        main_layout.setSpacing(12)

        # === 1. 函数类型选择 ===
        type_group = QGroupBox(t("function_explorer.function_type"))
        type_layout = QVBoxLayout(type_group)
        self.type_combo = QComboBox()
        self.type_combo.addItems(
            [
                t("function_explorer.explicit"),
                t("function_explorer.implicit"),
                t("function_explorer.polar"),
            ]
        )
        self.type_combo.setItemData(0, "explicit")
        self.type_combo.setItemData(1, "implicit")
        self.type_combo.setItemData(2, "polar")
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        type_layout.addWidget(self.type_combo)
        main_layout.addWidget(type_group)

        # === 2. 函数表达式输入 ===
        expr_group = QGroupBox(t("function_explorer.expression"))
        expr_layout = QVBoxLayout(expr_group)
        self.example_label = QLabel(t("function_explorer.example_explicit"))
        self.example_label.setStyleSheet("color: #737686; font-size: 11px;")
        expr_layout.addWidget(self.example_label)
        self.expr_input = QLineEdit()
        self.expr_input.setPlaceholderText(t("function_explorer.enter_expression"))
        self.expr_input.setFont(QFont("Consolas", 11))
        self.expr_input.returnPressed.connect(self.on_plot_function)
        expr_layout.addWidget(self.expr_input)
        self.plot_btn = QPushButton(t("function_explorer.plot"))
        self.plot_btn.setStyleSheet(
            "QPushButton { background: #004ac6; color: white; border: none; padding: 8px; border-radius: 4px; font-weight: 600; } QPushButton:hover { background: #2563eb; }"
        )
        self.plot_btn.clicked.connect(self.on_plot_function)
        expr_layout.addWidget(self.plot_btn)
        main_layout.addWidget(expr_group)

        # === 3. 参数滑块区域 ===
        self.params_group = QGroupBox(t("function_explorer.parameters"))
        params_layout = QVBoxLayout(self.params_group)
        self.params_scroll = QScrollArea()
        self.params_scroll.setWidgetResizable(True)
        self.params_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.params_container = QWidget()
        self.params_container_layout = QVBoxLayout(self.params_container)
        self.params_scroll.setWidget(self.params_container)
        params_layout.addWidget(self.params_scroll)
        main_layout.addWidget(self.params_group)
        self.params_group.setVisible(False)

        # === 4. 图象变换 ===
        transform_group = QGroupBox(t("function_explorer.transformations"))
        transform_layout = QVBoxLayout(transform_group)

        # 变换按钮行1: 平移
        trans_row1 = QHBoxLayout()
        self.shift_left_btn = QPushButton("← " + t("function_explorer.shift_left"))
        self.shift_right_btn = QPushButton(t("function_explorer.shift_right") + " →")
        self.shift_up_btn = QPushButton("↑ " + t("function_explorer.shift_up"))
        self.shift_down_btn = QPushButton(t("function_explorer.shift_down") + " ↓")

        for btn in [
            self.shift_left_btn,
            self.shift_right_btn,
            self.shift_up_btn,
            self.shift_down_btn,
        ]:
            btn.setFixedSize(80, 32)
            btn.setStyleSheet(
                "QPushButton { background: #eff4ff; border: 1px solid #d3e4fe; border-radius: 4px; font-size: 11px; } QPushButton:hover { background: #d3e4fe; }"
            )

        trans_row1.addWidget(self.shift_left_btn)
        trans_row1.addWidget(self.shift_right_btn)
        trans_row1.addWidget(self.shift_up_btn)
        trans_row1.addWidget(self.shift_down_btn)
        transform_layout.addLayout(trans_row1)

        # 变换按钮行2: 伸缩
        trans_row2 = QHBoxLayout()
        self.scale_x_btn = QPushButton(t("function_explorer.scale_x"))
        self.scale_y_btn = QPushButton(t("function_explorer.scale_y"))
        self.reflect_x_btn = QPushButton(t("function_explorer.reflect_x"))
        self.reflect_y_btn = QPushButton(t("function_explorer.reflect_y"))

        for btn in [
            self.scale_x_btn,
            self.scale_y_btn,
            self.reflect_x_btn,
            self.reflect_y_btn,
        ]:
            btn.setFixedSize(80, 32)
            btn.setStyleSheet(
                "QPushButton { background: #eff4ff; border: 1px solid #d3e4fe; border-radius: 4px; font-size: 11px; } QPushButton:hover { background: #d3e4fe; }"
            )

        trans_row2.addWidget(self.scale_x_btn)
        trans_row2.addWidget(self.scale_y_btn)
        trans_row2.addWidget(self.reflect_x_btn)
        trans_row2.addWidget(self.reflect_y_btn)
        transform_layout.addLayout(trans_row2)

        # 连接变换信号
        self.shift_left_btn.clicked.connect(lambda: self._apply_transform("shift", -1, 0))
        self.shift_right_btn.clicked.connect(lambda: self._apply_transform("shift", 1, 0))
        self.shift_up_btn.clicked.connect(lambda: self._apply_transform("shift", 0, 1))
        self.shift_down_btn.clicked.connect(lambda: self._apply_transform("shift", 0, -1))
        self.scale_x_btn.clicked.connect(lambda: self._apply_transform("scale", 1.5, 1))
        self.scale_y_btn.clicked.connect(lambda: self._apply_transform("scale", 1, 1.5))
        self.reflect_x_btn.clicked.connect(lambda: self._apply_transform("reflect", -1, 1))
        self.reflect_y_btn.clicked.connect(lambda: self._apply_transform("reflect", 1, -1))

        main_layout.addWidget(transform_group)

        # === 5. 全新：微积分与高阶分析引擎 (Calculus & Analysis) ===
        calc_group = QGroupBox("⚡ 微积分与高阶分析 (C# 驱动)")
        calc_layout = QVBoxLayout(calc_group)

        # 5.1 定积分计算 (面积填充)
        int_row1 = QHBoxLayout()
        int_row1.addWidget(QLabel("∫ 面积自适应积分：从"))

        self.int_a_input = QLineEdit()
        self.int_a_input.setPlaceholderText("a")
        self.int_a_input.setFixedWidth(50)
        self.int_a_input.setValidator(QDoubleValidator())

        int_row1.addWidget(self.int_a_input)
        int_row1.addWidget(QLabel("到"))

        self.int_b_input = QLineEdit()
        self.int_b_input.setPlaceholderText("b")
        self.int_b_input.setFixedWidth(50)
        self.int_b_input.setValidator(QDoubleValidator())

        int_row1.addWidget(self.int_b_input)
        calc_layout.addLayout(int_row1)

        int_row2 = QHBoxLayout()
        self.calc_int_btn = QPushButton("计算面积并填充阴影")
        self.calc_int_btn.setStyleSheet("background-color: #e0f2fe; color: #0284c7; border-radius: 4px; padding: 4px;")
        self.calc_int_btn.clicked.connect(self._on_calculate_integral)
        int_row2.addWidget(self.calc_int_btn)

        self.int_result_label = QLabel("面积 = -")
        self.int_result_label.setFont(QFont("Consolas", 10, QFont.Bold))
        self.int_result_label.setStyleSheet("color: #d97706;")
        int_row2.addWidget(self.int_result_label)
        calc_layout.addLayout(int_row2)

        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        calc_layout.addWidget(line)

        # 5.2 微分计算 (动态切线)
        deriv_row1 = QHBoxLayout()
        deriv_row1.addWidget(QLabel("∂ 动态切线：在 x ="))

        self.deriv_x_input = QLineEdit()
        self.deriv_x_input.setPlaceholderText("x0")
        self.deriv_x_input.setFixedWidth(60)
        self.deriv_x_input.setValidator(QDoubleValidator())
        deriv_row1.addWidget(self.deriv_x_input)
        deriv_row1.addStretch()
        calc_layout.addLayout(deriv_row1)

        deriv_row2 = QHBoxLayout()
        self.calc_deriv_btn = QPushButton("计算切线并绘制")
        self.calc_deriv_btn.setStyleSheet(
            "background-color: #fce7f3; color: #be185d; border-radius: 4px; padding: 4px;"
        )
        self.calc_deriv_btn.clicked.connect(self._on_calculate_tangent)
        deriv_row2.addWidget(self.calc_deriv_btn)

        self.deriv_result_label = QLabel("斜率 k = -")
        self.deriv_result_label.setFont(QFont("Consolas", 10, QFont.Bold))
        self.deriv_result_label.setStyleSheet("color: #be185d;")
        deriv_row2.addWidget(self.deriv_result_label)
        calc_layout.addLayout(deriv_row2)

        main_layout.addWidget(calc_group)
        main_layout.addStretch()
        self.setWidget(container)

    # === 微积分事件响应槽函数 ===

    def _get_evaluated_expression(self):
        """将当前面板上的参数 (如 a, b) 替换为具体数值，供引擎计算"""
        expr = self.expr_input.text().strip()
        if not expr:
            return None
        # 简单替换
        for pname, pslider in self.parameter_sliders.items():
            val = pslider.get_value()
            expr = re.sub(r"\b" + re.escape(pname) + r"\b", f"({val})", expr)
        return expr

    def _on_calculate_integral(self):
        """触发计算定积分并绘图"""
        if not HAS_CALCULUS_ENGINE:
            QMessageBox.information(self, "提示", "请先在核心引擎中启用 C# 微积分模块。")
            return

        expr = self._get_evaluated_expression()
        a_str, b_str = self.int_a_input.text(), self.int_b_input.text()

        if not expr or not a_str or not b_str:
            QMessageBox.warning(self, "参数不全", "请确保已输入函数表达式，以及积分上下限 a 和 b。")
            return

        try:
            a, b = float(a_str), float(b_str)
            # 1. 编译为极速 Python 字节码函数
            x = sp.Symbol("x")
            sp_expr = sp.sympify(expr)
            fast_func = sp.lambdify(x, sp_expr, modules=["math"])

            # 2. 呼叫 C# 引擎秒算高斯-克朗罗德积分
            self.int_result_label.setText("计算中...")
            area_val = cs_calculus.integrate_adaptive(fast_func, a, b, tol=1e-8)

            # 3. 更新 UI
            self.int_result_label.setText(f"面积 ≈ {area_val:.5f}")

            # 4. 发射信号让 Canvas 画布去填充阴影！
            self.render_integral_area.emit(expr, a, b, area_val)

        except Exception as e:
            self.int_result_label.setText("计算错误")
            QMessageBox.critical(self, "计算失败", f"积分计算失败: {str(e)}")

    def _on_calculate_tangent(self):
        """触发计算切线并绘图"""
        if not HAS_CALCULUS_ENGINE:
            QMessageBox.information(self, "提示", "请先在核心引擎中启用 C# 微积分模块。")
            return

        expr = self._get_evaluated_expression()
        x0_str = self.deriv_x_input.text()

        if not expr or not x0_str:
            QMessageBox.warning(self, "参数不全", "请确保已输入函数表达式及切点坐标 x0。")
            return

        try:
            x0 = float(x0_str)
            x = sp.Symbol("x")
            sp_expr = sp.sympify(expr)
            fast_func = sp.lambdify(x, sp_expr, modules=["math"])

            # 1. 调用 C# 引擎计算在 x0 处的导数 (斜率)
            self.deriv_result_label.setText("计算中...")
            slope_k = cs_calculus.differentiate(fast_func, x0)

            # 2. 计算出具体函数值 y0
            y0 = fast_func(x0)

            # 3. 更新 UI
            self.deriv_result_label.setText(f"k ≈ {slope_k:.3f}")

            # 4. 发射信号，通知 Canvas 画出这根神奇的切线！
            # 切线方程 y - y0 = k(x - x0)
            self.render_tangent_line.emit(expr, x0, slope_k)

        except Exception as e:
            self.deriv_result_label.setText("计算错误")
            QMessageBox.critical(self, "计算失败", f"求导失败: {str(e)}")

    def _on_type_changed(self, index: int):
        """函数类型改变时更新示例提示"""
        type_data = self.type_combo.itemData(index)
        examples = {
            "explicit": t("function_explorer.example_explicit"),
            "implicit": t("function_explorer.example_implicit"),
            "polar": t("function_explorer.example_polar"),
        }
        self.example_label.setText(examples.get(type_data, ""))

    def _on_template_selected(self, index: int):
        """选择预设模板"""
        if not hasattr(self, "template_combo"):
            return
        expression = self.template_combo.itemData(index)
        if expression:
            self.expr_input.setText(expression)
            self.on_plot_function()

    def _extract_parameters(self, expression: str) -> list:
        """从表达式中提取参数(非常数变量)"""
        # 已知变量
        known_vars = {
            "x",
            "y",
            "theta",
            "pi",
            "e",
            "sin",
            "cos",
            "tan",
            "exp",
            "log",
            "sqrt",
            "abs",
        }

        # 使用正则提取所有字母标识符
        identifiers = re.findall(r"\b([a-zA-Z_]\w*)\b", expression)

        # 过滤出参数(非常量、非常见函数)
        params = []
        for ident in identifiers:
            if ident not in known_vars and ident not in params:
                params.append(ident)

        return params

    def on_plot_function(self):
        """绘制函数"""
        expression = self.expr_input.text().strip()
        if not expression:
            QMessageBox.warning(self, t("dialogs.warning"), t("function_explorer.empty_expression"))
            return

        # 确定函数类型
        func_type = self.type_combo.currentData()

        # 提取参数
        params = self._extract_parameters(expression)

        # 生成函数对象
        func_data = {
            "type": func_type,
            "expression": expression,
            "parameters": {p: 1.0 for p in params},  # 默认值为1.0
            "x_range": (-10, 10),
            "y_range": (-10, 10),
        }

        # 如果是显函数,添加到画布
        if func_type == "explicit":
            func_data["plot_type"] = "FunctionPlot"
        elif func_type == "implicit":
            func_data["plot_type"] = "ImplicitPlot"
        elif func_type == "polar":
            func_data["plot_type"] = "PolarPlot"

        # 发射信号
        self.function_added.emit(func_data)

        # 创建参数滑块
        self._create_parameter_sliders(params)

    def _create_parameter_sliders(self, params: list):
        """为参数创建滑块控件"""
        # 清除旧滑块
        for slider_widget in list(self.parameter_sliders.values()):
            self.params_container_layout.removeWidget(slider_widget)
            slider_widget.deleteLater()
        self.parameter_sliders.clear()

        # 创建新滑块
        for param_name in params:
            slider = ParameterSlider(param_name, min_val=-10.0, max_val=10.0, default_val=1.0)
            slider.value_changed.connect(self._on_parameter_changed)
            self.parameter_sliders[param_name] = slider
            self.params_container_layout.insertWidget(self.params_container_layout.count() - 1, slider)

        # 显示/隐藏参数组
        self.params_group.setVisible(len(params) > 0)

    def _on_parameter_changed(self, param_name: str, value: float):
        """参数值改变（高频触发）：仅重启节流定时器，不立即重算重绘。"""
        if not self.expr_input.text():
            return
        self._param_update_timer.start()

    def _apply_parameter_update(self):
        """节流后的参数更新：替换表达式中的参数值并请求重绘。"""
        if not self.expr_input.text():
            return

        # 替换表达式中的参数值
        expression = self.expr_input.text()

        # 简单的参数替换(实际应该用更安全的解析)
        try:
            # 将参数名替换为数值
            modified_expr = expression
            for pname, pval in self.parameter_sliders.items():
                val = pval.get_value()
                # 使用正则确保完整匹配参数名
                modified_expr = re.sub(r"\b" + re.escape(pname) + r"\b", f"({val})", modified_expr)

            # 重新绘制
            func_data = {
                "type": self.type_combo.currentData(),
                "expression": modified_expr,
                "original_expression": expression,
                "parameters": {p: s.get_value() for p, s in self.parameter_sliders.items()},
                "x_range": (-10, 10),
                "y_range": (-10, 10),
            }

            if self.type_combo.currentData() == "explicit":
                func_data["plot_type"] = "FunctionPlot"
            elif self.type_combo.currentData() == "implicit":
                func_data["plot_type"] = "ImplicitPlot"
            elif self.type_combo.currentData() == "polar":
                func_data["plot_type"] = "PolarPlot"

            # [P0修复 Bug4] 发射信号时，带上具体的 func_id
            if self.current_function_id:
                self.function_updated.emit(self.current_function_id, func_data)
        except Exception as e:
            print(f"Error updating function: {e}")

    def _apply_transform(self, transform_type: str, factor_x: float, factor_y: float):
        """应用图象变换"""
        expression = self.expr_input.text().strip()
        if not expression:
            return

        try:
            transformed_expr = expression

            if transform_type == "shift":
                # 平移: f(x-a) + b
                if factor_x != 0:
                    # 水平平移: x -> (x - shift)，使用正则整词匹配避免替换 exp、max 等
                    shift = factor_x
                    transformed_expr = re.sub(r"\bx\b", f"(x - {shift})", transformed_expr)
                if factor_y != 0:
                    # 垂直平移: f(x) + shift
                    shift = factor_y
                    transformed_expr = f"({transformed_expr}) + {shift}"

            elif transform_type == "scale":
                # 伸缩: f(ax) * b
                if factor_x != 1:
                    # 水平伸缩: x -> x/a，使用正则整词匹配
                    transformed_expr = re.sub(r"\bx\b", f"(x / {factor_x})", transformed_expr)
                if factor_y != 1:
                    # 垂直伸缩: f(x) * b
                    transformed_expr = f"{factor_y} * ({transformed_expr})"

            elif transform_type == "reflect":
                # 反射
                if factor_x == -1:
                    # 关于y轴反射: x -> -x，使用正则整词匹配
                    transformed_expr = re.sub(r"\bx\b", "(-x)", transformed_expr)
                if factor_y == -1:
                    # 关于x轴反射: f(x) -> -f(x)
                    transformed_expr = f"-({transformed_expr})"

            # 更新表达式并重新绘制
            self.expr_input.setText(transformed_expr)
            self.on_plot_function()

        except Exception as e:
            QMessageBox.warning(
                self,
                t("dialogs.warning"),
                f"{t('function_explorer.transform_error')}: {str(e)}",
            )

    def clear_sliders(self):
        """清除所有滑块"""
        for slider_widget in list(self.parameter_sliders.values()):
            self.params_container_layout.removeWidget(slider_widget)
            slider_widget.deleteLater()
        self.parameter_sliders.clear()
        self.params_group.setVisible(False)

    def retranslate_ui(self):
        """国际化支持"""
        self.setWindowTitle(t("function_explorer.title"))

        # 需要重新翻译的文本
        # 由于使用了组合框和按钮,这里只更新标题
        # 其他文本在创建时已经翻译
