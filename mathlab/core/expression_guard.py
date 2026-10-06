"""数学表达式解析的统一安全入口。

背景（P0）：SymPy 的 ``sympify()`` 与 ``parse_expr()`` 在 ``global_dict=None`` 时
会把 ``builtins`` 注入求值命名空间（见 sympy/parsing/sympy_parser.py 的默认分支），
因此表达式字符串等价于可执行代码：

    sympify("__import__('os').getpid()")                       -> 真的执行
    parse_expr("x.__class__", local_dict={"x": x})              -> 返回 type 对象
    parse_expr("Integer.__subclasses__()", ...)                 -> 返回全部子类列表

项目里的 ``.mathlab`` 工程文件会把 ``expression`` 字段原样交给这两个函数，
所以"打开一个不受信的项目文件"就是任意代码执行。

本模块提供三层收口，任何一层单独失效都不会退回可执行状态：

1. 文本闸门 :func:`is_expression_safe` —— 拦 dunder、属性访问、危险关键字
2. 受限命名空间 :func:`restricted_global_dict` —— 不给 builtins
3. 结果类型校验 —— 解析结果必须是 ``sympy.Basic``，拿到 Python 对象即判定失败

注意：不要用 :func:`mathlab.core.sandbox_security.is_code_safe` 替代第 1 层。
它依赖 ``ast.parse``，而 ``2x`` / ``3sin(x)`` 这类隐式乘法本身不是合法 Python，
会把合法数学输入误判成语法错误。
"""

import functools
import re
from typing import Any, Dict, Optional, Tuple

_DUNDER_RE = re.compile(r"__")
# 点后紧跟标识符 = 属性访问（1.5 / .5 这类小数点不会命中）
_ATTRIBUTE_RE = re.compile(r"\.\s*[A-Za-z_]")
# 表达式里不该出现的 Python 结构；数学记号不会用到这些词
BANNED_TOKENS = (
    "import",
    "exec",
    "eval",
    "compile",
    "globals",
    "locals",
    "getattr",
    "setattr",
    "delattr",
    "vars",
    "dir",
    "open",
    "breakpoint",
    "memoryview",
    "lambda",
    "class",
    "with",
    "del ",
    "try",
    "except",
    "finally",
    "global ",
    "nonlocal",
    "raise",
    "assert",
    "yield",
    "await",
)
_TOKEN_BOUNDARY_RE = r"(?<![A-Za-z0-9_])({})(?![A-Za-z0-9_])"

# sympy 公开命名空间里可以重新打开执行面的入口（parse_expr / sympify 会自己注入
# builtins；preview 会外部调用 LaTeX；init_session / interactive 换掉渲染后端），
# 必须从受限字典中剔除
GLOBAL_DENY_SUBSTRINGS = (
    "parse",
    "sympify",
    "eval",
    "import",
    "exec",
    "session",
    "testing",
    "print",
    "plot",
    "preview",
    "interactive",
    "autoload",
    "debug",
)

MAX_EXPRESSION_LENGTH = 2000


def is_expression_safe(expr_str: str) -> Tuple[bool, str]:
    """第 1 层：文本闸门。返回 (是否安全, 原因)。"""
    if not expr_str or not expr_str.strip():
        return False, "表达式为空"
    if len(expr_str) > MAX_EXPRESSION_LENGTH:
        return False, f"表达式过长（>{MAX_EXPRESSION_LENGTH} 字符）"
    if _DUNDER_RE.search(expr_str):
        return False, "安全拦截: 表达式中不允许出现 dunder 名称 '__'"
    if _ATTRIBUTE_RE.search(expr_str):
        return False, "安全拦截: 表达式中不允许出现属性访问"
    lowered = expr_str.lower()
    for token in BANNED_TOKENS:
        if re.search(_TOKEN_BOUNDARY_RE.format(re.escape(token.strip())), lowered):
            return False, f"安全拦截: 表达式中不允许出现 '{token.strip()}'"
    return True, "安全"


@functools.lru_cache(maxsize=1)
def _allowed_sympy_items() -> Tuple[Tuple[str, Any], ...]:
    """sympy 公开命名空间里允许出现的 (名称, 值) 名单（不可变，只算一次）。"""
    import types

    import sympy

    allowed: list[tuple[str, Any]] = []
    for name in dir(sympy):
        if name.startswith("_"):
            continue
        lowered = name.lower()
        if any(deny in lowered for deny in GLOBAL_DENY_SUBSTRINGS):
            continue
        value = getattr(sympy, name)
        if isinstance(value, types.ModuleType):
            continue
        module_of_value = getattr(value, "__module__", "") or ""
        if not module_of_value.startswith("sympy"):
            continue
        allowed.append((name, value))
    return tuple(allowed)


