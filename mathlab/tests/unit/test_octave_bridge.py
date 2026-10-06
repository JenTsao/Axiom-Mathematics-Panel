"""OctaveBridge 单元测试套件。

Uses the shared ``bridge`` fixture from the root conftest.py instead
of a local fixture definition. All test functions are marked with
``@pytest.mark.unit``. The ``TestNumEngineIntegration`` class is
excluded here (moved to integration tests).

运行方式:
    pytest mathlab/tests/unit/test_octave_bridge.py -v
"""

import math

import numpy as np
import pytest

from mathlab.core.octave_bridge import OctaveBridgeError

# ─────────────────────────────────────────────────────────────
# 矩阵字面量翻译 (Matrix Literal Translation)
# ─────────────────────────────────────────────────────────────


class TestMatrixLiterals:
    @pytest.mark.unit
    def test_1d_row_vector_spaces(self, bridge):
        """[1 2 3] → np.array([1, 2, 3])"""
        assert bridge.translate("[1 2 3]") == "np.array([1, 2, 3])"

    @pytest.mark.unit
    def test_1d_row_vector_commas(self, bridge):
        """[1, 2, 3] → np.array([1, 2, 3])"""
        assert bridge.translate("[1, 2, 3]") == "np.array([1, 2, 3])"

    @pytest.mark.unit
    def test_2d_matrix(self, bridge):
        """[1 2; 3 4] → np.array([[1, 2], [3, 4]])"""
        assert bridge.translate("[1 2; 3 4]") == "np.array([[1, 2], [3, 4]])"

    @pytest.mark.unit
    def test_2d_matrix_with_commas(self, bridge):
        """[1, 2; 3, 4] → np.array([[1, 2], [3, 4]])"""
        assert bridge.translate("[1, 2; 3, 4]") == "np.array([[1, 2], [3, 4]])"

    @pytest.mark.unit
    def test_column_vector(self, bridge):
        """[1; 2; 3] → np.array([[1], [2], [3]])"""
        assert bridge.translate("[1; 2; 3]") == "np.array([[1], [2], [3]])"

    @pytest.mark.unit
    def test_empty_matrix(self, bridge):
        """[] → np.array([])"""
        assert bridge.translate("[]") == "np.array([])"

    @pytest.mark.unit
    def test_evaluate_matrix(self, bridge):
        """矩阵字面量求值应返回正确的 ndarray"""
        result = bridge.evaluate("[1 2; 3 4]")
        np.testing.assert_array_equal(result, np.array([[1, 2], [3, 4]]))

    @pytest.mark.unit
    def test_evaluate_row_vector(self, bridge):
        result = bridge.evaluate("[1 2 3]")
        np.testing.assert_array_equal(result, np.array([1, 2, 3]))


# ─────────────────────────────────────────────────────────────
# 运算符翻译 (Operator Translation)
# ─────────────────────────────────────────────────────────────


class TestOperatorTranslation:
    @pytest.mark.unit
    def test_matrix_multiply_translated(self, bridge):
        """* 应翻译为 @（矩阵乘法）"""
        assert "@" in bridge.translate("A * B")

    @pytest.mark.unit
    def test_elementwise_mul_preserved(self, bridge):
        """.*（逐元素乘）应翻译为 *"""
        translated = bridge.translate("A .* B")
        assert "*" in translated
        assert "@" not in translated

    @pytest.mark.unit
    def test_elementwise_div(self, bridge):
        """./（逐元素除）应翻译为 /"""
        translated = bridge.translate("A ./ B")
        assert "/" in translated

    @pytest.mark.unit
    def test_elementwise_pow(self, bridge):
        """.^（逐元素幂）应翻译为 **"""
        translated = bridge.translate("A .^ 2")
        assert "**" in translated

    @pytest.mark.unit
    def test_matrix_pow(self, bridge):
        """^（矩阵幂）应翻译为 **"""
        translated = bridge.translate("x ^ 2")
        assert "**" in translated

    @pytest.mark.unit
    def test_transpose(self, bridge):
        """A' 应翻译为 A.T"""
        assert bridge.translate("A'") == "A.T"

    @pytest.mark.unit
    def test_not_equal(self, bridge):
        """~= 应翻译为 !="""
        assert "!=" in bridge.translate("a ~= b")

    @pytest.mark.unit
    def test_comment(self, bridge):
        """% 应翻译为 #（注释符）"""
        assert "#" in bridge.translate("x = 1 % comment")


