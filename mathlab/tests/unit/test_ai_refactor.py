"""ai_manager 拆分后的回归测试。

覆盖三块新/改结构：

* ``mathlab/core/ai_engine_worker.py`` —— Qt/openai 兼容层与流式工作线程
* ``mathlab/core/planner_agent.py`` —— 教研组长及其 ``StepResultCollector``
* ``mathlab/core/ai_manager.py::SolveCallbacks`` / ``BaseMathAgent.solve_problem`` 各环节

设计原则：全部打桩，不发网络请求、不启动真实 QThread、不写真实记忆目录。
"""

import types

import pytest

from mathlab.core import ai_manager as ai_mod
from mathlab.core import planner_agent as planner_mod
from mathlab.core.ai_engine_worker import (
    AIEngineWorker,
    AIState,
    describe_api_error,
)
from mathlab.core.ai_manager import SolveCallbacks
from mathlab.core.planner_agent import StepResultCollector

_NO_CLIENT = object()


def _fake_manager(client=_NO_CLIENT):
    """最小可用的 AIManager 替身：只需要 client / current_model / file_memory。

    ``client`` 省略时给一个占位对象（表示"已配置"）；显式传 None 表示未配置。
    """
    return types.SimpleNamespace(
        client=object() if client is _NO_CLIENT else client,
        current_model="stub-model",
        file_memory=None,
    )


# ======================================================================
# 兼容层与流式工作线程
# ======================================================================
class TestAIEngineWorkerModule:
    """ai_engine_worker 独立成模块后的契约。"""

    @pytest.mark.unit
    def test_compat_layer_is_reexported(self):
        """ai_manager 仍要能拿到 Qt/openai 兼容层（历史导入路径不能断）。"""
        for name in (
            "AIEngineWorker",
            "AIState",
            "OpenAI",
            "QObject",
            "QThread",
            "Signal",
            "describe_api_error",
        ):
            assert hasattr(ai_mod, name), f"ai_manager 丢失 re-export: {name}"

    @pytest.mark.unit
    def test_worker_and_state_come_from_new_module(self):
        assert AIEngineWorker.__module__ == "mathlab.core.ai_engine_worker"
        assert AIState.__module__ == "mathlab.core.ai_engine_worker"
        assert describe_api_error.__module__ == "mathlab.core.ai_engine_worker"

    @pytest.mark.unit
    def test_planner_is_lazily_forwarded(self):
        """PlannerAgent 已迁走，但旧导入路径必须还能用（避免循环导入只能用 __getattr__）。"""
        assert ai_mod.PlannerAgent is planner_mod.PlannerAgent
        with pytest.raises(AttributeError):
            ai_mod.DefinitelyNotHere

    @pytest.mark.unit
    def test_describe_api_error_generic_fallback(self):
        assert describe_api_error(RuntimeError("boom"))


class TestToolCallAccumulation:
    """tool_calls 分片聚合（不启动线程，直接调方法）。"""

    @staticmethod
    def _delta(index, name=None, arguments=None):
        fn = None
        if name is not None or arguments is not None:
            fn = types.SimpleNamespace(name=name, arguments=arguments)
        return types.SimpleNamespace(index=index, function=fn)

    @pytest.mark.unit
    def test_name_and_arguments_are_merged_across_chunks(self):
        buffer = {}
        AIEngineWorker._accumulate_tool_call(buffer, self._delta(0, name="draw", arguments='{"x":'))
        AIEngineWorker._accumulate_tool_call(buffer, self._delta(0, arguments="1}"))

        assert buffer[0] == {"name": "draw", "arguments": '{"x":1}'}

    @pytest.mark.unit
    def test_later_chunk_can_fix_name(self):
        buffer = {}
        AIEngineWorker._accumulate_tool_call(buffer, self._delta(0, name="", arguments="{}"))
        AIEngineWorker._accumulate_tool_call(buffer, self._delta(0, name="real_name"))

        assert buffer[0]["name"] == "real_name"

    @pytest.mark.unit
    def test_multiple_indices_are_isolated(self):
        buffer = {}
        AIEngineWorker._accumulate_tool_call(buffer, self._delta(0, name="a", arguments="1"))
        AIEngineWorker._accumulate_tool_call(buffer, self._delta(1, name="b", arguments="2"))

        assert set(buffer) == {0, 1}
        assert buffer[1]["name"] == "b"

    @pytest.mark.unit
    def test_emit_tool_calls_parses_json_and_survives_bad_json(self):
        emitted = []
        worker = AIEngineWorker.__new__(AIEngineWorker)
        worker.tool_call_received = types.SimpleNamespace(emit=lambda name, args: emitted.append((name, args)))
        worker.state_changed = types.SimpleNamespace(emit=lambda _s: None)

        worker._emit_tool_calls(
            {
                0: {"name": "draw", "arguments": '{"x": 1}'},
                1: {"name": "broken", "arguments": "{not json"},
                2: {"name": "empty", "arguments": ""},
            }
        )

        assert emitted[0] == ("draw", {"x": 1})
        assert emitted[1] == ("broken", {})
        assert emitted[2] == ("empty", {})