def restricted_global_dict() -> Dict[str, Any]:
    """第 2 层：只含 sympy 数学对象的求值命名空间，不含 builtins、不含子模块。

    **必须每次返回新字典**。``sympy.parsing.sympy_parser.parse_expr`` 会向传入的
    ``global_dict`` 里回写 ``__builtins__``（实测：解析一次之后该键就出现了），
    所以缓存并复用同一个 dict 会让这层限制在第一次调用后被悄悄解除。

    ``dir(sympy)`` 还会把 ``parsing`` / ``utilities`` / ``external`` 等子模块一起
    暴露出来；虽然第 1 层的属性访问规则已拦住这类写法，这里仍一并剔除。
    """
    return dict(_allowed_sympy_items())


@functools.lru_cache(maxsize=1)
def default_transformations() -> Tuple[Any, ...]:
    """sympy 的 standard_transformations + ``convert_xor``。

    sympy 1.14 的 standard_transformations 并不包含 ^ -> ** 的转换（``symbolic`` 已不在
    名单里），而 ``sympify("x^2+1")`` 一直能用；不补 ``convert_xor`` 会让老工程文件里的
    ``x^2 + y^2 - 1`` 这类写法直接解析失败。
    """
    from sympy.parsing.sympy_parser import convert_xor, standard_transformations

    return standard_transformations + (convert_xor,)


# 逃逸链的载体类型：拿到这些对象就等于拿到类/模块/函数
_DANGEROUS_RESULT_TYPES: Tuple[type, ...] = ()


def _dangerous_result_types() -> Tuple[type, ...]:
    global _DANGEROUS_RESULT_TYPES
    if not _DANGEROUS_RESULT_TYPES:
        import types

        _DANGEROUS_RESULT_TYPES = (
            type,
            types.ModuleType,
            types.FunctionType,
            types.BuiltinFunctionType,
            types.MethodType,
        )
    return _DANGEROUS_RESULT_TYPES


def _ensure_safe_result(result: Any, expr_str: str, _depth: int = 0) -> Any:
    """第 3 层：解析结果里不允许出现类 / 模块 / 函数对象。

    不能简单要求"结果必须是 ``sympy.Basic``"：``Matrix(...)`` 是 MatrixBase、
    ``solve()`` 返回 list，都会被误伤。这里改为只拒绝逃逸载体本身
    （``x.__class__`` -> type、``__subclasses__()`` -> list[type]），
    并对容器递归一层。
    """
    if _depth > 2:
        return result

    dangerous = _dangerous_result_types()
    if isinstance(result, dangerous):
        raise ValueError(f"安全拦截: 表达式解析出了非法对象 {type(result).__name__}: {expr_str!r}")

    if isinstance(result, (list, tuple, set, frozenset)):
        for item in result:
            _ensure_safe_result(item, expr_str, _depth + 1)
    elif isinstance(result, dict):
        for value in result.values():
            _ensure_safe_result(value, expr_str, _depth + 1)
    return result


def safe_parse_expr(
    expr_str: str,
    local_dict: Optional[Dict[str, Any]] = None,
    transformations: Optional[Tuple[Any, ...]] = None,
) -> Any:
    """安全版 ``parse_expr``：字符串闸门 + 受限 global_dict + 结果类型校验。

    Args:
        expr_str: 待解析的表达式字符串（可含 ``2x`` / ``x^2`` 这类数学写法）
        local_dict: 局部符号表，调用方自己控制
        transformations: sympy 解析变换链；不传则用 standard + convert_xor
    Returns:
        sympy 表达式
    Raises:
        ValueError: 表达式被判定不安全
    """
    ok, reason = is_expression_safe(expr_str)
    if not ok:
        raise ValueError(reason)

    from sympy.parsing.sympy_parser import parse_expr

    result = parse_expr(
        expr_str,
        local_dict=local_dict if local_dict is not None else {},
        global_dict=restricted_global_dict(),
        transformations=transformations if transformations is not None else default_transformations(),
    )
    return _ensure_safe_result(result, expr_str)


def safe_sympify(expr_str: str) -> Any:
    """``sympy.sympify`` 的安全替代。

    不对字符串调用 ``sympy.sympify``：它对 str 输入内部就是走带 builtins 的
    parse_expr，这正是漏洞来源。字符串一律交给受限解析。
    """
    return safe_parse_expr(expr_str, local_dict={})
