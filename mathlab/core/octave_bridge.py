import re
from typing import Any, Dict, Optional

import numpy as np
from PySide6.QtCore import QObject, Signal

from mathlab.core.num_engine import NumEngine
from mathlab.core.sandbox_security import is_code_safe


class BridgeSignals(QObject):
    """
    OctaveBridge 专属信号总线。

    使用独立的 QObject 子类持有信号，让 OctaveBridge 本身不必继承 QObject，
    保持纯 Python 的轻量级封装。
    """

    # 包含绘图配置的字典：类型、x/y 数据、标题、颜色等
    plot_requested = Signal(dict)

    # 滑块请求信号
    slider_requested = Signal(dict)


class OctaveBridgeError(Exception):
    """Octave 语法桥接器专属异常"""

    pass


class OctaveBridge:
    """
    MATLAB/Octave 语法桥接器

    将 Octave 代码字符串动态翻译为基于 NumPy 和 NumEngine 的 Python
    代码并在有状态的执行环境（self.env）中运行。

    核心机制：
        拦截 MATLAB 语法 → 词法替换 → 注入 NumEngine 环境执行

    设计原则：
        - 轻量渐进式正则替换，无需引入完整 AST 解析器
        - 通过 self.env 字典充当"工作区内存"，跨语句保持变量状态
        - 所有高级线性代数路由到 NumEngine，保持防腐层的一致性
    """

    def __init__(self, engine: Optional[NumEngine] = None):
        self.engine = engine or NumEngine()

        # ── Qt 信号总线（其他组件可监听）─────────────────────────────
        self.signals = BridgeSignals()

        # ── 执行上下文 (用户工作区) ──────────────────────────────────────
        # 注意: eval/exec 共享此同一字典，确保赋值后变量对后续表达式可见。
        self.env: Dict[str, Any] = {
            "__builtins__": {},  # 沙箱：屏蔽内置危险函数
            "np": np,
            # ── 矩阵构建 ──────────────────────────────────────────────
            # MATLAB: zeros(m, n) / ones(m, n) 传入两个独立整数
            # NumPy:  np.zeros((m, n))          期望一个元组形状
            # 用 lambda 包装兼容两种调用约定
            "zeros": lambda *a: np.zeros(a[0] if len(a) == 1 else a),
            "ones": lambda *a: np.ones(a[0] if len(a) == 1 else a),
            "eye": np.eye,
            "linspace": np.linspace,
            "arange": np.arange,
            "rand": lambda *a: np.random.rand(*a),
            "randn": lambda *a: np.random.randn(*a),
            "diag": np.diag,
            "reshape": np.reshape,
            # ── 基础运算 ──────────────────────────────────────────────
            "abs": np.abs,
            "sqrt": np.sqrt,
            "exp": np.exp,
            "log": np.log,
            "log2": np.log2,
            "log10": np.log10,
            "floor": np.floor,
            "ceil": np.ceil,
            "round": np.round,
            "mod": np.mod,
            # ── 三角函数 ──────────────────────────────────────────────
            "sin": np.sin,
            "cos": np.cos,
            "tan": np.tan,
            "asin": np.arcsin,
            "acos": np.arccos,
            "atan": np.arctan,
            "atan2": np.arctan2,
            # ── 矩阵属性 ──────────────────────────────────────────────
            "size": lambda x, *a: np.shape(x) if not a else np.shape(x)[a[0] - 1],
            "numel": np.size,
            "length": lambda x: max(np.shape(x)),
            "ndims": np.ndim,
            "find": lambda x: np.where(np.asarray(x).ravel())[0],
            # ── 聚合函数 ──────────────────────────────────────────────
            "max": np.max,
            "min": np.min,
            "sum": np.sum,
            "prod": np.prod,
            "cumsum": np.cumsum,
            "mean": np.mean,
            "std": np.std,
            "var": np.var,
            "norm": np.linalg.norm,
            "sort": np.sort,
            "fliplr": np.fliplr,
            "flipud": np.flipud,
            # ── 常数 ──────────────────────────────────────────────────
            "pi": np.pi,
            "e": np.e,
            "Inf": np.inf,
            "inf": np.inf,
            "NaN": np.nan,
            "nan": np.nan,
            "true": True,
            "false": False,
            # ── 高级线性代数 (路由到 NumEngine) ──────────────────────
            "inv": np.linalg.inv,
            "det": np.linalg.det,
            "rank": self.engine.matrix_rank,
            "cond": self.engine.condition_number,
            "eig": self.engine.eigenvalues,
            "svd": self.engine.svd,
            "lu": self.engine.lu_decomposition,
            "chol": self.engine.cholesky,
            # ── 优化 (路由到 NumEngine) ───────────────────────────────
            "fminsearch": lambda f, x0: self.engine.minimize(f, [x0]),
            "fzero": lambda f, x0: self.engine.root_finding(f, x0),
            # ── 信号处理 (路由到 NumEngine) ───────────────────────────
            "fft": lambda x: self.engine.fft_transform(x)["spectrum"],
            "ifft": lambda x: self.engine.ifft_transform(x),
            "conv": self.engine.convolve,
            # ── 统计回归 (路由到 NumEngine) ───────────────────────────
            "polyfit": lambda x, y, n: self.engine.polynomial_fit(x, y, deg=n)["coefficients"],
            "polyval": np.polyval,
            "__smart_mul__": lambda a, b: ((a * b) if np.isscalar(a) or np.isscalar(b) else (a @ b)),
            # ── ✨ UI 联动：绘图函数（发射 Qt 信号）───────────────────────
            "plot": self._builtin_plot,
            "scatter": self._builtin_scatter,
            "bar": self._builtin_bar,
            "stem": self._builtin_stem,
            # ── 输出 ────────────────────────────────────────────────────
            # Octave 的 disp() 此前在 env 里根本没有定义，写 disp(x) 必然 NameError。
            # disp 在 Octave 中打印后无返回值，而本桥接的控制台是按"表达式的返回值"
            # 显示的，所以直接把参数原样返回即可让用户看到内容，不必另开一条打印通道。
            "disp": lambda *a: (a[0] if len(a) == 1 else list(a)),
        }

    # ──────────────────────────────────────────────────────────────────────────
    # 词法翻译器 (Lexical Translator)
    # ──────────────────────────────────────────────────────────────────────────

    def _translate_matrix_literals(self, code: str) -> str:
        """
        将 MATLAB 矩阵字面量翻译为 np.array(...)。

        规则：
          [1 2 3]        → np.array([1, 2, 3])      (一维行向量)
          [1; 2; 3]      → np.array([[1], [2], [3]]) (列向量)
          [1 2; 3 4]     → np.array([[1, 2], [3, 4]])
          [1, 2; 3, 4]   → np.array([[1, 2], [3, 4]])
          []             → np.array([])
        """

        def replacer(match):
            inner = match.group(1).strip()
            if not inner:
                return "np.array([])"

            has_semicolon = ";" in inner
            rows = inner.split(";")
            formatted_rows = []
            for row in rows:
                elements = [e.strip() for e in row.replace(",", " ").split() if e.strip()]
                formatted_rows.append("[" + ", ".join(elements) + "]")

            if not has_semicolon and len(formatted_rows) == 1:
                # 一维数组
                return "np.array(" + formatted_rows[0] + ")"

            # 二维数组（含列向量）
            return "np.array([" + ", ".join(formatted_rows) + "])"

        # 使用非贪婪匹配，但要避免匹配已被翻译的 np.array([...])
        # 策略：先做占位保护再替换
        protected: Dict[str, str] = {}
        counter = [0]

        def protect(m):
            key = f"__NPARRAY{counter[0]}__"
            protected[key] = m.group(0)
            counter[0] += 1
            return key

        # 保护已有的 np.array(...) 不被二次替换
        code = re.sub(r"np\.array\([^)]*\)", protect, code)
        # 替换 MATLAB 矩阵字面量
        code = re.sub(r"\[([^\[\]]*)\]", replacer, code)
        # 还原保护内容
        for key, val in protected.items():
            code = code.replace(key, val)

        return code

    def _translate_operators(self, code: str) -> str:
        """
        翻译 MATLAB 运算符到 Python/NumPy 等价形式。

        映射表：
          A'    → A.T          (共轭转置，此处近似为普通转置)
          .*    → *            (逐元素乘，NumPy 默认行为)
          ./    → /            (逐元素除)
          .^    → **           (逐元素幂)
          *     → @            (矩阵乘法)
          ^     → **           (标量/矩阵幂，标量场景与 Python 一致)
          ~=    → !=           (不等于)
          ~     → not          (逻辑非，仅处理简单场景)
          %...  → #...         (注释符)
        """
        # 1. 保护字符串字面量，防止转置正则误伤
        protected_strs: Dict[str, str] = {}
        str_counter = [0]

        def protect_string(m):
            prefix = m.group(1)
            string_literal = m.group(2)
            key = f"__STRINGLIT{str_counter[0]}__"
            protected_strs[key] = string_literal
            str_counter[0] += 1
            return prefix + key

        code = re.sub(r"(^|[^A-Za-z0-9_\]\)])('[^']*')", protect_string, code)
        code = re.sub(
            r'("[^"]*")',
            lambda m: protect_string(re.match(r"(^|\s|)(" + re.escape(m.group(1)) + ")", m.group(1))),
            code,
        )

        # 2. 转置：变量名/右括号/右方括号后紧跟单引号
        code = re.sub(r"([A-Za-z0-9_\]\)]+)'", r"\1.T", code)

        # 3. 保护逐元素运算符（避免被后续步骤污染）
        code = code.replace(".*", "__DOT_MUL__")
        code = code.replace("./", "__DOT_DIV__")
        code = code.replace(".^", "__DOT_POW__")

        # 将矩阵乘法 operator * 替换为 @，而 element-wise 乘法 .* 会被还原为 *。
        # 在 evaluate 阶段通过 AST 将 @ 替换为 __smart_mul__ 以兼容标量乘法。
        code = code.replace("*", "@")

        # 4. 幂运算：^ → **
        code = code.replace("^", "**")

        # 5. 还原逐元素运算符
        code = code.replace("__DOT_MUL__", "*")
        code = code.replace("__DOT_DIV__", "/")
        code = code.replace("__DOT_POW__", "**")

        # 6. 比较运算符
        code = code.replace("~=", "!=")
        code = re.sub(r"~(?!=)", "not ", code)

        # 7. 注释符：% → #
        code = re.sub(r"%", "#", code)

        # 还原字符串字面量
        for key, val in protected_strs.items():
            code = code.replace(key, val)

        return code

    def translate(self, code: str) -> str:
        """
        将一行 Octave/MATLAB 代码翻译为等价的 Python 代码字符串。

        翻译顺序（顺序敏感）：
            1. 矩阵字面量
            2. 运算符映射

        :param code: MATLAB/Octave 源代码字符串
        :returns: 等价 of Python 代码字符串
        """
        code = code.strip()
        code = self._translate_matrix_literals(code)
        code = self._translate_operators(code)
        return code

    # ──────────────────────────────────────────────────────────────────────────
    # 执行器 (Executor)
    # ──────────────────────────────────────────────────────────────────────────

    def evaluate(self, code: str) -> Any:
        """
        执行一条 Octave 语句并返回结果。

        支持：
          - 表达式：   ``A + B``  → 返回计算结果
          - 赋值语句：  ``A = [1 2; 3 4]`` → 更新 env，返回变量值
          - 多语句块：  用分号或换行分隔（目前仅支持单行）

        状态持久化：env 字典在每次调用间保持，变量跨语句可见。

        :param code: Octave 源代码
        :returns: 表达式求值结果，赋值语句返回被赋值的变量值，无结果返回 None
        :raises OctaveBridgeError: 翻译或执行失败时抛出
        """
        python_code = self.translate(code)

        # [P0 安全加固] 这是主进程内的 eval/exec，env 里挂着 np，
        # `np.__builtins__['__import__']('os')` 之类写法此前可直接逃逸。
        # 现在对翻译后的 Python 文本先过一遍强扫描器；
        # 语法错误不在这里拦截，交给下面的 eval/exec 分支给出原有翻译错误。
        scan_ok, scan_reason = is_code_safe(python_code)
        if not scan_ok and not scan_reason.startswith("语法错误"):
            raise OctaveBridgeError(f"安全拦截: 拒绝执行该代码。\n  原始代码: {code!r}\n  {scan_reason}")

        import ast

        class SmartMulTransformer(ast.NodeTransformer):
            def visit_BinOp(self, node):
                self.generic_visit(node)
                if isinstance(node.op, ast.MatMult):
                    return ast.Call(
                        func=ast.Name(id="__smart_mul__", ctx=ast.Load()),
                        args=[node.left, node.right],
                        keywords=[],
                    )
                return node

        try:
            # 尝试作为表达式 eval（eval/exec 共享 self.env，变量跨调用可见）
            tree = ast.parse(python_code, mode="eval")
            tree = SmartMulTransformer().visit(tree)
            ast.fix_missing_locations(tree)
            compiled = compile(tree, "<string>", "eval")
            result = eval(compiled, self.env, self.env)
            return result
        except SyntaxError:
            # 可能是赋值语句或含有多行的代码块，改用 exec
            try:
                exec_tree = ast.parse(python_code, mode="exec")
                exec_tree = SmartMulTransformer().visit(exec_tree)
                ast.fix_missing_locations(exec_tree)
                compiled = compile(exec_tree, "<string>", "exec")
                exec(compiled, self.env, self.env)
                # 启发式：如果是简单赋值 "VAR = ..."，返回该变量
                stripped = python_code.strip()
                if "=" in stripped and not any(op in stripped.split("=")[0] for op in ["<", ">", "!", "="]):
                    var_name = stripped.split("=")[0].strip()
                    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", var_name):
                        return self.env.get(var_name)
                return None
            except Exception as exc:
                raise OctaveBridgeError(
                    f"执行失败。\n"
                    f"  原始代码:   {code!r}\n"
                    f"  翻译后代码: {python_code!r}\n"
                    f"  错误信息:   {exc}"
                )
        except Exception as exc:
            raise OctaveBridgeError(
                f"执行失败。\n" f"  原始代码:   {code!r}\n" f"  翻译后代码: {python_code!r}\n" f"  错误信息:   {exc}"
            )

    def reset(self) -> None:
        """清空工作区（保留内置函数和常量，仅清除用户变量）"""
        user_vars = [
            k
            for k in self.env
            if not callable(self.env[k])
            and k
            not in (
                "pi",
                "e",
                "Inf",
                "inf",
                "NaN",
                "nan",
                "true",
                "false",
                "np",
                "__builtins__",
            )
        ]
        for k in user_vars:
            del self.env[k]

    def workspace(self) -> Dict[str, Any]:
        """返回当前工作区中所有用户变量（过滤掉内置函数）"""
        return {
            k: v
            for k, v in self.env.items()
            if not k.startswith("__")
            and not callable(v)
            and k not in ("np", "pi", "e", "Inf", "inf", "NaN", "nan", "true", "false")
        }

    # ──────────────────────────────────────────────────────────────────────────
    # 内置绘图函数 (Built-in Plot Helpers)
    # 每个函数负责：
    #   1. 参数校验 + 数据标准化
    #   2. 打包 payload 字典
    #   3. 通过 self.signals.plot_requested 发射 Qt 信号（异步通知 ECharts）
    #   4. 返回控制台提示字符串
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _to_list(arr) -> list:
        """将任意数值类型展平为 Python list，保留有限精度"""
        import numpy as _np

        a = _np.asarray(arr, dtype=float).flatten()
        return [round(float(v), 8) for v in a]

    def _emit_plot(self, payload: dict) -> str:
        """发射 plot_requested 信号并返回控制台提示"""
        n = len(payload.get("y", []))
        self.signals.plot_requested.emit(payload)
        chart_type = payload.get("type", "line")
        return f"[✓ 图表已发送至 ECharts 渲染 · 类型={chart_type} · {n} 个数据点]"

    def _builtin_plot(self, *args, **kwargs) -> str:
        """
        plot(y)          — 以 0,1,2,... 为 x，绘制折线图
        plot(x, y)       — 指定 x 轴数据，绘制折线图
        plot(x, y, title="标题")  — 带标题
        """
        if len(args) == 0:
            raise OctaveBridgeError("plot() 需要至少一个参数。")

        if len(args) == 1:
            y = self._to_list(args[0])
            x = list(range(len(y)))
        else:
            x = self._to_list(args[0])
            y = self._to_list(args[1])

        if len(x) != len(y):
            raise OctaveBridgeError(f"plot 数据维度不匹配: x={len(x)} 个点, y={len(y)} 个点。")

        return self._emit_plot(
            {
                "type": "line",
                "x": x,
                "y": y,
                "title": kwargs.get("title", "2D 折线图"),
                "smooth": True,
                "color": "#4EC9B0",
                "area": True,
            }
        )

    def _builtin_scatter(self, *args, **kwargs) -> str:
        """
        scatter(y)       — 散点图（自动 x）
        scatter(x, y)    — 指定 x、y 的散点图
        """
        if len(args) == 0:
            raise OctaveBridgeError("scatter() 需要至少一个参数。")

        if len(args) == 1:
            y = self._to_list(args[0])
            x = list(range(len(y)))
        else:
            x = self._to_list(args[0])
            y = self._to_list(args[1])

        if len(x) != len(y):
            raise OctaveBridgeError(f"scatter 数据维度不匹配: x={len(x)} 个点, y={len(y)} 个点。")

        return self._emit_plot(
            {
                "type": "scatter",
                "x": x,
                "y": y,
                "title": kwargs.get("title", "散点图"),
                "color": "#C586C0",
                "area": False,
            }
        )

    def _builtin_bar(self, *args, **kwargs) -> str:
        """
        bar(y)           — 柱状图（类别自动编号）
        bar(x, y)        — 指定类别标签和高度
        """
        if len(args) == 0:
            raise OctaveBridgeError("bar() 需要至少一个参数。")

        if len(args) == 1:
            y = self._to_list(args[0])
            x = list(range(len(y)))
        else:
            # x 可以是字符串列表或数值数组
            try:
                x = self._to_list(args[0])
            except Exception:
                x = list(args[0])
            y = self._to_list(args[1])

        return self._emit_plot(
            {
                "type": "bar",
                "x": x,
                "y": y,
                "title": kwargs.get("title", "柱状图"),
                "color": "#569CD6",
                "area": False,
            }
        )

    def _builtin_stem(self, *args, **kwargs) -> str:
        """
        stem(y)          — 茎叶图（以竖线 + 点表示离散信号）
        stem(x, y)       — 指定 x 的茎叶图
        """
        if len(args) == 0:
            raise OctaveBridgeError("stem() 需要至少一个参数。")

        if len(args) == 1:
            y = self._to_list(args[0])
            x = list(range(len(y)))
        else:
            x = self._to_list(args[0])
            y = self._to_list(args[1])

        return self._emit_plot(
            {
                "type": "stem",  # 前端将渲染为带 markLine 的散点图
                "x": x,
                "y": y,
                "title": kwargs.get("title", "茎叶图 (Stem Plot)"),
                "color": "#DCDCAA",
                "area": False,
            }
        )