class TestStreamConsumption:
    """_consume_stream：usage 上报、取消、首字节状态切换。"""

    @staticmethod
    def _chunk(content=None, tool_calls=None, usage=None):
        delta = types.SimpleNamespace(content=content, tool_calls=tool_calls)
        return types.SimpleNamespace(
            usage=usage, choices=[types.SimpleNamespace(delta=delta)] if (content or tool_calls) else []
        )

    @pytest.mark.unit
    def test_collects_text_and_reports_usage(self):
        worker = AIEngineWorker.__new__(AIEngineWorker)
        worker._is_cancelled = False
        chunks_seen = []
        worker.chunk_received = types.SimpleNamespace(emit=chunks_seen.append)
        worker.usage_reported = types.SimpleNamespace(emit=lambda *_a: None)
        worker.state_changed = types.SimpleNamespace(emit=lambda _s: None)

        usage = types.SimpleNamespace(prompt_tokens=3, completion_tokens=4)
        stream = [
            self._chunk(usage=usage),
            self._chunk(content="你好"),
            self._chunk(content="世界"),
        ]
        text, buffer = worker._consume_stream(stream)

        assert text == "你好世界"
        assert chunks_seen == ["你好", "世界"]
        assert buffer == {}

    @pytest.mark.unit
    def test_cancel_stops_consuming(self):
        worker = AIEngineWorker.__new__(AIEngineWorker)
        worker._is_cancelled = True
        worker.chunk_received = types.SimpleNamespace(emit=lambda _t: None)
        worker.usage_reported = types.SimpleNamespace(emit=lambda *_a: None)
        worker.state_changed = types.SimpleNamespace(emit=lambda _s: None)

        text, _ = worker._consume_stream([self._chunk(content="不应被消费")])
        assert text == ""

    @pytest.mark.unit
    def test_generating_state_emitted_once(self):
        worker = AIEngineWorker.__new__(AIEngineWorker)
        worker._is_cancelled = False
        states = []
        worker.chunk_received = types.SimpleNamespace(emit=lambda _t: None)
        worker.usage_reported = types.SimpleNamespace(emit=lambda *_a: None)
        worker.state_changed = types.SimpleNamespace(emit=states.append)

        worker._consume_stream([self._chunk(content="a"), self._chunk(content="b")])

        assert states == [AIState.GENERATING]


# ======================================================================
# SolveCallbacks
# ======================================================================
class TestSolveCallbacks:
    """回调集合的 None 安全。"""

    @pytest.mark.unit
    def test_all_none_is_inert(self):
        cbs = SolveCallbacks()
        cbs.thought("x")
        cbs.code("y")
        cbs.finish(True, "z")
        cbs.geom([1])

    @pytest.mark.unit
    def test_forwards_to_wrapped_callbacks(self):
        seen = []
        cbs = SolveCallbacks(
            thought=lambda t: seen.append(("t", t)),
            code=lambda c: seen.append(("c", c)),
            finish=lambda s, c: seen.append(("f", s, c)),
            geom=lambda g: seen.append(("g", g)),
        )
        cbs.thought("思考")
        cbs.code("print(1)")
        cbs.finish(True, "done")
        cbs.geom([{"cmd": "add_point"}])

        assert seen == [
            ("t", "思考"),
            ("c", "print(1)"),
            ("f", True, "done"),
            ("g", [{"cmd": "add_point"}]),
        ]


