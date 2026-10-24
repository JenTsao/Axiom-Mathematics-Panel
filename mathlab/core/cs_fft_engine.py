"""C# FFT 引擎（MathLab.CSharpEngine.FastFFT）的 Python 封装。

设计要点（对齐 :mod:`mathlab.core.cs_num_engine` 的安全加载约定）：
- pythonnet / .NET 运行时缺失时**模块导入不抛异常**，由调用方通过
  :func:`get_cs_fft` 判断可用性并走降级路径；
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
# FastFFT 为 pythonnet 动态加载的 .NET 类型，静态类型系统无法解析，声明为 Any。
FastFFT: Any = None
CS_FFT_AVAILABLE = False
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
    from MathLab.CSharpEngine import FastFFT as _FastFFTClass

    FastFFT = _FastFFTClass
    CS_FFT_AVAILABLE = True
except Exception as _load_exc:  # pragma: no cover - 取决于本机 .NET 环境
    _LOAD_ERROR = str(_load_exc)
    logger.warning("C# FFT 引擎不可用，实时频谱分析功能将不可用: %s", _LOAD_ERROR)


class CsFFTEngine:
    """频域分析引擎：C# FFT 算力 + NumPy 数据重塑"""

    def __init__(self):
        if FastFFT is None:
            raise RuntimeError("C# Engine DLL is not loaded.")
        self._engine = FastFFT()

    def analyze_spectrum(self, signal_array: np.ndarray, sample_rate: float):
        """
        对一维时域信号进行频域分析
        返回: (frequencies, magnitudes) 两个一维 numpy 数组
        """
        import System

        # 1. 确保信号是一维且类型正确
        signal_np = np.asarray(signal_array, dtype=np.float64).ravel()

        # 2. 极速封送至 C# 环境
        c_signal = System.Array[System.Double](signal_np.tolist())

        # 3. 呼叫 C# 引擎进行原地 FFT 计算
        res_flat = self._engine.ComputeFFT(c_signal, float(sample_rate))

        # 4. 瞬间提取并使用 NumPy 重塑为 N x 2 的矩阵
        res_np = np.array(list(res_flat), dtype=np.float64).reshape(-1, 2)

        # 切片返回：第一列是频率，第二列是幅值
        return res_np[:, 0], res_np[:, 1]


# ── 惰性单例 ────────────────────────────────────────────────────────────────
# 历史问题：模块尾部曾直接 ``cs_fft = CsFFTEngine()``，DLL 缺失时 RuntimeError
# 在**导入期**抛出；且 signal_lab_panel 的 except 只捕 ImportError，漏放
# RuntimeError。现改为惰性创建 + 可用性标志，调用方按标志降级。
_cs_fft_singleton: Optional[CsFFTEngine] = None
_cs_fft_lock = threading.Lock()


def get_cs_fft() -> Optional[CsFFTEngine]:
    """获取 C# FFT 引擎单例；引擎不可用时返回 None（不抛异常）。

    Returns:
        可用时返回 :class:`CsFFTEngine` 实例；pythonnet 缺失、DLL 未编译
        或实例化失败时返回 None，调用方应跳过频谱分析。
    """
    global _cs_fft_singleton
    if not CS_FFT_AVAILABLE:
        return None
    if _cs_fft_singleton is not None:
        return _cs_fft_singleton
    with _cs_fft_lock:
        if _cs_fft_singleton is None:
            try:
                _cs_fft_singleton = CsFFTEngine()
            except Exception as exc:  # pragma: no cover - 取决于本机 .NET 环境
                logger.warning("C# FFT 引擎实例化失败，频谱分析不可用: %s", exc)
                return None
    return _cs_fft_singleton
