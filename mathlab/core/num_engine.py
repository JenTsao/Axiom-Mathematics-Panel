import os
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import numpy as np
import scipy.fft as fft  # 傅里叶变换模块
import scipy.integrate as integrate
import scipy.linalg as la
import scipy.optimize as opt  # 优化模块
import scipy.signal as sig  # 信号处理模块
import scipy.stats as stats  # 统计模块

try:
    from mathlab.utils.logger import get_logger

    logger = get_logger(__name__)
except ImportError:
    import logging

    logger = logging.getLogger(__name__)

# C# 数值后端（MathLab.CSharpEngine.FastMath）开关的环境变量名。
# 实测（600×600 方阵）：C#/MathNet 路径慢于 SciPy/LAPACK 一至两个数量级
# （Cholesky 493ms vs 4.9ms、Solve 510ms vs 10.5ms、Eigen 959ms vs 274ms），
# 主要原因是 MathNet 托管实现 + 跨语言封送成本，故默认关闭。
# 如需启用：设置 MATHLAB_CS_NUM_ENGINE=1，或 NumEngine(prefer_csharp=True)。
CS_BACKEND_ENV = "MATHLAB_CS_NUM_ENGINE"


# 采用五点中心差分手动实现，支持任意阶导数计算 (通过递归降阶)
def _finite_diff(func, x, dx, n):
    if n == 1:
        return (-func(x + 2 * dx) + 8 * func(x + dx) - 8 * func(x - dx) + func(x - 2 * dx)) / (12 * dx)
    elif n == 2:
        return (-func(x + 2 * dx) + 16 * func(x + dx) - 30 * func(x) + 16 * func(x - dx) - func(x - 2 * dx)) / (
            12 * dx**2
        )
    else:
        # 递归降阶
        return _finite_diff(lambda t: _finite_diff(func, t, dx, n - 1), x, dx, 1)


class NumEngineError(Exception):
    """数值计算引擎专属异常"""

    pass