# ======================================================================
# StepResultCollector
# ======================================================================
class TestStepResultCollector:
    """子步骤回调收集器（原 solve_problem 内的四个嵌套闭包工厂）。"""

    @pytest.mark.unit
    def test_thought_cb_is_prefixed_with_step_number(self):
        seen = []
        c = StepResultCollector(2, thought_cb=seen.append)
        c.make_thought_cb()("正在计算")
        assert seen == ["  [Step 2] 正在计算"]

    @pytest.mark.unit
    def test_code_cb_stores_and_forwards(self):
        seen = []
        c = StepResultCollector(1, code_cb=seen.append)
        c.make_code_cb()("print(1)")
        assert c.code == "print(1)"
        assert seen == ["print(1)"]

    @pytest.mark.unit
    def test_finish_cb_sets_success_and_code(self):
        c = StepResultCollector(1)
        c.make_finish_cb()(True, "final")
        assert c.success is True
        assert c.code == "final"

    @pytest.mark.unit
    def test_finish_cb_failure_keeps_code(self):
        c = StepResultCollector(1)
        c.make_finish_cb()(False, "")
        assert c.success is False
        assert c.code == ""

    @pytest.mark.unit
    def test_geom_cb_accumulates_and_forwards(self):
        seen = []
        c = StepResultCollector(1, geom_cb=seen.append)
        cb = c.make_geom_cb()
        cb([{"cmd": "a"}])
        cb([{"cmd": "b"}])
        assert c.geom == [{"cmd": "a"}, {"cmd": "b"}]
        assert seen == [[{"cmd": "a"}], [{"cmd": "b"}]]

    @pytest.mark.unit
    def test_as_tuple_shape(self):
        c = StepResultCollector(3)
        c.code = "x"
        assert c.as_tuple() == (3, False, "x", [])


# ======================================================================
# PlannerAgent 环节拆分
# ======================================================================
def _make_planner(client=_NO_CLIENT, registry=None):
    """构造一个不依赖网络的 PlannerAgent。默认"已配置 API Key"。"""
    return planner_mod.PlannerAgent(ai_manager=_fake_manager(client), agent_registry=registry)


class TestPlannerStepSplitting:
    """_split_steps_by_mode：并行/串行分组。"""

    @pytest.mark.unit
    def test_parallel_disabled_puts_everything_in_serial(self):
        planner = _make_planner()
        steps = [
            {"num": 1, "parallelizable": True},
            {"num": 2, "parallelizable": False},
        ]
        parallel, serial = planner._split_steps_by_mode(steps)
        assert parallel == []
        assert len(serial) == 2

    @pytest.mark.unit
    def test_parallel_enabled_respects_flag(self):
        planner = planner_mod.PlannerAgent(ai_manager=_fake_manager(), agent_registry=None, parallel_execution=True)
        steps = [
            {"num": 1, "parallelizable": True},
            {"num": 2, "parallelizable": False},
        ]
        parallel, serial = planner._split_steps_by_mode(steps)
        assert [s["num"] for s in parallel] == [1]
        assert [s["num"] for s in serial] == [2]


class TestPlannerAgentSelection:
    """_pick_sub_agent：按注册表描述动态路由。"""

    @staticmethod
    def _registry(agents):
        return types.SimpleNamespace(agents=agents)

    @pytest.mark.unit
    def test_no_registry_falls_back_to_geometry(self):
        assert _make_planner()._pick_sub_agent("画图", "") == "GeometryAgent"

    @pytest.mark.unit
    def test_viz_keyword_routes_to_viz_agent(self):
        registry = self._registry(
            {
                "geo": {"description": "解析几何专家"},
                "viz": {"description": "数据可视化专家 ECharts"},
            }
        )
        picked = _make_planner(registry=registry)._pick_sub_agent("画一个柱状图", "")
        assert picked == "viz"

    @pytest.mark.unit
    def test_non_viz_task_routes_to_geometry_agent(self):
        registry = self._registry(
            {
                "geo": {"description": "解析几何专家"},
                "viz": {"description": "数据可视化专家 ECharts"},
            }
        )
        picked = _make_planner(registry=registry)._pick_sub_agent("证明三角形全等", "")
        assert picked == "geo"

    @pytest.mark.unit
    def test_fallback_skips_planner_itself(self):
        registry = self._registry(
            {
                "PlannerAgent": {"description": "教研组长"},
                "somebody": {"description": "通用专家"},
            }
        )
        assert _make_planner(registry=registry)._pick_sub_agent("随便", "") == "somebody"


