"""C# 3D 网格引擎（MathLab.CSharpEngine.FastMesh3D）的 Python 封装。

设计要点（对齐 :mod:`mathlab.core.cs_num_engine` 的安全加载约定）：
- pythonnet / .NET 运行时缺失时**模块导入不抛异常**，由调用方通过
  :func:`get_cs_mesh_3d` 判断可用性并走降级路径；
- 引擎实例**惰性创建**，不再于模块尾部无条件实例化。
"""

import os
import sys
import threading
from typing import Any, Optional

from mathlab.utils.logger import get_logger

logger = get_logger(__name__)

# ── C# 引擎加载（pythonnet）─────────────────────────────────────────────────
# FastMesh3D 为 pythonnet 动态加载的 .NET 类型，静态类型系统无法解析，声明为 Any。
FastMesh3D: Any = None
CS_MESH_AVAILABLE = False
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
    from MathLab.CSharpEngine import FastMesh3D as _FastMesh3DClass

    FastMesh3D = _FastMesh3DClass
    CS_MESH_AVAILABLE = True
except Exception as _load_exc:  # pragma: no cover - 取决于本机 .NET 环境
    _LOAD_ERROR = str(_load_exc)
    logger.warning("C# 3D 网格引擎不可用，3D 波纹曲面功能将不可用: %s", _LOAD_ERROR)


class CsMeshEngine:
    """3D 空间曲面网格计算引擎"""

    def __init__(self):
        if FastMesh3D is None:
            raise RuntimeError("C# Engine DLL is not loaded.")
        self._engine = FastMesh3D()

    def get_ripple_mesh_data(self, x_range, y_range, x_seg=150, y_seg=150, time_val=0.0, freq=2.0):
        """
        生成一维展平的顶点列表，供前端 WebGL 消费
        """
        # 调用 C# 进行密集空间点并行矩阵计算
        res_flat = self._engine.GenerateRippleMesh(
            float(x_range[0]),
            float(x_range[1]),
            float(y_range[0]),
            float(y_range[1]),
            int(x_seg),
            int(y_seg),
            float(time_val),
            float(freq),
        )

        # 极速将非托管的 C# float[] 转换为 python 基础的 list (WebGL 传输所需)
        return list(res_flat)


# ── 惰性单例 ────────────────────────────────────────────────────────────────
# 历史问题：模块尾部曾直接 ``cs_mesh_3d = CsMeshEngine()``，DLL 缺失时
# RuntimeError 在**导入期**抛出，击穿 plugin_3d_viewer。
# 现改为首次使用时惰性创建；不可用或实例化失败返回 None。
_cs_mesh_singleton: Optional[CsMeshEngine] = None
_cs_mesh_lock = threading.Lock()


def get_cs_mesh_3d() -> Optional[CsMeshEngine]:
    """获取 C# 3D 网格引擎单例；引擎不可用时返回 None（不抛异常）。

    Returns:
        可用时返回 :class:`CsMeshEngine` 实例；pythonnet 缺失、DLL 未编译
        或实例化失败时返回 None，调用方应跳过 3D 波纹渲染。
    """
    global _cs_mesh_singleton
    if not CS_MESH_AVAILABLE:
        return None
    if _cs_mesh_singleton is not None:
        return _cs_mesh_singleton
    with _cs_mesh_lock:
        if _cs_mesh_singleton is None:
            try:
                _cs_mesh_singleton = CsMeshEngine()
            except Exception as exc:  # pragma: no cover - 取决于本机 .NET 环境
                logger.warning("C# 3D 网格引擎实例化失败，波纹功能不可用: %s", exc)
                return None
    return _cs_mesh_singleton
