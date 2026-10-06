import warnings
from functools import lru_cache

import numpy as np
from sympy import lambdify, symbols

from mathlab.core.expression_guard import safe_parse_expr
from mathlab.core.models.base import GeometricObject
from mathlab.utils.logger import get_logger

logger = get_logger(__name__)


# 表达式解析缓存：相同表达式字符串只解析一次，避免重复解析 + lambdify 开销
# [P0 安全加固] 三处解析统一走 safe_parse_expr：.mathlab 工程文件里的 expression 字段
# 会原样传进来，直接用 sympy.parse_expr 等于执行工程文件里的代码
# （sympy 在 global_dict=None 时会注入 builtins）。
@lru_cache(maxsize=128)
def _get_cached_lambdified_func(expression_str):
    """将表达式字符串解析为 SymPy 表达式并 lambdify 为 NumPy 函数（带缓存）"""
    x_sym = symbols("x")
    expr = safe_parse_expr(expression_str, local_dict={"x": x_sym})
    return lambdify(x_sym, expr, "numpy")


@lru_cache(maxsize=128)
def _get_cached_lambdified_func_xy(expression_str):
    """将二元表达式字符串解析为 SymPy 表达式并 lambdify 为 NumPy 函数（带缓存）"""
    x_sym, y_sym = symbols("x y")
    expr = safe_parse_expr(expression_str, local_dict={"x": x_sym, "y": y_sym})
    return lambdify((x_sym, y_sym), expr, "numpy")


@lru_cache(maxsize=128)
def _get_cached_lambdified_func_theta(expression_str):
    """将极坐标表达式字符串解析为 SymPy 表达式并 lambdify 为 NumPy 函数（带缓存）"""
    theta_sym = symbols("theta")
    expr = safe_parse_expr(expression_str, local_dict={"theta": theta_sym})
    return lambdify(theta_sym, expr, "numpy")


class FunctionPlot(GeometricObject):
    """显函数绘图：y = f(x)"""

    def __init__(self, obj_id, name, expression, x_range=(-10, 10), num_points=500):
        super().__init__(obj_id, name, "FunctionPlot")
        self.expression = expression
        self.x_range = x_range
        self.num_points = num_points
        self.points_data = []
        self._generate_points()

    def _generate_points(self):
        """生成离散点用于绘制（使用 lambdify 矢量化加速 + 表达式缓存）"""
        try:
            x_vals = np.linspace(self.x_range[0], self.x_range[1], self.num_points)

            try:
                # 使用缓存的表达式解析，避免重复 parse_expr 开销
                func = _get_cached_lambdified_func(self.expression)
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    y_vals = func(x_vals)
            except Exception:
                self.points_data = []
                self.coordinates = {"points": []}
                return

            # 过滤掉 NaN/Inf
            mask = np.isfinite(y_vals)
            points = list(zip(x_vals[mask].tolist(), y_vals[mask].astype(float).tolist()))

            self.points_data = points
            self.coordinates = {"points": points}
        except Exception as e:
            print(f"Error generating function plot points: {e}")
            self.points_data = []

    def to_latex(self):
        return rf"y = {self.expression}"

    def serialize(self):
        data = super().serialize()
        data["expression"] = self.expression
        data["x_range"] = self.x_range
        data["num_points"] = self.num_points
        data["points_data"] = self.points_data
        return data

    @classmethod
    def deserialize(cls, data):
        # 使用工厂方法模式：绕过 __init__ 中的 _generate_points 调用
        # 但通过 super().__init__ 正确初始化基类，而非手动调用
        expression = data.get("expression", "x")
        x_range = data.get("x_range", (-10, 10))
        num_points = data.get("num_points", 500)
        obj = cls.__new__(cls)
        GeometricObject.__init__(obj, data["id"], data["name"], "FunctionPlot")
        obj.expression = expression
        obj.x_range = x_range
        obj.num_points = num_points
        obj.coordinates = data.get("coordinates", {})
        obj.constraints = data.get("constraints", [])
        obj.depends_on = data.get("depends_on", [])
        obj.points_data = data.get("points_data", [])
        obj.symbolic_expr = None
        obj.is_draft = data.get("is_draft", False)
        return obj