# ─────────────────────────────────────────────────────────────
# 矩阵运算求值 (Matrix Operations Evaluation)
# ─────────────────────────────────────────────────────────────


class TestMatrixOperations:
    @pytest.mark.unit
    def test_matrix_multiplication(self, bridge):
        """A * B → 矩阵乘法结果正确"""
        bridge.evaluate("A = [1 2; 3 4]")
        bridge.evaluate("B = [2 0; 0 2]")
        result = bridge.evaluate("A * B")
        expected = np.array([[1, 2], [3, 4]]) @ np.array([[2, 0], [0, 2]])
        np.testing.assert_array_equal(result, expected)

    @pytest.mark.unit
    def test_elementwise_multiplication(self, bridge):
        """A .* B → 逐元素乘法结果正确"""
        bridge.evaluate("A = [1 2; 3 4]")
        bridge.evaluate("B = [2 0; 0 2]")
        result = bridge.evaluate("A .* B")
        expected = np.array([[2, 0], [0, 8]])
        np.testing.assert_array_equal(result, expected)

    @pytest.mark.unit
    def test_transpose(self, bridge):
        """A' → 转置结果正确"""
        bridge.evaluate("A = [1 2; 3 4]")
        result = bridge.evaluate("A'")
        np.testing.assert_array_equal(result, np.array([[1, 3], [2, 4]]))

    @pytest.mark.unit
    def test_scalar_operations(self, bridge):
        """标量运算：x ^ 2 → x**2"""
        bridge.evaluate("x = 3")
        result = bridge.evaluate("x ^ 2")
        assert result == 9

    @pytest.mark.unit
    def test_elementwise_power(self, bridge):
        """v .^ 2 → 逐元素平方"""
        bridge.evaluate("v = [1 2 3]")
        result = bridge.evaluate("v .^ 2")
        np.testing.assert_array_equal(result, np.array([1, 4, 9]))

    @pytest.mark.unit
    def test_addition(self, bridge):
        """矩阵加法保持不变"""
        result = bridge.evaluate("[1 2] + [3 4]")
        np.testing.assert_array_equal(result, np.array([4, 6]))


# ─────────────────────────────────────────────────────────────
# 状态保持 (Stateful Environment)
# ─────────────────────────────────────────────────────────────


class TestStatefulEnvironment:
    @pytest.mark.unit
    def test_variable_persists_across_calls(self, bridge):
        """赋值后，变量在后续 evaluate 中可见"""
        bridge.evaluate("x = 42")
        result = bridge.evaluate("x")
        assert result == 42

    @pytest.mark.unit
    def test_multiple_assignments(self, bridge):
        """多次赋值后，所有变量均可访问"""
        bridge.evaluate("A = [1 2; 3 4]")
        bridge.evaluate("B = [5 6; 7 8]")
        bridge.evaluate("C = A + B")
        result = bridge.evaluate("C")
        expected = np.array([[6, 8], [10, 12]])
        np.testing.assert_array_equal(result, expected)

    @pytest.mark.unit
    def test_assignment_returns_value(self, bridge):
        """赋值语句应返回被赋值的变量值"""
        result = bridge.evaluate("M = [1 2; 3 4]")
        assert result is not None
        np.testing.assert_array_equal(result, np.array([[1, 2], [3, 4]]))

    @pytest.mark.unit
    def test_workspace(self, bridge):
        """workspace() 应列出用户变量"""
        bridge.evaluate("alpha = 3.14")
        ws = bridge.workspace()
        assert "alpha" in ws
        assert pytest.approx(ws["alpha"]) == 3.14

    @pytest.mark.unit
    def test_reset_clears_user_vars(self, bridge):
        """reset() 应清除用户变量，保留内置常量"""
        bridge.evaluate("myvar = 99")
        bridge.reset()
        ws = bridge.workspace()
        assert "myvar" not in ws
        # pi 仍然存在
        result = bridge.evaluate("pi")
        assert pytest.approx(result) == math.pi


