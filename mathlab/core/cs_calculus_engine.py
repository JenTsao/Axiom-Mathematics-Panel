"""C# 微积分引擎（MathLab.CSharpEngine.FastCalculus）的 Python 封装。

设计要点（对齐 :mod:`mathlab.core.cs_num_engine` 的安全加载约定）：
- pythonnet / .NET 运行时缺失时**模块导入不抛异常**，由调用方通过
  :func:`get_cs_calculus` 判断可用性并走降级路径；
- DLL 路径与 ``PYTHONNET_RUNTIME`` 仍在导入期设置，但 ``import clr`` 与
  ``from System import ...`` 必须包在 try 内——缺少 pythonnet 时它们抛
  ImportError / RuntimeError，曾直接击穿 ``cas_provider`` 等导入方（P0）；
- 引擎实例**惰性创建**，不再于模块尾部无条件实例化。
"""

import os
import sys
import threading
from typing import Any, Optional

import numpy as np

from mathlab.utils.logger import get_logger

logger = get_logger(__name__)

# ── C# 引擎加载（pythonnet）─────────────────────────────────────────────────
# FastCalculus / Double / Func 均为 pythonnet 动态加载的 .NET 类型，
# 静态类型系统无法解析，故声明为 Any；不可用时一律置 None。
FastCalculus: Any = None
Double: Any = None
Func: Any = None
CS_CALCULUS_AVAILABLE = False
_LOAD_ERROR = ""

try:
    _DLL_DIR = os.path.abspath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "MathLab.CSharpEngine",
            "bin",
            "Release",
            "netstandard2.0",
        )
    )
    if _DLL_DIR not in sys.path:
        sys.path.append(_DLL_DIR)

    os.environ.setdefault("PYTHONNET_RUNTIME", "coreclr")

    import clr  # noqa: E402

    clr.AddReference("MathLab.CSharpEngine")
    from System import Double as _Double
    from System import Func as _Func

    from MathLab.CSharpEngine import FastCalculus as _FastCalculusClass

    FastCalculus = _FastCalculusClass
    Double = _Double
    Func = _Func
    CS_CALCULUS_AVAILABLE = True
except Exception as _load_exc:  # pragma: no cover - 取决于本机 .NET 环境
    _LOAD_ERROR = str(_load_exc)
    logger.warning("C# 微积分引擎不可用，定积分/微分将走 Python 降级路径: %s", _LOAD_ERROR)


class CsCalculusEngine:
    """自适应微积分混合引擎"""

    def __init__(self):
        if FastCalculus is None:
            raise RuntimeError("C# Engine DLL is not loaded.")
        self._engine = FastCalculus()

    def integrate_adaptive(self, py_func, a: float, b: float, tol: float = 1e-8):
        """
        将 Python Callable 传入 C# 进行自适应积分
        """
        # 【魔法发生地】：将 Python 函数包裹为 C# 的 Func<double, double> 委托
        cs_delegate = Func[Double, Double](py_func)

        # 呼叫 C# 引擎，C# 会在内部的自适应循环中不断回调这个委托
        return self._engine.IntegrateAdaptive(cs_delegate, float(a), float(b), float(tol))

    def differentiate(self, py_func, x: float):
        cs_delegate = Func[Double, Double](py_func)
        return self._engine.Differentiate(cs_delegate, float(x))

    def integrate_discrete(self, y_array: np.ndarray, dx: float):
        import System

        # 打平并转为 C# 一维数组 (复用我们在 NumEngine 里的平铺优化)
        c_y_flat = System.Array[System.Double](y_array.ravel().tolist())
        return self._engine.IntegrateDiscrete(c_y_flat, float(dx))


# ── 惰性单例 ────────────────────────────────────────────────────────────────
# 历史问题：模块尾部曾直接 ``cs_calculus = CsCalculusEngine()``，DLL 缺失时
# RuntimeError 在**导入期**抛出，任何 import 方（cas_provider、函数探索器）
# 都会被击穿。现改为首次使用时惰性创建；不可用或实例化失败返回 None。
_cs_calculus_singleton: Optional[CsCalculusEngine] = None
_cs_calculus_lock = threading.Lock()


def get_cs_calculus() -> Optional[CsCalculusEngine]:
    """获取 C# 微积分引擎单例；引擎不可用时返回 None（不抛异常）。

    Returns:
        可用时返回 :class:`CsCalculusEngine` 实例；pythonnet 缺失、DLL 未编译
        或实例化失败时返回 None，调用方应降级到纯 Python 数值积分。
    """
    global _cs_calculus_singleton
    if not CS_CALCULUS_AVAILABLE:
        return None
    if _cs_calculus_singleton is not None:
        return _cs_calculus_singleton
    with _cs_calculus_lock:
        if _cs_calculus_singleton is None:
            try:
                _cs_calculus_singleton = CsCalculusEngine()
            except Exception as exc:  # pragma: no cover - 取决于本机 .NET 环境
                logger.warning("C# 微积分引擎实例化失败，改用 Python 降级路径: %s", exc)
                return None
    return _cs_calculus_singleton
