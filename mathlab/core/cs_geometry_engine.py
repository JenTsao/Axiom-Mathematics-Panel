"""C# 几何加速引擎（MathLab.CSharpEngine.FastGeometry）的 Python 封装。

设计要点（对齐 :mod:`mathlab.core.cs_calculus_engine` 的安全加载约定）：

* pythonnet / .NET 运行时缺失时**模块导入不抛异常**，由调用方通过
  :func:`get_cs_geometry` 判断可用性并走 Python 降级路径；
* DLL 路径与 ``PYTHONNET_RUNTIME`` 仍在导入期设置，但 ``import clr`` 必须包在
  try 内 —— 缺少 pythonnet 时它抛 ImportError / RuntimeError，曾直接击穿
  ``geometry_engine`` / ``models.locus`` / ``models.conic`` 等导入方；
* 引擎实例**惰性创建**：模块尾部曾无条件 ``cs_geometry = CsGeometryEngine()``，
  缺 DLL 时在导入期构造，是 T-9 里唯一漏网的 ``cs_*`` 模块。
"""

import os
import sys
import threading
from typing import Any, Optional

from mathlab.utils.logger import get_logger

logger = get_logger(__name__)

# ── C# 引擎加载（pythonnet）─────────────────────────────────────────────────
# FastGeometry 为 pythonnet 动态加载的 .NET 类型，静态类型系统无法解析，故声明
# 为 Any；不可用时一律置 None。
FastGeometry: Any = None
CS_GEOMETRY_AVAILABLE = False
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
    # pythonnet 动态程序集导入：AddReference 必须先于本程序集导入；且 MathLab 在
    # Linux（大小写敏感）与 Windows（不敏感，会误命中 mathlab/ 包）会被 isort 归入
    # 不同分组，跨平台排序结论相反，故冻结本块顺序，避免 CI 与本地互相回改。
    # isort: off
    from MathLab.CSharpEngine import FastGeometry as _FastGeometryClass

    # isort: on

    FastGeometry = _FastGeometryClass
    CS_GEOMETRY_AVAILABLE = True
except Exception as _load_exc:  # pragma: no cover - 取决于本机 .NET 环境
    _LOAD_ERROR = str(_load_exc)
    logger.warning("C# 几何引擎不可用，交点/圆锥曲线计算将走 Python 降级路径: %s", _LOAD_ERROR)


class CsGeometryEngine:
    """几何底层优化引擎 (C# Python.NET 版本)。

    已开启内存池化 (Buffer Reuse) 机制，实现零 GC 开销的高频几何运算。
    DLL 不可用时 ``is_available`` 为 False，各计算方法返回 None 交由调用方降级。
    """

    def __init__(self):
        self._engine = FastGeometry() if FastGeometry is not None else None

    @property
    def is_available(self):
        return self._engine is not None

    def _flat_array_to_points_fast(self, flat_array, point_count):
        """根据 C# 返回的有效点数量截取数据；0 表示无交点。"""
        if point_count == 0:
            return []

        points = []
        for i in range(point_count):
            idx = i * 2
            points.append((float(flat_array[idx]), float(flat_array[idx + 1])))
        return points

    def solve_line_line(self, a1, b1, c1, a2, b2, c2):
        if not self.is_available:
            return None
        # clr 会将返回的数组和 out 参数封装成元组: (double[] buffer, int pointCount)
        res_buffer, count = self._engine.SolveLineLineFast(
            float(a1), float(b1), float(c1), float(a2), float(b2), float(c2)
        )
        return self._flat_array_to_points_fast(res_buffer, count)

    def solve_line_circle(self, a, b, c, cx, cy, r):
        if not self.is_available:
            return None
        res_buffer, count = self._engine.SolveLineCircleFast(
            float(a), float(b), float(c), float(cx), float(cy), float(r)
        )
        return self._flat_array_to_points_fast(res_buffer, count)

    def solve_circle_circle(self, cx1, cy1, r1, cx2, cy2, r2):
        if not self.is_available:
            return None
        res_buffer, count = self._engine.SolveCircleCircleFast(
            float(cx1), float(cy1), float(r1), float(cx2), float(cy2), float(r2)
        )
        return self._flat_array_to_points_fast(res_buffer, count)

    def generate_conic_points(self, A, B, C, D, E, F, x_range, y_range, num_points):
        """圆锥曲线采样（未做 Buffer 优化，保持原有解析逻辑）。"""
        if not self.is_available:
            return None
        res = self._engine.GenerateConicPoints(
            float(A),
            float(B),
            float(C),
            float(D),
            float(E),
            float(F),
            float(x_range[0]),
            float(x_range[1]),
            float(y_range[0]),
            float(y_range[1]),
            int(num_points),
        )
        points = []
        for i in range(0, len(res), 2):
            points.append((float(res[i]), float(res[i + 1])))
        return points


# ── 惰性单例 ────────────────────────────────────────────────────────────────
_cs_geometry_singleton: Optional[CsGeometryEngine] = None
_cs_geometry_lock = threading.Lock()


def get_cs_geometry() -> Optional[CsGeometryEngine]:
    """获取 C# 几何引擎单例；不可用时返回 None（不抛异常）。

    Returns:
        可用时返回 :class:`CsGeometryEngine`；pythonnet 缺失、DLL 未编译或
        实例化失败时返回 None，调用方应降级到纯 Python 几何计算。
    """
    global _cs_geometry_singleton
    if not CS_GEOMETRY_AVAILABLE:
        return None
    if _cs_geometry_singleton is not None:
        return _cs_geometry_singleton
    with _cs_geometry_lock:
        if _cs_geometry_singleton is None:
            try:
                _cs_geometry_singleton = CsGeometryEngine()
            except Exception as exc:  # pragma: no cover - 取决于本机 .NET 环境
                logger.warning("C# 几何引擎实例化失败，改用 Python 降级路径: %s", exc)
                return None
    return _cs_geometry_singleton
