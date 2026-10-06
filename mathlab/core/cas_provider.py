import functools
import re
import threading
from typing import TYPE_CHECKING, Any

from mathlab.core.cs_calculus_engine import cs_calculus
from mathlab.core.expression_guard import (
    default_transformations,
    safe_parse_expr,
    safe_sympify,
)

try:
    from mathlab.utils.logger import get_logger

    logger = get_logger(__name__)
except ImportError:
    import logging

    logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import sympy as _sympy  # noqa: F401

_sympy_lock = threading.Lock()
_sympy_loaded = False

# 使用模块级字典安全存储 sympy 对象，避免污染全局命名空间
_sympy_modules: dict[str, Any] = {}


def _load_sympy():
    """延迟加载 sympy 并将组件存入隔离字典，而非 globals()。"""
    global _sympy_loaded
    if _sympy_loaded:
        return
    with _sympy_lock:
        if _sympy_loaded:
            return
        import sympy  # noqa: F811
        from sympy import (  # noqa: F401
            Eq,
            Symbol,
            diff,
            expand,
            factor,
            integrate,
            latex,
            limit,
            simplify,
            solve,
            symbols,
        )

        _sympy_modules.update(
            {
                "sympy": sympy,
                "symbols": symbols,
                "Symbol": Symbol,
                "Eq": Eq,
                "solve": solve,
                "simplify": simplify,
                "expand": expand,
                "factor": factor,
                "diff": diff,
                "integrate": integrate,
                "limit": limit,
                "latex": latex,
            }
        )
        _sympy_loaded = True


def _get_sympy_func(name: str) -> Any:
    """从隔离字典中安全获取 sympy 函数。"""
    _load_sympy()
    if name not in _sympy_modules:
        raise AttributeError(f"sympy 函数 '{name}' 未加载")
    return _sympy_modules[name]


@functools.lru_cache(maxsize=1024)
def _cached_sympify(expr_str):
    # [P0 安全加固] 原实现直接 sympify(expr_str)：sympify 对字符串会走注入 builtins 的
    # parse_expr，"__import__('os').getpid()" 这类表达式会被真的执行。
    return safe_sympify(expr_str)


@functools.lru_cache(maxsize=1024)
def _cached_parse_expr(expr_str):
    # [P0 安全加固] 同上，parse_expr 不传 global_dict 时同样注入 builtins
    return safe_parse_expr(expr_str)


