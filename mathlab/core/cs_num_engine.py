"""C# 数值内核（MathLab.CSharpEngine.FastMath）的 Python 封装。

设计要点：
- 引擎不可用时（未安装 pythonnet / DLL 未编译）可安全导入与降级，
  模块导入不会抛异常，由调用方通过 :func:`get_cs_num_engine` 判断可用性；
- 数值计算由 :class:`mathlab.core.num_engine.NumEngine` 按需惰性接入；
- 实测说明（600×600 方阵，本机）：受跨语言封送与 MathNet 托管实现影响，
  C# 路径明显慢于 SciPy/LAPACK（Cholesky 493ms vs 4.9ms、Solve 510ms vs 10.5ms），
  因此默认不启用，仅在显式配置后使用（见 num_engine 模块说明）。
"""

import os
import sys
import threading

import numpy as np

# ── C# 引擎加载（pythonnet）─────────────────────────────────────────────────
# import clr 必须包在 try 内：未安装 pythonnet 的环境下模块导入不应崩溃
FastMath = None
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

    import clr

    clr.AddReference("MathLab.CSharpEngine")
    from MathLab.CSharpEngine import FastMath
except Exception as _load_exc:  # pragma: no cover - 取决于本机 .NET 环境
    _LOAD_ERROR = str(_load_exc)


class CsNumEngineError(Exception):
    """C# 数值引擎调用异常"""

    pass


def _to_cs_double_array(arr) -> "object":
    """numpy 数组 → System.Double[]（一维平铺封送）。

    实测：写入方向 tolist() 封送（600×600 约 68ms）显著快于
    Buffer.BlockCopy 路线（约 484ms，瓶颈是 Python bytes → C# byte[] 的转换）。
    """
    import System

    flat = np.ascontiguousarray(arr, dtype=np.float64).ravel()
    return System.Array[System.Double](flat.tolist())


def _from_cs_double_array(cs_arr) -> np.ndarray:
    """System.Double[] → numpy 一维数组。

    实测：读取方向 BlockCopy 比 list() 快约 47 倍（36 万元素 1.4ms vs 67ms）。
    """
    import System

    nbytes = cs_arr.Length * 8
    byte_arr = System.Array[System.Byte](nbytes)
    System.Buffer.BlockCopy(cs_arr, 0, byte_arr, 0, nbytes)
    return np.frombuffer(bytes(byte_arr), dtype=np.float64)


def _from_cs_complex_array(cs_arr) -> np.ndarray:
    """System.Numerics.Complex[] → numpy complex128 数组。

    .NET Complex 与 numpy complex128 均为 (Real, Imaginary) 双精度内存布局，
    可直接按字节拷贝，避免逐元素访问 Real/Imaginary 的高昂开销。
    """
    import System

    nbytes = cs_arr.Length * 16
    byte_arr = System.Array[System.Byte](nbytes)
    System.Buffer.BlockCopy(cs_arr, 0, byte_arr, 0, nbytes)
    return np.frombuffer(bytes(byte_arr), dtype=np.complex128)


class CsNumEngine:
    """底层数值引擎 (C# Python.NET 版本)

    全面启用一维平铺 (Flat Array) 进行跨语言内存封送。
    """

    def __init__(self):
        if FastMath is None:
            raise CsNumEngineError(f"C# Engine DLL is not loaded. {_LOAD_ERROR}".strip())
        self._engine = FastMath()
        self.default_tolerance = 1e-8

    @property
    def is_available(self) -> bool:
        return self._engine is not None

    def eigenvalues(self, matrix):
        """特征值与特征向量（返回 complex 数组，特征向量按行优先还原为 n×n）。"""
        mat = np.asarray(matrix, dtype=float)
        if mat.ndim != 2 or mat.shape[0] != mat.shape[1]:
            raise CsNumEngineError("特征值计算需要输入方阵 (Square Matrix)。")

        rows, cols = mat.shape
        res_dict = self._engine.EigenvaluesFlat(_to_cs_double_array(mat), rows, cols)

        values_np = _from_cs_complex_array(res_dict["eigenvalues"])
        vectors_np = _from_cs_complex_array(res_dict["eigenvectors"]).reshape(rows, cols)

        return {
            "eigenvalues": values_np,
            "eigenvectors": vectors_np,
        }

    def cholesky(self, matrix):
        """Cholesky 分解，返回下三角矩阵 L（实测与 scipy lower=True 约定一致）。"""
        mat = np.asarray(matrix, dtype=float)
        rows, cols = mat.shape

        try:
            res_dict = self._engine.CholeskyFlat(_to_cs_double_array(mat), rows, cols)
            return {"L": _from_cs_double_array(res_dict["L"]).reshape(rows, cols)}
        except Exception as e:
            raise CsNumEngineError(f"Cholesky 分解失败: {e}")

    def solve_linear_system(self, A, b):
        """求解 Ax = b（b 为一维向量），返回解与残差 L2 范数。"""
        mat_A = np.asarray(A, dtype=float)
        vec_b = np.asarray(b, dtype=float)
        rows, cols = mat_A.shape

        try:
            res_dict = self._engine.SolveLinearSystemFlat(
                _to_cs_double_array(mat_A), rows, cols, _to_cs_double_array(vec_b)
            )
        except Exception as e:
            raise CsNumEngineError(f"求解失败: {e}")

        x = _from_cs_double_array(res_dict["x"])
        residual_norm = float(res_dict["residual_norm"])

        # 语义对齐：MathNet 对奇异/病态矩阵返回 NaN/Inf，而 scipy.linalg.solve 抛 LinAlgError。
        # 这里显式拒绝非有限结果，交由上层 NumEngine 回退 NumPy，保证错误语义一致。
        if not np.all(np.isfinite(x)) or not np.isfinite(residual_norm):
            raise CsNumEngineError("求解结果包含非有限值（矩阵可能奇异或病态）")

        return {"x": x, "residual_norm": residual_norm}


# ── 全局单例（惰性探测，失败后不再重复尝试）────────────────────────────────

_cs_num_engine_instance = None
_cs_num_engine_lock = threading.Lock()
_cs_num_engine_probed = False


def get_cs_num_engine():
    """获取全局唯一的 CsNumEngine 实例；C# 引擎不可用时返回 None。

    仅在调用方显式请求 C# 后端时才会构造引擎（默认不启用，原因见模块 docstring）。
    """
    global _cs_num_engine_instance, _cs_num_engine_probed

    if _cs_num_engine_probed:
        return _cs_num_engine_instance

    with _cs_num_engine_lock:
        if not _cs_num_engine_probed:
            try:
                _cs_num_engine_instance = CsNumEngine()
            except Exception:
                _cs_num_engine_instance = None
            _cs_num_engine_probed = True

    return _cs_num_engine_instance