class TestPlannerDecomposeFallback:
    """_decompose_problem 的降级路径。"""

    @pytest.mark.unit
    def test_returns_fallback_plan_when_llm_fails(self):
        planner = _make_planner()
        boom = types.SimpleNamespace(
            chat=types.SimpleNamespace(
                completions=types.SimpleNamespace(
                    create=lambda **_kw: (_ for _ in ()).throw(RuntimeError("network down"))
                )
            )
        )
        planner.ai_manager.client = boom

        plan = planner._decompose_problem("讲一下圆锥曲线")
        assert plan["topic"] == "讲一下圆锥曲线"
        assert len(plan["steps"]) == 3
        assert all(s["parallelizable"] is False for s in plan["steps"])

    @pytest.mark.unit
    def test_fallback_steps_are_copies(self):
        """兜底大纲是常量，必须每次拷贝，避免调用方改脏全局。"""
        planner = _make_planner()
        boom = types.SimpleNamespace(
            chat=types.SimpleNamespace(
                completions=types.SimpleNamespace(create=lambda **_kw: (_ for _ in ()).throw(RuntimeError("x")))
            )
        )
        planner.ai_manager.client = boom

        first = planner._decompose_problem("a")
        first["steps"][0]["title"] = "被改坏了"
        second = planner._decompose_problem("b")

        assert second["steps"][0]["title"] == "理解问题与分析已知条件"


class TestPlannerSolveProblemGuards:
    """solve_problem 的前置校验与回退。"""

    @pytest.mark.unit
    def test_missing_client_short_circuits(self):
        planner = _make_planner(client=None)
        thoughts, finishes = [], []
        result = planner.solve_problem(
            "讲一下三角形",
            on_thought_cb=thoughts.append,
            on_finish_cb=lambda s, c: finishes.append((s, c)),
        )
        assert result["status"] == "failed"
        assert finishes == [(False, "未配置 API Key")]
        assert thoughts

    @pytest.mark.unit
    def test_empty_plan_falls_back_to_base_agent(self):
        planner = _make_planner()
        planner._decompose_problem = lambda _p: {"topic": "t", "steps": []}

        called = {}

        def _stub(self, prompt, *_args, **_kw):
            called["prompt"] = prompt
            return {"status": "ok", "code": "base", "geom_commands": []}

        original = ai_mod.BaseMathAgent.solve_problem
        ai_mod.BaseMathAgent.solve_problem = _stub
        try:
            result = planner.solve_problem("讲一下三角形")
        finally:
            ai_mod.BaseMathAgent.solve_problem = original

        assert result["status"] == "ok"
        assert called["prompt"] == "讲一下三角形"

    @pytest.mark.unit
    def test_unregistered_sub_agent_runs_step_by_self(self):
        planner = _make_planner(registry=None)
        planner._decompose_problem = lambda _p: {
            "topic": "t",
            "steps": [{"num": 1, "title": "步骤一", "hint_for_teacher": "提示"}],
        }

        original = ai_mod.BaseMathAgent.solve_problem

        def _stub(self, prompt, *_args, **_kw):
            return {"status": "ok", "code": "self-run", "geom_commands": [{"cmd": "add_point"}]}

        ai_mod.BaseMathAgent.solve_problem = _stub
        try:
            result = planner.solve_problem("讲一下三角形")
        finally:
            ai_mod.BaseMathAgent.solve_problem = original

        assert result["status"] == "ok"
        assert "self-run" in result["code"]
        assert result["geom_commands"] == [{"cmd": "add_point"}]

    @pytest.mark.unit
    def test_delegates_to_registered_sub_agent(self):
        calls = []

        class Sub:
            def solve_problem(self, prompt, on_thought_cb=None, on_code_cb=None, on_finish_cb=None, on_geom_cb=None):
                calls.append(prompt)
                if on_code_cb:
                    on_code_cb("sub-code")
                if on_finish_cb:
                    on_finish_cb(True, "sub-code")
                return {"status": "ok", "code": "sub-code", "geom_commands": []}

        registry = types.SimpleNamespace(agents={"geo": {"instance": Sub(), "description": "解析几何专家"}})
        planner = _make_planner(registry=registry)
        planner._decompose_problem = lambda _p: {
            "topic": "三角形",
            "steps": [{"num": 1, "title": "画底边", "hint_for_teacher": "先画"}],
        }
        planner._pick_sub_agent = lambda _t, _h: "geo"

        result = planner.solve_problem("讲一下三角形")

        assert result["status"] == "ok"
        assert "sub-code" in result["code"]
        assert len(calls) == 1


