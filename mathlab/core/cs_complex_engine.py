"""C# 复数/分形引擎（MathLab.CSharpEngine.FastComplex）的 Python 封装。

设计要点（对齐 :mod:`mathlab.core.cs_num_engine` 的安全加载约定）：
- pythonnet / .NET 运行时缺失时**模块导入不抛异常**，由调用方通过
  :func:`get_cs_complex` 判断可用性并走降级路径；
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
# FastComplex 为 pythonnet 动态加载的 .NET 类型，静态类型系统无法解析，声明为 Any。
FastComplex: Any = None
CS_COMPLEX_AVAILABLE = False
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
    from MathLab.CSharpEngine import FastComplex as _FastComplexClass

    FastComplex = _FastComplexClass
    CS_COMPLEX_AVAILABLE = True
except Exception as _load_exc:  # pragma: no cover - 取决于本机 .NET 环境
    _LOAD_ERROR = str(_load_exc)
    logger.warning("C# 分形引擎不可用，Mandelbrot / Julia 渲染功能将不可用: %s", _LOAD_ERROR)


class CsComplexEngine:
    """复平面引擎：连接 C# 算力与 NumPy 色彩渲染"""

    def __init__(self):
        if FastComplex is None:
            raise RuntimeError("C# Engine DLL is not loaded.")
        self._engine = FastComplex()

    def generate_mandelbrot_image(self, x_min, x_max, y_min, y_max, width, height, max_iter=256):
        """
        核心渲染流程：
        1. C# 并行计算出迭代矩阵
        2. Numpy 将迭代次数映射为 RGB 像素矩阵
        """
        # 1. 呼叫 C# 引擎计算 (吃满 CPU 多核)
        # 返回的是 System.Int32[]
        res_flat = self._engine.GenerateMandelbrot(
            float(x_min),
            float(x_max),
            float(y_min),
            float(y_max),
            int(width),
            int(height),
            int(max_iter),
        )

        # 2. 零成本内存转换 (int数组转换极快)
        iter_array = np.array(list(res_flat), dtype=np.int32)
        iter_matrix = iter_array.reshape((height, width))

        # 3. Numpy 极速调色盘 (向量化运算，瞬间完成)
        # 创建一个 HxWx3 的 RGB 矩阵
        image_rgb = np.zeros((height, width, 3), dtype=np.uint8)

        # 找出那些逃逸的点 (iter < max_iter)
        mask = iter_matrix < max_iter

        # 使用平滑着色算法 (基于正弦波)，你可以随后修改这里玩出不同的色彩风格
        # 红色通道
        image_rgb[mask, 0] = (np.sin(0.1 * iter_matrix[mask]) * 127 + 128).astype(np.uint8)
        # 绿色通道
        image_rgb[mask, 1] = (np.sin(0.1 * iter_matrix[mask] + 2.094) * 127 + 128).astype(np.uint8)
        # 蓝色通道
        image_rgb[mask, 2] = (np.sin(0.1 * iter_matrix[mask] + 4.188) * 127 + 128).astype(np.uint8)

        # 未逃逸的点 (集合内部) 保持黑色 [0,0,0]

        return image_rgb

    def generate_julia_image(self, x_min, x_max, y_min, y_max, width, height, c_real, c_imag, max_iter=256):
        """
        生成 Julia 集合的 RGB 图像矩阵。
        新增参数 c_real, c_imag 代表当前的复数常数 C。
        """
        # 1. 呼叫 C# 极速计算
        res_flat = self._engine.GenerateJulia(
            float(x_min),
            float(x_max),
            float(y_min),
            float(y_max),
            int(width),
            int(height),
            int(max_iter),
            float(c_real),
            float(c_imag),
        )

        # 2. Numpy 零成本内存转换与重塑
        iter_array = np.array(list(res_flat), dtype=np.int32)
        iter_matrix = iter_array.reshape((height, width))

        # 3. 调色盘映射
        image_rgb = np.zeros((height, width, 3), dtype=np.uint8)
        mask = iter_matrix < max_iter

        # 换一种色彩风格 (更冷峻的赛博朋克蓝紫配色) 以区分 Mandelbrot
        image_rgb[mask, 0] = (np.sin(0.05 * iter_matrix[mask] + 3.0) * 127 + 128).astype(np.uint8)  # R
        image_rgb[mask, 1] = (np.sin(0.05 * iter_matrix[mask] + 3.5) * 127 + 128).astype(np.uint8)  # G
        image_rgb[mask, 2] = (np.sin(0.05 * iter_matrix[mask] + 4.0) * 127 + 128).astype(np.uint8)  # B

        return image_rgb

    def generate_smooth_mandelbrot(self, x_min, x_max, y_min, y_max, width, height, max_iter=256):
        """
        接收 C# 的平滑浮点数据，并渲染出无断层的极致分形图象
        """

        # 1. 呼叫 C# 引擎 (新增的 Smooth 方法)
        # 返回的是 System.Single (float[])
        res_flat = self._engine.GenerateMandelbrotSmooth(
            float(x_min),
            float(x_max),
            float(y_min),
            float(y_max),
            int(width),
            int(height),
            int(max_iter),
        )

        # 2. 转换为 Numpy float32 矩阵
        iter_array = np.array(list(res_flat), dtype=np.float32)
        iter_matrix = iter_array.reshape((height, width))

        # 3. 极致调色盘 (Smooth Color Palette)
        image_rgb = np.zeros((height, width, 3), dtype=np.uint8)
        mask = iter_matrix < max_iter

        # 提取浮点数值
        smooth_iter = iter_matrix[mask]

        # 使用基于余弦映射的调色盘 (Cosine Palette)
        # 色彩公式: Color = a + b * cos(2pi * (c * t + d))
        # 这是一种可以在数学上保证颜色平滑过渡的专业分形着色技术

        # 调整这些频率和相位因子可以改变分形的整体色调
        freq = 0.05

        # 霓虹电音风格 (Cyberpunk / Neon)
        r = np.cos(freq * smooth_iter + 0.0) * 127 + 128
        g = np.cos(freq * smooth_iter + 0.3) * 127 + 128
        b = np.cos(freq * smooth_iter + 0.6) * 127 + 128

        image_rgb[mask, 0] = r.astype(np.uint8)
        image_rgb[mask, 1] = g.astype(np.uint8)
        image_rgb[mask, 2] = b.astype(np.uint8)

        # 内部(逃逸失败的点)保持纯黑

        return image_rgb


