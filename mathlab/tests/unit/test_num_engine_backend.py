"""NumEngine 的 C# 数值后端（FastMath）接入测试。

不依赖 pythonnet / C# DLL：通过 monkeypatch 注入假引擎，验证
后端开关、调用路由、失败回退与错误语义。真实的 C# 引擎行为
（数值一致性、封送正确性）由开发期探测脚本验证。
"""

import numpy as np
import pytest

from mathlab.core import cs_num_engine
from mathlab.core.cs_num_engine import CsNumEngineError
from mathlab.core.num_engine import CS_BACKEND_ENV, NumEngine, NumEngineError


class _FakeCsEngine:
    """可辨识结果的假 C# 引擎（返回 99 系列数值以证明走了 C# 路径）。"""

    def __init__(self, fail: bool = False):
        self.calls: list = []
        self.fail = fail

    def eigenvalues(self, matrix):
        self.calls.append("eigenvalues")
        if self.fail:
            raise RuntimeError("模拟 C# 特征值失败")
        return {
            "eigenvalues": np.array([99.0, 98.0], dtype=complex),
            "eigenvectors": np.eye(2, dtype=complex),
        }

    def cholesky(self, matrix):
        self.calls.append("cholesky")
        if self.fail:
            raise RuntimeError("模拟 C# Cholesky 失败")
        return {"L": np.array([[99.0, 0.0], [0.0, 99.0]])}

    def solve_linear_system(self, A, b):
        self.calls.append("solve_linear_system")
        if self.fail:
            raise RuntimeError("模拟 C# 求解失败")
        return {"x": np.array([99.0, 99.0]), "residual_norm": 0.0}


@pytest.fixture
def fake_cs(monkeypatch):
    """注入可用的假 C# 引擎。"""
    engine = _FakeCsEngine()
    monkeypatch.setattr(cs_num_engine, "get_cs_num_engine", lambda: engine)
    return engine


@pytest.fixture
def failing_cs(monkeypatch):
    """注入总是失败的假 C# 引擎。"""
    engine = _FakeCsEngine(fail=True)
    monkeypatch.setattr(cs_num_engine, "get_cs_num_engine", lambda: engine)
    return engine


# ─────────────────────────────────────────────────────────────
# 后端开关
# ─────────────────────────────────────────────────────────────


class TestBackendSelection:
    @pytest.mark.unit
    def test_disabled_by_default(self, fake_cs):
        """默认关闭：即使引擎可用也不启用 C# 后端。"""
        engine = NumEngine()
        assert engine.csharp_backend_enabled is False
        assert fake_cs.calls == []

    @pytest.mark.unit
    def test_enabled_by_argument(self, fake_cs):
        """构造参数显式启用。"""
        assert NumEngine(prefer_csharp=True).csharp_backend_enabled is True

    @pytest.mark.unit
    def test_enabled_by_env(self, monkeypatch, fake_cs):
        """环境变量 MATHLAB_CS_NUM_ENGINE=1 启用。"""
        monkeypatch.setenv(CS_BACKEND_ENV, "1")
        assert NumEngine().csharp_backend_enabled is True

    @pytest.mark.unit
    def test_env_value_false_keeps_disabled(self, monkeypatch, fake_cs):
        """环境变量为假值时保持关闭。"""
        monkeypatch.setenv(CS_BACKEND_ENV, "0")
        assert NumEngine().csharp_backend_enabled is False

    @pytest.mark.unit
    def test_engine_unavailable_falls_back(self, monkeypatch):
        """请求了 C# 后端但引擎不可用：回退 NumPy 且功能正常。"""
        monkeypatch.setattr(cs_num_engine, "get_cs_num_engine", lambda: None)
        engine = NumEngine(prefer_csharp=True)

        assert engine.csharp_backend_enabled is False
        result = engine.eigenvalues([[2.0, 0.0], [0.0, 3.0]])
        assert pytest.approx(np.sort(np.real(result["eigenvalues"])), abs=1e-10) == [2.0, 3.0]