# ======================================================================
# BaseMathAgent.solve_problem 拆分后的各环节
# ======================================================================
class TestBaseAgentSolveStages:
    """拆分出来的各个小环节。"""

    @pytest.mark.unit
    def test_missing_client_short_circuits(self):
        agent = ai_mod.BaseMathAgent(ai_manager=_fake_manager(client=None))
        finishes = []
        result = agent.solve_problem("x", on_finish_cb=lambda s, c: finishes.append((s, c)))
        assert result["error"] == "未配置 API Key"
        assert finishes == [(False, "未配置 API Key")]

    @pytest.mark.unit
    def test_replay_cached_result_feeds_all_callbacks(self):
        agent = ai_mod.BaseMathAgent(ai_manager=_fake_manager())
        seen = []
        cbs = SolveCallbacks(
            thought=seen.append,
            code=lambda c: seen.append(c),
            finish=lambda s, c: seen.append((s, c)),
            geom=seen.append,
        )
        cached = {"status": "ok", "code": "cached-code", "geom_commands": [{"cmd": "add_point"}]}

        result = agent._replay_cached_result(cached, cbs)

        assert result is cached
        assert "cached-code" in seen
        assert (True, "cached-code") in seen
        assert [{"cmd": "add_point"}] in seen

    @pytest.mark.unit
    def test_execute_code_wraps_exception(self):
        agent = ai_mod.BaseMathAgent(ai_manager=_fake_manager())

        def _boom(_code):
            raise RuntimeError("sandbox exploded")

        ai_mod.execute_math_task = _boom
        try:
            result = agent._execute_code("print(1)")
        finally:
            import importlib

            ai_mod.execute_math_task = importlib.import_module("mathlab.core.ai_tools").execute_math_task

        assert result["status"] == "error"
        assert "sandbox exploded" in result["error"]

    @pytest.mark.unit
    def test_execute_code_accepts_dict_result(self):
        agent = ai_mod.BaseMathAgent(ai_manager=_fake_manager())
        ai_mod.execute_math_task = lambda _c: {"status": "ok", "output": "hi"}
        try:
            assert agent._execute_code("x")["status"] == "ok"
        finally:
            import importlib

            ai_mod.execute_math_task = importlib.import_module("mathlab.core.ai_tools").execute_math_task

    @pytest.mark.unit
    def test_append_failure_feedback_trims_history(self):
        agent = ai_mod.BaseMathAgent(ai_manager=_fake_manager())
        messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]

        for i in range(10):
            agent._append_failure_feedback(messages, f"code{i}", f"err{i}")

        assert len(messages) == agent.MAX_HISTORY_MSGS
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    @pytest.mark.unit
    def test_build_initial_messages_injects_prompt(self):
        agent = ai_mod.BaseMathAgent(ai_manager=_fake_manager())
        agent.system_prompt = "SYS"
        agent.skill_lib = types.SimpleNamespace(retrieve_relevant_skills=lambda _p: [])

        messages = agent._build_initial_messages("求根", SolveCallbacks())
        assert messages[0]["role"] == "system"
        assert "SYS" in messages[0]["content"]
        assert messages[1]["content"] == "任务：求根"