# ── 惰性单例 ────────────────────────────────────────────────────────────────
# 历史问题：模块尾部曾直接 ``cs_complex = CsComplexEngine()``，DLL 缺失时
# RuntimeError 在**导入期**抛出，击穿 complex_explorer / complex_panel。
# 现改为首次使用时惰性创建；不可用或实例化失败返回 None。
_cs_complex_singleton: Optional[CsComplexEngine] = None
_cs_complex_lock = threading.Lock()


def get_cs_complex() -> Optional[CsComplexEngine]:
    """获取 C# 分形引擎单例；引擎不可用时返回 None（不抛异常）。

    Returns:
        可用时返回 :class:`CsComplexEngine` 实例；pythonnet 缺失、DLL 未编译
        或实例化失败时返回 None，调用方应禁用/降级分形渲染功能。
    """
    global _cs_complex_singleton
    if not CS_COMPLEX_AVAILABLE:
        return None
    if _cs_complex_singleton is not None:
        return _cs_complex_singleton
    with _cs_complex_lock:
        if _cs_complex_singleton is None:
            try:
                _cs_complex_singleton = CsComplexEngine()
            except Exception as exc:  # pragma: no cover - 取决于本机 .NET 环境
                logger.warning("C# 分形引擎实例化失败，渲染功能不可用: %s", exc)
                return None
    return _cs_complex_singleton
