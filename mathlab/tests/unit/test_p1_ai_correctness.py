"""P1 修复的回归测试：AI 多智能体调度的正确性与网络层加固。

覆盖三件事：
1. **子任务只执行一遍**。PlannerAgent 曾同时通过消息总线（TASK_REQUEST 会被
   MessageRouter 同步转成 solve_problem 调用）和直接调用各跑一次子 Agent，
   导致双份 token 花费与重复的代码/几何命令回传。
2. **AI 客户端有超时与重试**。openai SDK 默认 read timeout 600s，网关挂死时
   用户要等 10 分钟才看到错误。
3. **异常不再原样进 UI**。原始 str(e) 会带出 base_url 与上游响应体。
"""

import types

import pytest

from mathlab.core import ai_manager as ai_mod
from mathlab.core.agent_message import MessageType


class RecordingBus:
    """只记录消息的假总线，用于断言 PlannerAgent 发了什么。"""

    def __init__(self):
        self.published = []

    def publish(self, message):
        self.published.append(message)
        return True


class CountingSubAgent:
    """记录被调用次数的假子 Agent。"""

    def __init__(self):
        self.calls = 0

    def solve_problem(self, prompt, on_thought_cb=None, on_code_cb=None, on_finish_cb=None, on_geom_cb=None):
        self.calls += 1
        if on_code_cb:
            on_code_cb("print(1)")
        if on_finish_cb:
            on_finish_cb(True, "done")
        return {"status": "ok", "code": "print(1)", "geom_commands": []}


def _make_planner(bus, sub_agent):
    """构造一个不依赖网络的 PlannerAgent：拆题与子 Agent 选择全部打桩。

    ``bus`` 为 None 时用一个只记录的假总线；传真实 MessageBus 时才会复现
    "总线消息被同步转成 solve_problem 调用" 的语义 —— 那正是双执行的来源。
    """
    fake_manager = types.SimpleNamespace(client=object(), current_model="stub-model", memory=None)

    planner = ai_mod.PlannerAgent(ai_manager=fake_manager, agent_registry=None)

    if bus is None:
        bus = RecordingBus()
    planner.set_message_bus(bus)

    registry = types.SimpleNamespace(agents={"geometry_agent": {"instance": sub_agent, "name": "几何"}})
    planner.agent_registry = registry

    planner._decompose_problem = lambda _prompt: {
        "topic": "三角形",
        "steps": [{"num": 1, "title": "构造三角形", "hint_for_teacher": "先画底边"}],
    }
    planner._pick_sub_agent = lambda _title, _hint: "geometry_agent"
    return planner