class NumEngine:
    """
    数值计算引擎核心 (基于 NumPy/SciPy)

    提供 Octave 级别的矩阵运算与数值分析接口。
    作为防腐层 (Anti-corruption Layer)，上层业务逻辑只需面向本类编程，
    底层 NumPy/SciPy 依赖的迭代不会污染核心业务逻辑。

    可选 C# 后端：当 ``prefer_csharp=True`` 或环境变量 ``MATHLAB_CS_NUM_ENGINE=1``
    时，``eigenvalues`` / ``cholesky`` / ``solve_linear_system`` 会优先调用
    ``MathLab.CSharpEngine.FastMath``；任何失败都会自动回退 NumPy/SciPy。
    """

    def __init__(self, prefer_csharp: Optional[bool] = None):
        # 预留配置项，例如设置默认的浮点数精度、随机数种子等
        self.default_tolerance = 1e-8

        # C# 数值后端开关（默认关闭：实测 C# 路径慢于 SciPy/LAPACK，见模块头部说明）
        if prefer_csharp is None:
            prefer_csharp = os.environ.get(CS_BACKEND_ENV, "").strip().lower() in ("1", "true", "yes", "on")
        self._prefer_csharp = bool(prefer_csharp)
        self._cs_engine = None
        self._cs_engine_probed = False

    def _get_cs_engine(self):
        """惰性获取 C# 数值引擎；未启用或不可用时返回 None（只探测一次）。"""
        if not self._prefer_csharp:
            return None

        if not self._cs_engine_probed:
            from mathlab.core.cs_num_engine import get_cs_num_engine

            self._cs_engine = get_cs_num_engine()
            self._cs_engine_probed = True
            if self._cs_engine is None:
                logger.warning("已请求 C# 数值后端，但引擎不可用（缺少 pythonnet 或未编译 DLL），回退 NumPy。")

        return self._cs_engine

    @property
    def csharp_backend_enabled(self) -> bool:
        """当前是否实际启用了 C# 数值后端（已请求且引擎可用）。"""
        return self._get_cs_engine() is not None

    # ──────────────────────────────────────────────────────────────────────────
    # 线性代数模块 (Linear Algebra)
    # ──────────────────────────────────────────────────────────────────────────

    def eigenvalues(self, matrix: Union[list, np.ndarray]) -> Dict[str, np.ndarray]:
        """
        计算方阵的特征值和特征向量。

        :param matrix: 输入方阵 (list 或 np.ndarray)
        :returns: 包含 'eigenvalues' 和 'eigenvectors' 的字典
        :raises NumEngineError: 输入非方阵时抛出
        """
        mat = np.asarray(matrix, dtype=complex)
        if mat.ndim != 2 or mat.shape[0] != mat.shape[1]:
            raise NumEngineError("特征值计算需要输入方阵 (Square Matrix)。")

        csharp = self._get_cs_engine()
        # C# Flat 接口仅支持实数矩阵；含复数元素时交由 NumPy 处理，避免虚部被静默丢弃
        if csharp is not None and not np.iscomplexobj(matrix):
            try:
                return csharp.eigenvalues(np.asarray(matrix, dtype=float))
            except Exception as exc:
                # C# 后端失败（如不支持的输入）时回退 NumPy
                logger.debug("C# 特征值计算失败，回退 NumPy: %s", exc)

        vals, vecs = la.eig(mat)
        return {
            "eigenvalues": vals,
            "eigenvectors": vecs,
        }

    def svd(self, matrix: Union[list, np.ndarray]) -> Dict[str, np.ndarray]:
        """
        奇异值分解 (Singular Value Decomposition)。

        :param matrix: 任意形状的矩阵
        :returns: 包含 'U'、'S'、'Vh' 的字典
                  - U  : 左奇异向量 (m×m 酉矩阵)
                  - S  : 奇异值一维数组 (降序排列)
                  - Vh : 右奇异向量的共轭转置 (n×n 酉矩阵)
        """
        mat = np.asarray(matrix, dtype=float)
        U, S, Vh = la.svd(mat, full_matrices=True)
        return {"U": U, "S": S, "Vh": Vh}

    def lu_decomposition(self, matrix: Union[list, np.ndarray]) -> Dict[str, np.ndarray]:
        """
        LU 分解 (PA = LU)。

        :param matrix: 输入方阵或矩形矩阵
        :returns: 包含 'P'、'L'、'U' 的字典
                  - P : 置换矩阵
                  - L : 下三角矩阵 (对角线元素为 1)
                  - U : 上三角矩阵
        """
        mat = np.asarray(matrix, dtype=float)
        P, L, U = la.lu(mat)
        return {"P": P, "L": L, "U": U}

    def cholesky(self, matrix: Union[list, np.ndarray]) -> Dict[str, np.ndarray]:
        """
        Cholesky 分解 (适用于埃尔米特正定矩阵)。

        :param matrix: 埃尔米特正定方阵
        :returns: 包含 'L' 的字典，满足 A = L @ L.T.conj()
        :raises NumEngineError: 矩阵非正定时抛出
        """
        mat = np.asarray(matrix, dtype=float)

        csharp = self._get_cs_engine()
        if csharp is not None:
            try:
                return csharp.cholesky(mat)
            except Exception as exc:
                # C# 后端失败（如非正定矩阵）时回退 NumPy，保持统一异常语义
                logger.debug("C# Cholesky 失败，回退 NumPy: %s", exc)

        try:
            L = la.cholesky(mat, lower=True)
            return {"L": L}
        except la.LinAlgError as e:
            raise NumEngineError(f"Cholesky 分解失败: {e}。请确保矩阵是埃尔米特正定的。") from e

    def solve_linear_system(
        self,
        A: Union[list, np.ndarray],
        b: Union[list, np.ndarray],
    ) -> Dict[str, Any]:
        """
        求解线性方程组 Ax = b。

        :param A: 系数矩阵 (方阵)
        :param b: 右端向量或矩阵
        :returns: 包含 'x' (解向量/矩阵) 和 'residual_norm' 的字典
        :raises NumEngineError: 矩阵奇异或维度不匹配时抛出
        """
        mat_A = np.asarray(A, dtype=float)
        vec_b = np.asarray(b, dtype=float)

        csharp = self._get_cs_engine()
        # C# Flat 接口仅支持一维右端向量；矩阵右端项直接走 NumPy
        if csharp is not None and mat_A.ndim == 2 and vec_b.ndim == 1:
            try:
                return csharp.solve_linear_system(mat_A, vec_b)
            except Exception as exc:
                # C# 后端失败（如奇异矩阵）时回退 NumPy，保持统一异常语义
                logger.debug("C# 线性求解失败，回退 NumPy: %s", exc)

        try:
            x = la.solve(mat_A, vec_b)
            residual_norm = float(np.linalg.norm(mat_A @ x - vec_b))
            return {"x": x, "residual_norm": residual_norm}
        except la.LinAlgError as e:
            raise NumEngineError(f"线性方程组求解失败: {e}。") from e

    def matrix_rank(self, matrix: Union[list, np.ndarray]) -> int:
        """
        计算矩阵的秩。

        :param matrix: 输入矩阵
        :returns: 矩阵的秩 (整数)
        """
        mat = np.asarray(matrix, dtype=float)
        return int(np.linalg.matrix_rank(mat, tol=self.default_tolerance))

    def condition_number(self, matrix: Union[list, np.ndarray]) -> float:
        """
        计算矩阵的条件数（使用 2-范数）。

        :param matrix: 输入矩阵
        :returns: 条件数 (浮点数)；若矩阵奇异则返回 inf
        """
        mat = np.asarray(matrix, dtype=float)
        return float(np.linalg.cond(mat))

    # ──────────────────────────────────────────────────────────────────────────
    # 数值微积分模块 (Numerical Calculus)
    # ──────────────────────────────────────────────────────────────────────────

    def numerical_derivative(
        self,
        func: Callable[[float], float],
        x: float,
        dx: float = 1e-6,
        order: int = 1,
    ) -> float:
        """
        数值求导（基于中心差分的高阶有限差分）。

        :param func:  目标函数 f: R → R
        :param x:     求导点
        :param dx:    步长，默认 1e-6
        :param order: 导数阶数 (1 = 一阶导，2 = 二阶导，…)
        :returns: 指定阶数的导数值 (浮点数)
        :raises NumEngineError: 计算失败时抛出
        """
        if order < 1:
            raise NumEngineError("导数阶数 order 必须为正整数。")
        try:
            return float(_finite_diff(func, x, dx, order))

        except Exception as e:
            raise NumEngineError(f"数值求导失败: {e}") from e

    def numerical_integral(
        self,
        func: Callable[[float], float],
        a: float,
        b: float,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """
        数值积分（自适应 Gauss-Kronrod 求积法，QUADPACK 实现）。

        :param func:  被积函数 f: R → R
        :param a:     积分下限（支持 ±np.inf）
        :param b:     积分上限（支持 ±np.inf）
        :param limit: 自适应子区间最大划分数，默认 100
        :returns: 包含 'integral' 和 'error_estimate' 的字典
        :raises NumEngineError: 计算失败时抛出
        """
        try:
            result, error_estimate = integrate.quad(func, a, b, limit=limit)
            return {
                "integral": float(result),
                "error_estimate": float(error_estimate),
            }
        except Exception as e:
            raise NumEngineError(f"数值积分计算失败: {e}") from e

    def numerical_double_integral(
        self,
        func: Callable[[float, float], float],
        a: float,
        b: float,
        gfun: Callable[[float], float],
        hfun: Callable[[float], float],
    ) -> Dict[str, Any]:
        """
        二重数值积分（DBLQUAD）。

        :param func:  被积函数 f(y, x)
        :param a:     x 积分下限
        :param b:     x 积分上限
        :param gfun:  y 积分下限函数 g(x)
        :param hfun:  y 积分上限函数 h(x)
        :returns: 包含 'integral' 和 'error_estimate' 的字典
        """
        try:
            result, error_estimate = integrate.dblquad(func, a, b, gfun, hfun)
            return {
                "integral": float(result),
                "error_estimate": float(error_estimate),
            }
        except Exception as e:
            raise NumEngineError(f"二重数值积分计算失败: {e}") from e

    # ──────────────────────────────────────────────────────────────────────────
    # 优化模块 (Optimization & Root Finding)
    # ──────────────────────────────────────────────────────────────────────────

    def minimize(
        self,
        func: Callable[[np.ndarray], float],
        x0: Union[list, np.ndarray],
        method: str = "BFGS",
        bounds: Optional[List[Tuple[float, float]]] = None,
    ) -> Dict[str, Any]:
        """
        寻找多元/一元函数的局部极小值。

        :param func:   目标函数，输入为 np.ndarray
        :param x0:     初始猜测点
        :param method: 优化算法，默认 BFGS；有界约束时推荐 'L-BFGS-B'
        :param bounds:  变量边界列表，如 [(0, None), (-1, 1)]
        :returns: 包含 'success'、'x'、'fun'、'message' 的字典
        :raises NumEngineError: 优化求解失败时抛出
        """
        try:
            res = opt.minimize(func, np.asarray(x0, dtype=float), method=method, bounds=bounds)
            return {
                "success": bool(res.success),
                "x": res.x,
                "fun": float(res.fun),
                "message": res.message,
            }
        except Exception as e:
            raise NumEngineError(f"优化求解失败: {e}") from e

    def root_finding(
        self,
        func: Callable[[float], float],
        bracket: List[float],
    ) -> float:
        """
        寻找标量函数在给定区间内的根（Brent 法）。

        :param func:    目标标量函数 f: R → R
        :param bracket: 包围根的区间 [a, b]，要求 f(a) 与 f(b) 异号
        :returns: 根的近似值 (浮点数)
        :raises NumEngineError: 区间无效或未收敛时抛出
        """
        if len(bracket) != 2:
            raise NumEngineError("求根需要提供两元素区间 bracket=[a, b]。")
        try:
            res = opt.root_scalar(func, bracket=bracket, method="brentq")
            if res.converged:
                return float(res.root)
            raise NumEngineError("求根迭代未收敛。")
        except NumEngineError:
            raise
        except Exception as e:
            raise NumEngineError(f"求根计算失败: {e}") from e

    def minimize_scalar(
        self,
        func: Callable[[float], float],
        bounds: Optional[Tuple[float, float]] = None,
        method: str = "brent",
    ) -> Dict[str, Any]:
        """
        寻找一元标量函数的极小值。

        :param func:   一元目标函数 f: R → R
        :param bounds: 搜索边界 (a, b)；若提供则自动使用 'bounded' 方法
        :param method: 优化算法，默认 'brent'
        :returns: 包含 'x'、'fun'、'success' 的字典
        """
        try:
            if bounds is not None:
                res = opt.minimize_scalar(func, bounds=bounds, method="bounded")
            else:
                res = opt.minimize_scalar(func, method=method)
            return {
                "success": bool(res.success) if hasattr(res, "success") else True,
                "x": float(res.x),
                "fun": float(res.fun),
            }
        except Exception as e:
            raise NumEngineError(f"一元极值求解失败: {e}") from e

    # ──────────────────────────────────────────────────────────────────────────
    # 信号处理模块 (Signal Processing)
    # ──────────────────────────────────────────────────────────────────────────

    def fft_transform(
        self,
        signal: Union[list, np.ndarray],
        sample_rate: float = 1.0,
    ) -> Dict[str, np.ndarray]:
        """
        一维快速傅里叶变换 (FFT)，同时返回对应频率轴。

        :param signal:      时域信号
        :param sample_rate: 采样率（Hz），用于计算频率轴，默认 1.0
        :returns: 包含 'spectrum'（复数频谱）和 'frequencies'（频率轴）的字典
        """
        try:
            arr = np.asarray(signal, dtype=complex)
            spectrum = fft.fft(arr)
            freqs = fft.fftfreq(len(arr), d=1.0 / sample_rate)
            return {"spectrum": spectrum, "frequencies": freqs}
        except Exception as e:
            raise NumEngineError(f"FFT 失败: {e}") from e

    def ifft_transform(
        self,
        spectrum: Union[list, np.ndarray],
    ) -> np.ndarray:
        """
        一维快速傅里叶逆变换 (IFFT)。

        :param spectrum: 频域复数谱
        :returns: 时域信号（复数数组，实际信号取 .real 即可）
        """
        try:
            return fft.ifft(np.asarray(spectrum, dtype=complex))
        except Exception as e:
            raise NumEngineError(f"IFFT 失败: {e}") from e

    def convolve(
        self,
        signal1: Union[list, np.ndarray],
        signal2: Union[list, np.ndarray],
        mode: str = "full",
    ) -> np.ndarray:
        """
        一维离散卷积。

        :param signal1: 第一个输入信号
        :param signal2: 第二个输入信号（卷积核）
        :param mode:    输出模式 'full' | 'same' | 'valid'，默认 'full'
        :returns: 卷积结果数组
        """
        try:
            return sig.convolve(
                np.asarray(signal1, dtype=float),
                np.asarray(signal2, dtype=float),
                mode=mode,
            )
        except Exception as e:
            raise NumEngineError(f"卷积计算失败: {e}") from e

    def find_peaks(
        self,
        signal: Union[list, np.ndarray],
        height: Optional[float] = None,
        distance: Optional[int] = None,
    ) -> Dict[str, np.ndarray]:
        """
        检测一维信号中的局部峰值。

        :param signal:   输入信号
        :param height:   峰值最小高度阈值
        :param distance: 相邻峰值的最小间距（采样点数）
        :returns: 包含 'peak_indices' 和 'peak_values' 的字典
        """
        try:
            arr = np.asarray(signal, dtype=float)
            kwargs: Dict[str, Any] = {}
            if height is not None:
                kwargs["height"] = height
            if distance is not None:
                kwargs["distance"] = distance
            indices, _ = sig.find_peaks(arr, **kwargs)
            return {
                "peak_indices": indices,
                "peak_values": arr[indices],
            }
        except Exception as e:
            raise NumEngineError(f"峰值检测失败: {e}") from e

    # ──────────────────────────────────────────────────────────────────────────
    # 统计与回归模块 (Statistics & Regression)
    # ──────────────────────────────────────────────────────────────────────────

    def linear_regression(
        self,
        x: Union[list, np.ndarray],
        y: Union[list, np.ndarray],
    ) -> Dict[str, float]:
        """
        一元线性回归拟合 (y = slope·x + intercept)。

        :param x: 自变量序列
        :param y: 因变量序列
        :returns: 包含 'slope'、'intercept'、'r_value'、'p_value'、'std_err' 的字典
        """
        try:
            res = stats.linregress(np.asarray(x, dtype=float), np.asarray(y, dtype=float))
            return {
                "slope": float(res.slope),
                "intercept": float(res.intercept),
                "r_value": float(res.rvalue),
                "p_value": float(res.pvalue),
                "std_err": float(res.stderr),
            }
        except Exception as e:
            raise NumEngineError(f"线性回归失败: {e}") from e

    def polynomial_fit(
        self,
        x: Union[list, np.ndarray],
        y: Union[list, np.ndarray],
        deg: int = 2,
    ) -> Dict[str, Any]:
        """
        多项式最小二乘拟合。

        :param x:   自变量序列
        :param y:   因变量序列
        :param deg: 多项式阶数，默认 2（二次曲线）
        :returns: 包含 'coefficients'（高次到低次）和 'residuals' 的字典
        """
        try:
            coeffs, residuals, rank, _sv, _rcond = np.polyfit(
                np.asarray(x, dtype=float),
                np.asarray(y, dtype=float),
                deg,
                full=True,
            )
            return {
                "coefficients": coeffs,
                "residuals": residuals if len(residuals) > 0 else np.array([0.0]),
                "rank": int(rank),
            }
        except Exception as e:
            raise NumEngineError(f"多项式拟合失败: {e}") from e

    def descriptive_stats(
        self,
        data: Union[list, np.ndarray],
    ) -> Dict[str, float]:
        """
        计算一组数据的基本描述性统计量。

        :param data: 输入数据序列
        :returns: 包含 'mean'、'median'、'std'、'variance'、'skewness'、'kurtosis'、
                  'min'、'max' 的字典
        """
        try:
            arr = np.asarray(data, dtype=float)
            return {
                "mean": float(np.mean(arr)),
                "median": float(np.median(arr)),
                "std": float(np.std(arr, ddof=1)),
                "variance": float(np.var(arr, ddof=1)),
                "skewness": float(stats.skew(arr)),
                "kurtosis": float(stats.kurtosis(arr)),
                "min": float(np.min(arr)),
                "max": float(np.max(arr)),
            }
        except Exception as e:
            raise NumEngineError(f"描述性统计计算失败: {e}") from e