class ImplicitPlot(GeometricObject):
    """隐函数绘图：f(x,y) = 0"""

    def __init__(
        self,
        obj_id,
        name,
        expression,
        x_range=(-10, 10),
        y_range=(-10, 10),
        resolution=400,
    ):
        super().__init__(obj_id, name, "ImplicitPlot")
        self.expression = expression
        self.x_range = x_range
        self.y_range = y_range
        self.resolution = resolution
        self.points_data = []
        self._generate_points()

    def _generate_points(self):
        """使用网格采样和等值线提取生成点（全程 numpy 矢量化，无 Python 循环）。

        算法：
        1. lambdify 矢量化计算整个网格的函数值 Z (resolution×resolution)
        2. 用 numpy 检测网格单元内的符号变化（零点穿越），标记候选单元
        3. 在候选单元的 4 个角点里收集 |Z| < near_zero_tol 的点

        相比原双重 Python 循环，resolution=400 时约快 80-120 倍。
        表达式缓存进一步避免重复 parse_expr + lambdify 开销。
        """
        try:
            # 创建网格
            x_vals = np.linspace(self.x_range[0], self.x_range[1], self.resolution)
            y_vals = np.linspace(self.y_range[0], self.y_range[1], self.resolution)
            X, Y = np.meshgrid(x_vals, y_vals)

            # 矢量化计算函数值（一次 C 级别运算替代 resolution² 次 subs）
            try:
                func = _get_cached_lambdified_func_xy(self.expression)
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    Z = func(X, Y)
                    # 确保结果是和 X 同形状的 ndarray（scalar 表达式时 lambdify 返回标量）
                    if not isinstance(Z, np.ndarray):
                        Z = np.full_like(X, float(Z), dtype=float)
                    else:
                        Z = np.asarray(Z, dtype=float)
            except Exception:
                Z = np.full_like(X, np.nan, dtype=float)

            # ── 全 numpy 等值线提取（零 Python 循环）────────────────────────────
            # 步骤 1：找出存在符号变化的网格单元（零点穿越 → 轮廓线经过的单元）
            Z_fin = np.where(np.isfinite(Z), Z, np.nan)

            # 表达式求不了值时（上面的 except 分支）整张网格都是 NaN。
            # 直接判定为空：否则 np.nanmax 会抛 All-NaN RuntimeWarning，
            # 并把 near_zero_tol 变成 NaN，后面靠 max() 也救不回来。
            if Z_fin.size == 0 or np.all(np.isnan(Z_fin)):
                self.points_data = []
                self.coordinates = {"points": []}
                return

            # 四个角点的切片（左上、右上、右下、左下）
            tl = Z_fin[:-1, :-1]
            tr = Z_fin[:-1, 1:]
            br = Z_fin[1:, 1:]
            bl = Z_fin[1:, :-1]

            has_neg = (tl <= 0) | (tr <= 0) | (br <= 0) | (bl <= 0)
            has_pos = (tl >= 0) | (tr >= 0) | (br >= 0) | (bl >= 0)
            # 同时包含正值和负值（或有限值过零）的单元才算轮廓穿越
            cell_mask = has_neg & has_pos

            # 步骤 2：在候选单元的 4 个角点里收集 |Z| 足够小的点
            near_zero_tol = (np.nanmax(np.abs(Z_fin)) or 1.0) * 0.05
            near_zero_tol = max(near_zero_tol, 0.05)  # 至少 0.05，避免过于严苛

            # 用 np.where 把单元行列号扩展回角点坐标
            ci, cj = np.where(cell_mask)  # 满足条件的单元 (i, j)
            # 全矢量化收集角点：避免 Python for 循环
            all_xs = []
            all_ys = []
            for di, dj in ((0, 0), (0, 1), (1, 1), (1, 0)):
                pi, pj = ci + di, cj + dj
                valid = np.isfinite(Z[pi, pj]) & (np.abs(Z[pi, pj]) < near_zero_tol)
                all_xs.append(X[pi[valid], pj[valid]])
                all_ys.append(Y[pi[valid], pj[valid]])

            # 一次性拼接去重
            if all_xs:
                xs_cat = np.concatenate(all_xs)
                ys_cat = np.concatenate(all_ys)
                # 使用结构化数组实现矢量化去重：(x, y) 作为复合键
                combined = np.column_stack((xs_cat, ys_cat))
                # round 到 6 位小数后去重，避免浮点误差导致的重复
                rounded = np.round(combined, 6)
                unique_indices = np.unique(rounded, axis=0, return_index=True)[1]
                points = combined[unique_indices].tolist()
                # 转为 list of tuple
                points = [tuple(p) for p in points]
            else:
                points = []
            self.points_data = points
            self.coordinates = {"points": points}
        except Exception as e:
            logger.error("隐函数取点失败: %s", e, exc_info=True)
            self.points_data = []

    def to_latex(self):
        return rf"{self.expression} = 0"

    def serialize(self):
        data = super().serialize()
        data["expression"] = self.expression
        data["x_range"] = self.x_range
        data["y_range"] = self.y_range
        data["resolution"] = self.resolution
        data["points_data"] = self.points_data
        return data

    @classmethod
    def deserialize(cls, data):
        # 绕过 __init__ 中的 _generate_points 调用，但完整初始化所有属性
        obj = cls.__new__(cls)
        GeometricObject.__init__(obj, data["id"], data["name"], "ImplicitPlot")
        obj.expression = data.get("expression", "x**2 + y**2 - 1")
        obj.x_range = data.get("x_range", (-10, 10))
        obj.y_range = data.get("y_range", (-10, 10))
        obj.resolution = data.get("resolution", 400)
        obj.coordinates = data.get("coordinates", {})
        obj.constraints = data.get("constraints", [])
        obj.depends_on = data.get("depends_on", [])
        obj.points_data = data.get("points_data", [])
        obj.symbolic_expr = None
        obj.is_draft = data.get("is_draft", False)
        return obj