@pytest.mark.unit
class TestPlannerSingleExecution:
    """每个子任务必须且只能被执行一次。"""

    @staticmethod
    def _drive(planner):
        """跑一遍调度；基类的汇总求解打桩掉，避免真的发请求。"""
        base_cls = ai_mod.BaseMathAgent
        original = base_cls.solve_problem

        def _stubbed(self, *args, **kwargs):
            return {"status": "ok", "code": "", "geom_commands": []}

        base_cls.solve_problem = _stubbed
        try:
            planner.solve_problem("讲一下三角形", on_thought_cb=lambda _t: None)
        finally:
            base_cls.solve_problem = original

    def test_router_turns_task_request_into_one_solve_problem_call(self):
        """先钉住机制本身：TASK_REQUEST 会被 MessageRouter **同步**执行。

        这条断言解释了为什么规划器绝不能发 TASK_REQUEST —— 它不是"通知"，
        而是第二次真正的执行。
        """
        from mathlab.core.agent_message import AgentMessage, MessageBus, MessageRouter

        sub = CountingSubAgent()
        bus = MessageBus()
        router = MessageRouter(bus)
        router.register_agent("geometry_agent", sub)

        msg = AgentMessage(
            sender_id="someone",
            receiver_id="geometry_agent",
            msg_type=MessageType.TASK_REQUEST,
            content="画一个三角形",
        )
        bus.publish(msg)

        assert sub.calls == 1, "MessageRouter 不再把 TASK_REQUEST 转成执行 —— 上一条用例的前提需要重新评估"

    def test_sub_agent_executed_exactly_once_with_real_bus(self):
        """接真实总线+路由跑一遍调度：子 Agent 只能被调用 1 次。

        回归场景：规划器同时（a）发 TASK_REQUEST（经路由同步执行一次）和
        （b）直接调用 solve_problem（再一次）→ 双份 token 与重复回传。
        """
        from mathlab.core.agent_message import MessageBus, MessageRouter

        sub = CountingSubAgent()
        bus = MessageBus()
        router = MessageRouter(bus)
        router.register_agent("geometry_agent", sub)

        planner = _make_planner(bus, sub)
        self._drive(planner)

        assert sub.calls == 1, "子 Agent 被执行了 %d 次（历史缺陷：总线 + 直调 = 2 次）" % sub.calls

    def test_publishing_task_request_would_double_execute(self):
        """灵敏度证明：只要规划器再发 TASK_REQUEST，子 Agent 立刻变成 2 次调用。

        这条用例的意义是让上面那条 ``calls == 1`` 的断言不是空断言 ——
        它复现的正是修复前的状态（总线一次 + 直调一次）。
        """
        from mathlab.core.agent_message import MessageBus, MessageRouter

        sub = CountingSubAgent()
        bus = MessageBus()
        router = MessageRouter(bus)
        router.register_agent("geometry_agent", sub)

        planner = _make_planner(bus, sub)
        self._drive(planner)
        assert sub.calls == 1

        # 模拟被移除的那次总线派发
        planner.send_message(
            receiver_id="geometry_agent",
            msg_type=MessageType.TASK_REQUEST,
            content="画一个三角形",
        )
        assert sub.calls == 2, "TASK_REQUEST 不再触发执行 —— 双执行的成因需要重新确认"

    def test_planner_does_not_publish_task_request(self):
        """规划器只允许发通知/进度类消息，不允许发会触发执行的 TASK_REQUEST。"""
        bus = RecordingBus()
        sub = CountingSubAgent()
        planner = _make_planner(None, sub)
        planner.set_message_bus(bus)

        self._drive(planner)

        task_requests = [m for m in bus.published if getattr(m, "msg_type", None) == MessageType.TASK_REQUEST]
        assert not task_requests, "规划器又发了 TASK_REQUEST：%s" % [m.content for m in task_requests]


@pytest.mark.unit
class TestAiClientNetworkHardening:
    """客户端必须带超时与有限重试。"""

    def test_client_constructed_with_timeout_and_retries(self, monkeypatch):
        captured = {}

        class FakeOpenAI:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        monkeypatch.setattr(ai_mod, "OpenAI", FakeOpenAI)
        monkeypatch.setattr(ai_mod, "OPENAI_AVAILABLE", True)
        monkeypatch.setattr(ai_mod.os.path, "exists", lambda _p: True)
        monkeypatch.setattr(
            ai_mod.json,
            "load",
            lambda _fh: {
                "ai_api_key": "test-key-not-a-real-one",
                "ai_base_url": "http://127.0.0.1:9/v1",
                "ai_model": "stub-model",
            },
        )

        manager = ai_mod.AIManager.__new__(ai_mod.AIManager)
        manager.current_model = "stub-model"
        manager.reload_config()

        assert captured, "客户端没有被构造"
        assert "timeout" in captured, "未设置 timeout：挂死的网关会占据 600 秒"
        assert captured.get("max_retries") == ai_mod.AI_MAX_RETRIES
        assert isinstance(captured["timeout"], tuple) and len(captured["timeout"]) == 2

    def test_describe_api_error_does_not_leak_base_url(self):
        """错误文案面向用户，不能带出部署地址。"""
        import httpx

        if not ai_mod.OPENAI_AVAILABLE:
            pytest.skip("未安装 openai SDK")

        request = httpx.Request("POST", "http://internal-gw.corp:8080/v1/chat/completions")
        exc = ai_mod.APIConnectionError(
            message="Connection error. Request to http://internal-gw.corp:8080/v1/chat failed. body={'key':'abc'}",
            request=request,
        )

        text = ai_mod.describe_api_error(exc)

        assert "internal-gw" not in text
        assert "http" not in text
        assert "abc" not in text
        assert text  # 不能是空串，UI 需要可见提示

    def test_describe_api_error_classifies_auth(self):
        import httpx

        if not ai_mod.OPENAI_AVAILABLE:
            pytest.skip("未安装 openai SDK")

        request = httpx.Request("POST", "http://internal-gw.corp:8080/v1/chat/completions")
        response = httpx.Response(401, request=request)
        exc = ai_mod.AuthenticationError(
            "Error code 401: Invalid API key 'sk-abcdef'",
            response=response,
            body=None,
        )

        text = ai_mod.describe_api_error(exc)

        assert "sk-abcdef" not in text
        assert "http" not in text
        assert text