class CASProvider:
    def __init__(self):
        self.symbols_cache = {}
        self._cache_lock = threading.Lock()

    def _get_symbol(self, name):
        _load_sympy()
        sympy = _get_sympy_func("sympy")
        Symbol = _get_sympy_func("Symbol")
        with self._cache_lock:
            if name in self.symbols_cache:
                return self.symbols_cache[name]

            if hasattr(sympy, name):
                return getattr(sympy, name)

            self.symbols_cache[name] = Symbol(name)
            return self.symbols_cache[name]

    def parse_expression(self, expr_str):
        _load_sympy()
        sympy = _get_sympy_func("sympy")
        try:
            result = _cached_sympify(expr_str)
            with self._cache_lock:
                for symbol in result.free_symbols:
                    sym_name = str(symbol)
                    if not hasattr(sympy, sym_name):
                        self.symbols_cache[sym_name] = symbol
            return result
        except Exception:
            return None

    def simplify(self, expr_str):
        expr = self.parse_expression(expr_str)
        if expr is None:
            return {"success": False, "error": "Invalid expression"}
        result = _get_sympy_func("simplify")(expr)
        return {
            "success": True,
            "latex": _get_sympy_func("latex")(result),
            "result": str(result),
        }

    def expand(self, expr_str):
        expr = self.parse_expression(expr_str)
        if expr is None:
            return {"success": False, "error": "Invalid expression"}
        result = _get_sympy_func("expand")(expr)
        return {
            "success": True,
            "latex": _get_sympy_func("latex")(result),
            "result": str(result),
        }

    def factor(self, expr_str):
        expr = self.parse_expression(expr_str)
        if expr is None:
            return {"success": False, "error": "Invalid expression"}
        result = _get_sympy_func("factor")(expr)
        return {
            "success": True,
            "latex": _get_sympy_func("latex")(result),
            "result": str(result),
        }

    def solve_equation(self, equation_str, variable="x"):
        try:
            x = self._get_symbol(variable)
            sympy = _get_sympy_func("sympy")
            Eq = _get_sympy_func("Eq")
            solve = _get_sympy_func("solve")
            latex = _get_sympy_func("latex")

            # 使用正则表达式精确匹配单个等号，排除 >=, <=, ==
            match = re.search(r"(?<![<>])=(?![<>=])", equation_str)
            if match:
                left_str = equation_str[: match.start()]
                right_str = equation_str[match.end() :]
                left_expr = _cached_sympify(left_str.strip())
                right_expr = _cached_sympify(right_str.strip())
                eq = Eq(left_expr, right_expr)
            else:
                left_expr = _cached_sympify(equation_str.strip())
                eq = Eq(left_expr, 0)

            solutions = solve(eq, x)
            for symbol in left_expr.free_symbols:
                sym_name = str(symbol)
                if not hasattr(sympy, sym_name):
                    self.symbols_cache[sym_name] = symbol
            return {
                "success": True,
                "solutions": [latex(s) for s in solutions],
                "raw_solutions": solutions,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def differentiate(self, expr_str, variable="x"):
        x = self._get_symbol(variable)
        expr = self.parse_expression(expr_str)
        if expr is None:
            return {"success": False, "error": "Invalid expression"}
        result = _get_sympy_func("diff")(expr, x)
        return {
            "success": True,
            "latex": _get_sympy_func("latex")(result),
            "result": str(result),
        }

    def integrate(self, expr_str, variable="x"):
        x = self._get_symbol(variable)
        expr = self.parse_expression(expr_str)
        if expr is None:
            return {"success": False, "error": "Invalid expression"}
        result = _get_sympy_func("integrate")(expr, x)
        return {
            "success": True,
            "latex": _get_sympy_func("latex")(result),
            "result": str(result),
        }

    def definite_integral(self, expr_str, variable="x", lower=0, upper=1):
        x = self._get_symbol(variable)
        expr = self.parse_expression(expr_str)
        if expr is None:
            return {"success": False, "error": "Invalid expression"}
        result = _get_sympy_func("integrate")(expr, (x, lower, upper))
        return {
            "success": True,
            "latex": _get_sympy_func("latex")(result),
            "result": str(result),
            "numeric": float(result) if result.is_number else None,
        }

    def limit(self, expr_str, variable="x", point=0):
        x = self._get_symbol(variable)
        expr = self.parse_expression(expr_str)
        if expr is None:
            return {"success": False, "error": "Invalid expression"}
        result = _get_sympy_func("limit")(expr, x, point)
        return {
            "success": True,
            "latex": _get_sympy_func("latex")(result),
            "result": str(result),
        }

    def evaluate(self, expr_str):
        expr = self.parse_expression(expr_str)
        if expr is None:
            return {"success": False, "error": "Invalid expression"}
        try:
            result = expr.evalf()
            return {
                "success": True,
                "latex": _get_sympy_func("latex")(result),
                "result": str(result),
                "numeric": float(result) if result.is_number else None,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def create_symbol(self, name):
        sym = self._get_symbol(name)
        return {"success": True, "symbol": str(sym)}

    def clear_symbols(self):
        self.symbols_cache.clear()
        return {"success": True}

    def solve_intersection(self, obj1, obj2):
        """求解两个几何对象的交点"""
        _load_sympy()
        try:
            symbols = _get_sympy_func("symbols")
            solve = _get_sympy_func("solve")
            x, y = symbols("x y")

            eq1 = self._object_to_equation(obj1, x, y)
            eq2 = self._object_to_equation(obj2, x, y)

            if eq1 is None or eq2 is None:
                return []

            solutions = solve((eq1, eq2), (x, y))

            points = []
            if isinstance(solutions, dict):
                if x in solutions and y in solutions:
                    try:
                        px = float(solutions[x])
                        py = float(solutions[y])
                        points.append((px, py))
                    except (TypeError, ValueError):
                        pass
            elif isinstance(solutions, list):
                for sol in solutions:
                    if isinstance(sol, dict) and x in sol and y in sol:
                        try:
                            px = float(sol[x])
                            py = float(sol[y])
                            points.append((px, py))
                        except (TypeError, ValueError):
                            pass

            return points
        except Exception:
            return []

    def _object_to_equation(self, obj, x, y):
        """将几何对象转换为 SymPy 方程"""
        Eq = _get_sympy_func("Eq")
        obj_type = obj.type

        if obj_type == "Line":
            return Eq(obj.a * x + obj.b * y + obj.c, 0)
        elif obj_type == "Segment":
            x1, y1 = obj.coordinates.get("x1", 0), obj.coordinates.get("y1", 0)
            x2, y2 = obj.coordinates.get("x2", 0), obj.coordinates.get("y2", 0)
            a = y2 - y1
            b = x1 - x2
            c = x2 * y1 - x1 * y2
            return Eq(a * x + b * y + c, 0)
        elif obj_type == "Circle":
            cx, cy = obj.coordinates.get("cx", 0), obj.coordinates.get("cy", 0)
            r = obj.coordinates.get("r", 1)
            return Eq((x - cx) ** 2 + (y - cy) ** 2, r**2)
        elif obj_type == "Point":
            px, _ = obj.coordinates.get("x", 0), obj.coordinates.get("y", 0)
            return Eq(x, px)

        return None

    def extract_line_control_points(self, equation_str):
        """从直线方程中提取两个控制点坐标"""
        _load_sympy()
        try:
            symbols = _get_sympy_func("symbols")
            simplify = _get_sympy_func("simplify")
            x, y = symbols("x y")

            match = re.search(r"(?<![<>])=(?![<>=])", equation_str)
            if match:
                left_str = equation_str[: match.start()]
                right_str = equation_str[match.end() :]
                left_expr = _cached_parse_expr(left_str.strip())
                right_expr = _cached_parse_expr(right_str.strip())
                eq = left_expr - right_expr
            else:
                eq = _cached_parse_expr(equation_str.strip())

            eq = simplify(eq)

            coeffs = eq.as_coefficients_dict()
            coeff_x = float(coeffs.get(x, 0).evalf()) if coeffs.get(x) is not None else 0.0
            coeff_y = float(coeffs.get(y, 0).evalf()) if coeffs.get(y) is not None else 0.0
            const = float(coeffs.get(1, 0).evalf()) if coeffs.get(1) is not None else 0.0

            points = []

            if abs(coeff_y) > 1e-10:
                x1, y1 = 0.0, -const / coeff_y
                x2, y2 = 10.0, (-const - coeff_x * 10) / coeff_y
                points.append((x1, y1))
                points.append((x2, y2))
            elif abs(coeff_x) > 1e-10:
                x1, y1 = -const / coeff_x, 0.0
                x2, y2 = (-const - coeff_y * 10) / coeff_x, 10.0
                points.append((x1, y1))
                points.append((x2, y2))

            return points
        except Exception:
            return []

    def latex_to_text(self, latex_str):
        """将 LaTeX 公式转换为可读的纯文本表示"""
        try:
            text = latex_str
            # 常见 LaTeX 命令替换
            replacements = [
                (r"\frac{", "("),  # 分式开始
                (r"}{", ") / ("),  # 分式分隔
                (r"\sqrt{", "sqrt("),  # 根号
                (r"\cdot", "·"),  # 乘法
                (r"\times", "×"),
                (r"\div", "÷"),
                (r"\pm", "±"),
                (r"\mp", "∓"),
                (r"\infty", "∞"),
                (r"\pi", "π"),
                (r"\theta", "θ"),
                (r"\alpha", "α"),
                (r"\beta", "β"),
                (r"\gamma", "γ"),
                (r"\delta", "δ"),
                (r"\lambda", "λ"),
                (r"\mu", "μ"),
                (r"\sigma", "σ"),
                (r"\omega", "ω"),
                (r"\Delta", "Δ"),
                (r"\Sigma", "Σ"),
                (r"\Omega", "Ω"),
                (r"\leq", "≤"),
                (r"\geq", "≥"),
                (r"\neq", "≠"),
                (r"\approx", "≈"),
                (r"\equiv", "≡"),
                (r"\rightarrow", "→"),
                (r"\leftarrow", "←"),
                (r"\Rightarrow", "⇒"),
                (r"\Leftarrow", "⇐"),
                (r"\sum", "Σ"),
                (r"\int", "∫"),
                (r"\partial", "∂"),
                (r"\nabla", "∇"),
                (r"\forall", "∀"),
                (r"\exists", "∃"),
                (r"\in", "∈"),
                (r"\notin", "∉"),
                (r"\subset", "⊂"),
                (r"\supset", "⊃"),
                (r"\cup", "∪"),
                (r"\cap", "∩"),
                (r"\emptyset", "∅"),
                (r"\overline{", ""),  # 上划线（去掉，保留内容）
                (r"\mathbf{", ""),  # 粗体（去掉）
                (r"\text{", ""),  # 文本模式（去掉）
                (r"\mathrm{", ""),  # 罗马体（去掉）
                (r"\left(", "("),
                (r"\right)", ")"),
                (r"\left[", "["),
                (r"\right]", "]"),
                (r"\left|", "|"),
                (r"\right|", "|"),
            ]
            for old, new in replacements:
                text = text.replace(old, new)
            # 清理多余的右花括号（由 \frac, \sqrt 等产生）
            text = text.replace("}", "")
            # 压缩多余空格
            import re as _re

            text = _re.sub(r"\s+", " ", text).strip()
            return {"success": True, "text": text}
        except Exception as e:
            return {"success": False, "error": str(e)}


class SmartCalculusSolver:
    @staticmethod
    def solve_integral(expression_str: str, var_name: str, a: float, b: float):
        """
        智能积分求解器：先解析 (Python)，后数值 (C#)
        """
        _load_sympy()
        from sympy import Integral, Symbol, integrate
        from sympy.parsing.sympy_parser import implicit_multiplication

        x = Symbol(var_name)
        try:
            # [P0 安全加固] 原注释称"使用 parse_expr 替代 sympify，避免代码注入"，
            # 但 sympy 在 global_dict=None 时照样注入 builtins，注入并未被挡住。
            # 现在走统一的安全解析入口。
            transformations = default_transformations() + (implicit_multiplication,)
            expr = safe_parse_expr(
                expression_str,
                local_dict={var_name: x},
                transformations=transformations,
            )
        except Exception:
            raise ValueError(f"无法解析数学表达式: {expression_str}")

        # 尝试 1：SymPy 寻找完美解析解 (符号运算)
        logger.info(f"正在尝试符号解析积分: {expression_str} ...")
        integral_expr = integrate(expr, (x, a, b))

        # 如果 integral_expr 里不再包含未计算的 Integral 对象，说明求出了解析解
        if not integral_expr.has(Integral):
            exact_val = float(integral_expr.evalf())
            return {"type": "exact", "value": exact_val, "method": "SymPy Symbolic"}

        logger.info("解析解不存在或过于复杂，正在降级到 C# 自适应数值引擎...")
        return SmartCalculusSolver._fallback_to_csharp(expr, x, a, b)

    @staticmethod
    def _fallback_to_csharp(expr, symbol, a, b):
        from sympy import lambdify

        # 将 SymPy 符号树编译为原生的 Python math 字节码函数 (速度极快)
        # 例如将 sp.sin(x)/x 编译为 lambda x: math.sin(x)/x
        fast_py_func = lambdify(symbol, expr, modules=["math"])

        # 将函数扔给 C# 底层跑 Gauss-Kronrod 算法
        # 容差设为 1e-10，在现代 CPU 上 C# 算出结果只需 1~2 毫秒
        numeric_val = cs_calculus.integrate_adaptive(fast_py_func, a, b, tol=1e-10)

        return {
            "type": "numeric",
            "value": numeric_val,
            "method": "C# Math.NET Double-Exponential",
        }