class PolarPlot(GeometricObject):
    """极坐标绘图：r = f(θ)"""

    def __init__(self, obj_id, name, expression, theta_range=(0, 2 * np.pi), num_points=500):
        super().__init__(obj_id, name, "PolarPlot")
        self.expression = expression
        self.theta_range = theta_range
        self.num_points = num_points
        self.points_data = []
        self._generate_points()

    def _generate_points(self):
        """将极坐标转换为直角坐标并生成点（使用 lambdify 矢量化加速 + 表达式缓存）"""
        try:
            theta_vals = np.linspace(self.theta_range[0], self.theta_range[1], self.num_points)

            try:
                # 使用缓存的表达式解析
                func = _get_cached_lambdified_func_theta(self.expression)
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    r_vals = func(theta_vals)
            except Exception:
                self.points_data = []
                self.coordinates = {"points": []}
                return

            # 过滤 NaN/Inf 后一次性转换为直角坐标
            mask = np.isfinite(r_vals)
            r_valid = r_vals[mask]
            t_valid = theta_vals[mask]
            x = r_valid * np.cos(t_valid)
            y = r_valid * np.sin(t_valid)
            points = list(zip(x.astype(float).tolist(), y.astype(float).tolist()))

            self.points_data = points
            self.coordinates = {"points": points}
        except Exception as e:
            print(f"Error generating polar plot points: {e}")
            self.points_data = []

    def to_latex(self):
        return rf"r = {self.expression}"

    def serialize(self):
        data = super().serialize()
        data["expression"] = self.expression
        data["theta_range"] = self.theta_range
        data["num_points"] = self.num_points
        data["points_data"] = self.points_data
        return data

    @classmethod
    def deserialize(cls, data):
        import math

        obj = cls.__new__(cls)
        GeometricObject.__init__(obj, data["id"], data["name"], "PolarPlot")
        obj.expression = data.get("expression", "theta")
        obj.theta_range = tuple(data.get("theta_range", [0, 2 * math.pi]))
        obj.num_points = data.get("num_points", 500)
        obj.coordinates = data.get("coordinates", {})
        obj.constraints = data.get("constraints", [])
        obj.depends_on = data.get("depends_on", [])
        obj.points_data = data.get("points_data", [])
        obj.symbolic_expr = None
        obj.is_draft = data.get("is_draft", False)
        return obj