# ─────────────────────────────────────────────────────────────
# 调用路由
# ─────────────────────────────────────────────────────────────


class TestCSharpRouting:
    @pytest.mark.unit
    def test_eigenvalues_routed_to_csharp(self, fake_cs):
        engine = NumEngine(prefer_csharp=True)
        result = engine.eigenvalues([[2.0, 1.0], [1.0, 2.0]])

        assert fake_cs.calls == ["eigenvalues"]
        assert pytest.approx(np.sort(np.real(result["eigenvalues"])), abs=1e-10) == [98.0, 99.0]

    @pytest.mark.unit
    def test_cholesky_routed_to_csharp(self, fake_cs):
        engine = NumEngine(prefer_csharp=True)
        result = engine.cholesky([[4.0, 2.0], [2.0, 3.0]])

        assert fake_cs.calls == ["cholesky"]
        assert np.allclose(result["L"], np.array([[99.0, 0.0], [0.0, 99.0]]))

    @pytest.mark.unit
    def test_solve_routed_to_csharp(self, fake_cs):
        engine = NumEngine(prefer_csharp=True)
        result = engine.solve_linear_system([[3.0, 1.0], [1.0, 2.0]], [9.0, 8.0])

        assert fake_cs.calls == ["solve_linear_system"]
        assert np.allclose(result["x"], [99.0, 99.0])

    @pytest.mark.unit
    def test_complex_matrix_not_routed(self, fake_cs):
        """复数矩阵不路由到 C#（其 Flat 接口仅支持实数）。"""
        engine = NumEngine(prefer_csharp=True)
        result = engine.eigenvalues([[1 + 2j, 0], [0, 3 - 1j]])

        assert fake_cs.calls == []
        assert pytest.approx(np.sort(np.real(result["eigenvalues"])), abs=1e-10) == [1.0, 3.0]

    @pytest.mark.unit
    def test_matrix_rhs_not_routed(self, fake_cs):
        """矩阵右端项不路由到 C#（其接口仅支持一维向量）。"""
        engine = NumEngine(prefer_csharp=True)
        result = engine.solve_linear_system([[3.0, 1.0], [1.0, 2.0]], np.eye(2))

        assert fake_cs.calls == []
        assert result["x"].shape == (2, 2)


# ─────────────────────────────────────────────────────────────
# 失败回退与错误语义
# ─────────────────────────────────────────────────────────────


class TestFallback:
    @pytest.mark.unit
    def test_eigenvalues_fallback(self, failing_cs):
        engine = NumEngine(prefer_csharp=True)
        result = engine.eigenvalues([[2.0, 0.0], [0.0, 3.0]])

        assert failing_cs.calls == ["eigenvalues"]
        assert pytest.approx(np.sort(np.real(result["eigenvalues"])), abs=1e-10) == [2.0, 3.0]

    @pytest.mark.unit
    def test_cholesky_fallback(self, failing_cs):
        engine = NumEngine(prefer_csharp=True)
        result = engine.cholesky([[4.0, 2.0], [2.0, 3.0]])

        assert failing_cs.calls == ["cholesky"]
        assert np.allclose(result["L"], np.linalg.cholesky([[4.0, 2.0], [2.0, 3.0]]))

    @pytest.mark.unit
    def test_solve_fallback(self, failing_cs):
        engine = NumEngine(prefer_csharp=True)
        result = engine.solve_linear_system([[3.0, 1.0], [1.0, 2.0]], [9.0, 8.0])

        assert failing_cs.calls == ["solve_linear_system"]
        assert np.allclose(result["x"], [2.0, 3.0])

    @pytest.mark.unit
    def test_error_semantics_preserved(self, failing_cs):
        """C# 与 NumPy 均失败时，仍抛出统一的 NumEngineError。"""
        engine = NumEngine(prefer_csharp=True)

        with pytest.raises(NumEngineError, match="方阵"):
            engine.eigenvalues([[1, 2, 3], [4, 5, 6]])
        with pytest.raises(NumEngineError, match="Cholesky"):
            engine.cholesky([[1.0, 2.0], [2.0, 1.0]])  # 非正定
        with pytest.raises(NumEngineError, match="求解失败"):
            engine.solve_linear_system([[1.0, 2.0], [2.0, 4.0]], [1.0, 2.0])  # 奇异

    @pytest.mark.unit
    def test_only_probes_engine_once(self, monkeypatch):
        """引擎探测只执行一次，避免每次调用重复尝试加载 DLL。"""
        probe_count = {"n": 0}

        def _probe():
            probe_count["n"] += 1
            return _FakeCsEngine()

        monkeypatch.setattr(cs_num_engine, "get_cs_num_engine", _probe)
        engine = NumEngine(prefer_csharp=True)

        engine.eigenvalues([[2.0, 0.0], [0.0, 3.0]])
        engine.cholesky([[4.0, 2.0], [2.0, 3.0]])
        engine.solve_linear_system([[3.0, 1.0], [1.0, 2.0]], [9.0, 8.0])

        assert probe_count["n"] == 1


