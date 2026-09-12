"""架构重构后的测试覆盖。

测试新增的模块和修复的架构债务：
- GeometryEngine Qt 信号系统
- 统一配置管理 (config_manager)
- AI 范式门面 (AIFacade)
- 版本号一致性 (version)
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Headless Qt
os.environ["QT_QPA_PLATFORM"] = "offscreen"


# ═══════════════════════════════════════════════════════════════════════════
# GeometryEngine Qt 信号系统测试
# ═══════════════════════════════════════════════════════════════════════════


class TestGeometryEngineSignals:
    """测试 GeometryEngine 的 Qt 信号替代手写 listener。"""

    @pytest.fixture
    def engine(self):
        from mathlab.core.geometry_engine import GeometryEngine

        return GeometryEngine()

    def test_object_added_signal_emitted(self, engine):
        """添加点时应发射 object_added 信号。"""
        received = []
        engine.object_added.connect(lambda data: received.append(data))

        engine.add_point(1.0, 2.0, name="A")

        assert len(received) == 1
        assert received[0]["name"] == "A"
        assert received[0]["type"] == "Point"

    def test_object_updated_signal_emitted(self, engine):
        """更新点时应发射 object_updated 信号。"""
        received = []
        engine.object_updated.connect(lambda data: received.append(data))

        point_id = engine.add_point(1.0, 2.0)
        received.clear()  # 清除 add_point 的信号

        engine.update_point(point_id, x=5.0)
        assert len(received) == 1
        assert received[0]["coordinates"]["x"] == 5.0

    def test_object_removed_signal_emitted(self, engine):
        """删除对象时应发射 object_removed 信号。"""
        received = []
        engine.object_removed.connect(lambda data: received.append(data))

        point_id = engine.add_point(1.0, 2.0)
        engine.remove_object(point_id)

        assert len(received) >= 1

    def test_geometry_event_signal_emitted(self, engine):
        """通用 geometry_event 信号应携带事件类型和数据。"""
        received = []
        engine.geometry_event.connect(lambda etype, data: received.append((etype, data)))

        engine.add_point(1.0, 2.0)

        assert len(received) == 1
        assert received[0][0] == "object_added"

    def test_signals_blocked(self, engine):
        """block_signals 应阻止信号发射。"""
        received = []
        engine.object_added.connect(lambda data: received.append(data))

        engine.block_signals(True)
        engine.add_point(1.0, 2.0)

        assert len(received) == 0

        engine.block_signals(False)
        engine.add_point(3.0, 4.0)

        assert len(received) == 1

    def test_backward_compatible_listener(self, engine):
        """旧式 add_listener 回调仍应正常工作。"""
        received = []
        engine.add_listener(lambda etype, data: received.append((etype, data)))

        engine.add_point(1.0, 2.0)

        assert len(received) == 1
        assert received[0][0] == "object_added"

    def test_remove_listener(self, engine):
        """remove_listener 应正确移除监听器。"""
        received = []

        def listener(etype, data):
            received.append((etype, data))

        engine.add_listener(listener)
        engine.add_point(1.0, 2.0)
        count_before = len(received)

        engine.remove_listener(listener)
        engine.add_point(3.0, 4.0)

        assert len(received) == count_before  # 没有新增

    def test_qt_signal_and_listener_both_fire(self, engine):
        """Qt 信号和旧式监听器应同时触发。"""
        signal_received = []
        listener_received = []

        engine.object_added.connect(lambda data: signal_received.append(data))
        engine.add_listener(lambda etype, data: listener_received.append(data))

        engine.add_point(1.0, 2.0)

        assert len(signal_received) == 1
        assert len(listener_received) == 1


# ═══════════════════════════════════════════════════════════════════════════
# 统一配置管理测试
# ═══════════════════════════════════════════════════════════════════════════


class TestConfigManager:
    """测试统一配置管理模块。"""

    def test_get_default_config(self):
        """未加载配置文件时应返回默认值。"""
        from mathlab.utils.config_manager import get_config

        # IPC 端口应有默认值
        port = get_config("ipc.server_port", default=99999)
        assert port == 45678

    def test_get_nested_config(self):
        """嵌套键访问应正常工作。"""
        from mathlab.utils.config_manager import get_config

        timeout = get_config("sandbox.timeout", default=999)
        assert timeout == 30

    def test_get_nonexistent_key_returns_default(self):
        """不存在的键应返回默认值。"""
        from mathlab.utils.config_manager import get_config

        val = get_config("nonexistent.key", default="fallback")
        assert val == "fallback"

    def test_get_full_config(self):
        """key=None 应返回整个配置字典。"""
        from mathlab.utils.config_manager import get_config

        config = get_config()
        assert isinstance(config, dict)
        assert "ipc" in config

    def test_set_config_runtime(self):
        """set_config 应在运行时更新缓存。"""
        from mathlab.utils.config_manager import get_config, set_config

        set_config("ipc.server_port", 55555)
        assert get_config("ipc.server_port") == 55555
        # 恢复默认
        set_config("ipc.server_port", 45678)

    def test_deep_merge(self):
        """_deep_merge 应正确递归合并字典。"""
        from mathlab.utils.config_manager import _deep_merge

        base = {"a": {"b": 1, "c": 2}, "d": 3}
        override = {"a": {"b": 10}, "e": 4}
        result = _deep_merge(base, override)
        assert result == {"a": {"b": 10, "c": 2}, "d": 3, "e": 4}


# ═══════════════════════════════════════════════════════════════════════════
# AI 范式门面测试
# ═══════════════════════════════════════════════════════════════════════════


class TestAIFacade:
    """测试 AI 范式门面的意图分类和路由。"""

    @pytest.fixture
    def facade(self):
        from mathlab.core.ai_facade import AIFacade

        # 使用 mock 对象避免真实 AI 初始化

        class MockAIManager:
            def ask(self, **kwargs):
                pass

        class MockAgentRegistry:
            def route_and_execute(self, **kwargs):
                pass

        return AIFacade(MockAIManager(), MockAgentRegistry())

    @pytest.mark.parametrize(
        "prompt,expected",
        [
            ("画一个圆", "simple_tool_call"),
            ("绘制三角形", "simple_tool_call"),
            ("出一道测验题", "simple_tool_call"),
            ("证明三角形内角和为180度", "complex_reasoning"),
            ("求解方程 x^2 - 4 = 0", "complex_reasoning"),
            ("计算积分 x^2 dx", "complex_reasoning"),
            ("推导勾股定理", "complex_reasoning"),
            ("化简表达式 (x+1)^2", "complex_reasoning"),
        ],
    )
    def test_classify_intent(self, facade, prompt, expected):
        """测试意图分类正确性。"""
        result = facade.classify_intent(prompt)
        assert result.value == expected

    def test_route_simple_tool_call(self, facade):
        """简单工具调用应路由到 Function Calling。"""
        from mathlab.core.ai_facade import AITaskType

        called = {}

        facade._run_function_calling = lambda *args, **kwargs: called.update({"fc": True})
        facade._run_agent_loop = lambda *args, **kwargs: called.update({"agent": True})

        result = facade.route_request("画一个圆")
        assert result == AITaskType.SIMPLE_TOOL_CALL
        assert called.get("fc") is True
        assert "agent" not in called

    def test_route_complex_reasoning(self, facade):
        """复杂推理应路由到 Agent 系统。"""
        from mathlab.core.ai_facade import AITaskType

        called = {}

        facade._run_function_calling = lambda *args, **kwargs: called.update({"fc": True})
        facade._run_agent_loop = lambda *args, **kwargs: called.update({"agent": True})

        result = facade.route_request("证明勾股定理")
        assert result == AITaskType.COMPLEX_REASONING
        assert called.get("agent") is True
        assert "fc" not in called

    def test_route_without_registry_calls_error(self):
        """无 AgentRegistry 时复杂任务应回调 on_error。"""
        from mathlab.core.ai_facade import AIFacade

        class MockAIManager:
            def ask(self, **kwargs):
                pass

        facade = AIFacade(MockAIManager(), agent_registry=None)
        errors = []
        facade.route_request("求解方程", on_error=lambda msg: errors.append(msg))
        assert len(errors) == 1
        assert "Agent" in errors[0]


# ═══════════════════════════════════════════════════════════════════════════
# 版本号一致性测试
# ═══════════════════════════════════════════════════════════════════════════


class TestVersionConsistency:
    """测试版本号统一管理。"""

    def test_version_importable(self):
        """version 模块应可导入且格式正确。"""
        from mathlab.utils.version import __version__

        assert __version__ == "3.8.0"

    def test_version_info_tuple(self):
        """__version_info__ 应为正确的元组。"""
        from mathlab.utils.version import __version_info__

        assert __version_info__ == (3, 8, 0)

    def test_version_string_format(self):
        """版本号应符合语义化版本格式。"""
        from mathlab.utils.version import __version__

        parts = __version__.split(".")
        assert len(parts) == 3
        for part in parts:
            assert part.isdigit()


# ═══════════════════════════════════════════════════════════════════════════
# Models 子包向后兼容测试
# ═══════════════════════════════════════════════════════════════════════════


class TestModelsBackwardCompat:
    """测试 geometry_engine.py 拆分后的向后兼容性。"""

    def test_import_from_geometry_engine(self):
        """从 geometry_engine 导入所有类应正常工作。"""
        from mathlab.core.geometry_engine import (  # noqa: F401
            DAG,
            Circle,
            ConicSection,
            Ellipse,
            FunctionPlot,
            GeometricObject,
            Hyperbola,
            ImplicitPlot,
            Intersection,
            Locus,
            Parabola,
            Point,
            PolarPlot,
            Polygon,
            Segment,
        )

        assert Point is not None
        assert Segment is not None
        assert Circle is not None

    def test_import_from_models(self):
        """从 models 子包导入应返回相同的类对象。"""
        from mathlab.core.geometry_engine import Point as P1
        from mathlab.core.models import Point as P2

        assert P1 is P2

    def test_models_init_all(self):
        """models.__init__ 应导出所有类。"""
        from mathlab.core.models import __all__

        assert "Point" in __all__
        assert "Segment" in __all__
        assert "Circle" in __all__
        assert "DAG" in __all__
        assert "GeometricObject" in __all__

    def test_point_creation_from_models(self):
        """从 models 导入的 Point 应能正常创建实例。"""
        from mathlab.core.models import Point

        p = Point("p1", "A", 1.0, 2.0)
        assert p.name == "A"
        assert p.coordinates["x"] == 1.0

    def test_dag_from_models(self):
        """从 models 导入的 DAG 应能正常工作。"""
        from mathlab.core.models import DAG

        dag = DAG()
        dag.add_edge("A", "B")
        deps = dag.get_dependencies("B")
        assert "A" in deps