# ─────────────────────────────────────────────────────────────
# 内置函数映射 (Built-in Function Mapping)
# ─────────────────────────────────────────────────────────────


class TestBuiltinFunctions:
    @pytest.mark.unit
    def test_zeros(self, bridge):
        result = bridge.evaluate("zeros(2, 3)")
        np.testing.assert_array_equal(result, np.zeros((2, 3)))

    @pytest.mark.unit
    def test_ones(self, bridge):
        result = bridge.evaluate("ones(2, 2)")
        np.testing.assert_array_equal(result, np.ones((2, 2)))

    @pytest.mark.unit
    def test_eye(self, bridge):
        result = bridge.evaluate("eye(3)")
        np.testing.assert_array_equal(result, np.eye(3))

    @pytest.mark.unit
    def test_linspace(self, bridge):
        """linspace(0, 10, 5) → [0, 2.5, 5, 7.5, 10]"""
        bridge.evaluate("v = linspace(0, 10, 5)")
        result = bridge.evaluate("sum(v)")
        assert pytest.approx(result) == 25.0

    @pytest.mark.unit
    def test_sum(self, bridge):
        result = bridge.evaluate("sum([1 2 3 4 5])")
        assert result == 15

    @pytest.mark.unit
    def test_max(self, bridge):
        result = bridge.evaluate("max([3 1 4 1 5 9])")
        assert result == 9

    @pytest.mark.unit
    def test_min(self, bridge):
        result = bridge.evaluate("min([3 1 4 1 5 9])")
        assert result == 1

    @pytest.mark.unit
    def test_abs(self, bridge):
        result = bridge.evaluate("abs(-5)")
        assert result == 5

    @pytest.mark.unit
    def test_sqrt(self, bridge):
        result = bridge.evaluate("sqrt(16)")
        assert pytest.approx(result) == 4.0

    @pytest.mark.unit
    def test_sin_cos(self, bridge):
        result = bridge.evaluate("sin(pi)")
        assert pytest.approx(result, abs=1e-10) == 0.0

    @pytest.mark.unit
    def test_pi_constant(self, bridge):
        result = bridge.evaluate("pi")
        assert pytest.approx(result) == math.pi

    @pytest.mark.unit
    def test_mean(self, bridge):
        result = bridge.evaluate("mean([1 2 3 4 5])")
        assert pytest.approx(result) == 3.0


# ─────────────────────────────────────────────────────────────
# 错误处理 (Error Handling)
# ─────────────────────────────────────────────────────────────


class TestErrorHandling:
    @pytest.mark.unit
    def test_invalid_code_raises(self, bridge):
        """无法执行的代码应抛出 OctaveBridgeError"""
        with pytest.raises(OctaveBridgeError):
            bridge.evaluate("this is not valid code !!!")

    @pytest.mark.unit
    def test_undefined_variable_raises(self, bridge):
        """访问未定义变量应抛出 OctaveBridgeError"""
        with pytest.raises(OctaveBridgeError):
            bridge.evaluate("undefined_var_xyz + 1")


class TestBuiltinDisp:
    """Octave 的 disp() 此前在 env 里没有定义，写它必然 NameError。"""

    @pytest.mark.unit
    def test_disp_returns_scalar(self, bridge):
        assert bridge.evaluate("disp(3)") == 3

    @pytest.mark.unit
    def test_disp_returns_matrix(self, bridge):
        import numpy as np

        result = bridge.evaluate("disp([1 2; 3 4])")
        assert np.array_equal(np.asarray(result), np.array([[1, 2], [3, 4]]))

    @pytest.mark.unit
    def test_disp_of_assigned_variable(self, bridge):
        bridge.evaluate("v = [1; 2; 3]")
        import numpy as np

        result = bridge.evaluate("disp(v)")
        assert np.array_equal(np.asarray(result).reshape(-1), np.array([1, 2, 3]))