# ─────────────────────────────────────────────────────────────
# 真实 C# 引擎（本地具备 pythonnet + DLL 时执行，CI 自动跳过）
# 直接调用后端而非经过 NumEngine，避免回退机制掩盖后端自身故障
# ─────────────────────────────────────────────────────────────

_real_engine = cs_num_engine.get_cs_num_engine()

requires_real_cs = pytest.mark.skipif(_real_engine is None, reason="C# 引擎不可用（缺少 pythonnet 或未编译 DLL）")


@requires_real_cs
class TestRealCSharpEngine:
    @pytest.mark.unit
    def test_eigenvalues_match_numpy(self):
        matrix = np.array([[2.0, 1.0], [1.0, 2.0]])
        result = _real_engine.eigenvalues(matrix)
        assert pytest.approx(np.sort(np.real(result["eigenvalues"])), abs=1e-8) == np.linalg.eigvalsh(matrix)

    @pytest.mark.unit
    def test_complex_eigenvalues_extraction(self):
        """旋转矩阵特征值为 ±i：验证 Complex[] 结果提取路径。"""
        rotation = np.array([[0.0, -1.0], [1.0, 0.0]])
        result = _real_engine.eigenvalues(rotation)
        assert np.allclose(np.sort_complex(result["eigenvalues"]), np.array([-1j, 1j]))

    @pytest.mark.unit
    def test_eigenvector_pairs(self):
        """特征对必须满足 A@v = λv（防止特征向量提取错位）。"""
        matrix = np.array([[2.0, 1.0], [1.0, 2.0]])
        result = _real_engine.eigenvalues(matrix)
        for i in range(matrix.shape[0]):
            lam = result["eigenvalues"][i]
            vec = result["eigenvectors"][:, i]
            assert np.allclose(matrix @ vec, lam * vec, atol=1e-8)

    @pytest.mark.unit
    def test_cholesky_matches_numpy(self):
        matrix = np.array([[4.0, 2.0], [2.0, 3.0]])
        assert np.allclose(_real_engine.cholesky(matrix)["L"], np.linalg.cholesky(matrix))

    @pytest.mark.unit
    def test_solve_matches_numpy(self):
        A = np.array([[3.0, 1.0], [1.0, 2.0]])
        b = np.array([9.0, 8.0])
        assert np.allclose(_real_engine.solve_linear_system(A, b)["x"], np.linalg.solve(A, b))

    @pytest.mark.unit
    def test_singular_matrix_rejected(self):
        """MathNet 对奇异矩阵返回 NaN/Inf，必须显式拒绝以对齐 NumPy 语义。"""
        with pytest.raises(CsNumEngineError):
            _real_engine.solve_linear_system(np.array([[1.0, 2.0], [2.0, 4.0]]), np.array([1.0, 2.0]))
