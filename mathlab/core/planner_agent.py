"""教研组长 PlannerAgent（从 ``ai_manager.py`` 拆出）。

职责：

1. 将用户的数学问题拆解为 3-5 个由浅入深的教学步骤
2. 调度 GeometryAgent / DataVizAgent 执行每一步（支持串行/并行模式）
3. 汇总结果并给出最终教学总结

拆出动机：``PlannerAgent.solve_problem`` 原为 296 行、圈复杂度 58 的单体函数，
内部还嵌套了 5 个闭包（步骤执行器 + 4 个回调工厂），是 ``ai_manager.py`` 里
最难读也最难改的一块。这里把它拆成「开场广播 → 大纲产出 → 步骤执行 →
并行/串行调度 → 汇总评估」五个环节，闭包提升为 :class:`StepResultCollector`。
"""

import json
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

from mathlab.core.ai_manager import BaseMathAgent, ResourceConfig, SolveCallbacks
from mathlab.utils.logger import get_logger

logger = get_logger(__name__)

# 子步骤派发的关键词表：命中可视化类关键词时才考虑 DataVizAgent
_VIZ_KEYWORDS = (
    "图表",
    "可视化",
    "数据",
    "统计",
    "echarts",
    "柱状图",
    "折线图",
    "饼图",
    "散点图",
    "3d曲面",
    "玫瑰图",
    "热力图",
)
_VIZ_AGENT_HINTS = ("可视化", "图表", "echarts")
_GEOMETRY_AGENT_HINTS = ("几何", "geometry")

# _decompose_problem 失败时的兜底大纲
_FALLBACK_PLAN_STEPS = (
    {
        "num": 1,
        "title": "理解问题与分析已知条件",
        "hint_for_teacher": "引导学生识别问题类型和关键数值",
        "parallelizable": False,
    },
    {
        "num": 2,
        "title": "建立数学模型与计算方法",
        "hint_for_teacher": "将文字描述转化为方程或几何图形",
        "parallelizable": False,
    },
    {
        "num": 3,
        "title": "执行计算并验证结果",
        "hint_for_teacher": "通过数值计算或画图展示答案并检查合理性",
        "parallelizable": False,
    },
)


class StepResultCollector:
    """收集单个教学步骤中子 Agent 的回调输出。

    原先是 ``solve_problem`` 里的四个嵌套闭包工厂（``make_sub_*_cb``），
    每次调用都要重建一遍，且闭包共享的可变 ``step_result`` 字典散落在函数体里。
    提升为类之后状态与回调绑在一起，``_run_step`` 只需三行。
    """

    __slots__ = ("step_num", "success", "code", "geom", "_thought_cb", "_code_cb", "_geom_cb")

    def __init__(self, step_num, thought_cb=None, code_cb=None, geom_cb=None):
        self.step_num = step_num
        self.success = False
        self.code = ""
        self.geom = []
        self._thought_cb = thought_cb
        self._code_cb = code_cb
        self._geom_cb = geom_cb

    def make_thought_cb(self):
        """返回带「[Step N]」前缀的思考回调。"""

        def _cb(text):
            if self._thought_cb:
                self._thought_cb(f"  [Step {self.step_num}] {text}")

        return _cb

    def make_code_cb(self):
        """返回代码回调：既透传给上层，也留存到本步骤结果。"""

        def _cb(code):
            if self._code_cb:
                self._code_cb(code)
            self.code = code

        return _cb

    def make_finish_cb(self):
        """返回完成回调：记录成功标志与最终代码。"""

        def _cb(success, content):
            self.success = success
            if success and content:
                self.code = content

        return _cb

    def make_geom_cb(self):
        """返回几何命令回调：累积到本步骤并透传给上层。"""

        def _cb(cmds):
            self.geom.extend(cmds)
            if self._geom_cb:
                self._geom_cb(cmds)

        return _cb

    def as_tuple(self) -> tuple:
        """导出为 ``(num, success, code, geom_commands)``。"""
        return (self.step_num, self.success, self.code, self.geom)


class PlannerAgent(BaseMathAgent):
    """教研组长 —— 多智能体自治系统的顶层调度者。"""

    def __init__(
        self,
        ai_manager,
        agent_registry=None,
        model_override=None,
        resource_config=None,
        parallel_execution=False,
        max_workers=3,
        student_model=None,
    ):
        super().__init__(
            ai_manager,
            model_override=model_override,
            resource_config=resource_config or ResourceConfig.for_agent("PlannerAgent"),
            student_model=student_model,
        )
        self.agent_registry = agent_registry  # 持有全局路由大脑，用于子任务委派
        # 并行执行配置：当 parallel_execution=True 时，独立步骤可并行调度
        self.parallel_execution = parallel_execution
        self.max_workers = max_workers  # ThreadPoolExecutor 最大并发数
        # 教学法引导引擎：注入 Bloom/ZPD/UDL/Socratic 约束
        self._pedagogical_builder = None
        self._quality_evaluator = None
        if student_model is not None:
            from mathlab.core.pedagogical_engine import (
                PedagogicalPromptBuilder,
                TeachingQualityEvaluator,
            )

            self._pedagogical_builder = PedagogicalPromptBuilder(student_model)
            self._quality_evaluator = TeachingQualityEvaluator(student_model)
        self.system_prompt = """你是一个【数学教研组长 (PlannerAgent)】。
你的核心职责是分析用户的数学问题，将其拆解为 3-5 个由浅入深、循序渐进的教学步骤，
然后协调解析几何专家和数据可视化专家共同完成教学。
教学过程中禁止直接给出最终答案——要通过引导式提问让学生自己发现规律。
你的输出必须是严格的 JSON，不要包含任何其他文本。"""

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------
    def solve_problem(
        self,
        user_prompt: str,
        on_thought_cb=None,
        on_code_cb=None,
        on_finish_cb=None,
        on_geom_cb=None,
    ):
        """教研组长的核心调度闭环：拆解 → 串行/并行委派 → 汇总。"""
        cbs = SolveCallbacks(on_thought_cb, on_code_cb, on_finish_cb, on_geom_cb)

        if getattr(self.ai_manager, "client", None) is None:
            cbs.thought("❌ 未配置 AI API Key，无法启动教研调度。")
            cbs.finish(False, "未配置 API Key")
            return {"status": "failed", "error": "未配置 API Key"}

        self._announce_start(user_prompt)

        # ========== 阶段 1: 拆解教学大纲 ==========
        cbs.thought("🧠 教研组长正在分析问题，制定教学大纲...")
        self._emit_student_profile(cbs)

        plan = self._decompose_problem(user_prompt)
        topic = plan.get("topic", user_prompt)
        steps = plan.get("steps", [])

        if not steps:
            cbs.thought("⚠️ 教学大纲生成失败，回退到通用求解模式。")
            # 回退到基类的纯代码闭环
            return super().solve_problem(user_prompt, on_thought_cb, on_code_cb, on_finish_cb, on_geom_cb)

        self._emit_plan(topic, steps, cbs)

        # ========== 阶段 2: 调度子 Agent（支持串行/并行模式）==========
        parallel_steps, serial_steps = self._split_steps_by_mode(steps)
        all_codes, all_geom_commands = self._dispatch_steps(
            topic, parallel_steps, serial_steps, on_thought_cb, on_code_cb, on_geom_cb
        )

        # ========== 阶段 3: 汇总 + 教学质量评估 ==========
        return self._aggregate(topic, steps, all_codes, all_geom_commands, user_prompt, plan, cbs)

    # ------------------------------------------------------------------
    # 环节 1：开场（会话 ID + 广播 + 学生画像）
    # ------------------------------------------------------------------
    def _announce_start(self, user_prompt: str) -> None:
        """生成会话 ID 并通过消息总线广播教学任务开始。"""
        self._conversation_id = str(uuid.uuid4())[:8]

        if not self._message_bus:
            return

        from mathlab.core.agent_message import MessageType

        self.send_message(
            receiver_id="broadcast",
            msg_type=MessageType.NOTIFICATION,
            content=f"教学任务启动: {user_prompt[:50]}",
            conversation_id=self._conversation_id,
            topic="数学教学",
        )

    def _emit_student_profile(self, cbs: SolveCallbacks) -> None:
        """把学生认知画像推送到思考流（自适应教学）。"""
        if not (self.student_model and self._adaptive_engine):
            return

        profile = self.student_model.get_profile_summary()
        comfort, stretch = self.student_model.get_zpd_zone()
        cbs.thought(
            f"🎓 学生画像加载完成：\n"
            f"  ├─ 认知层级：{profile['cognitive_level']}\n"
            f"  ├─ 学习偏好：{profile['learning_style']}\n"
            f"  ├─ 平均掌握度：{profile['avg_mastery']}\n"
            f"  ├─ 参与度：{profile['engagement']}\n"
            f"  ├─ ZPD区间：{comfort.to_chinese()} → {stretch.to_chinese()}\n"
            f"  └─ 薄弱知识点：{', '.join(profile['weakness_areas']) or '无'}"
        )

    @staticmethod
    def _emit_plan(topic: str, steps: list, cbs: SolveCallbacks) -> None:
        """把拆解出来的教学大纲输出给用户。"""
        cbs.thought(f"📋 课题：{topic}")
        for s in steps:
            cbs.thought(f"  ├─ 步骤 {s['num']}: {s['title']}" f"（💡 {s.get('hint_for_teacher', '')}）")

    # ------------------------------------------------------------------
    # 环节 2：步骤分组与调度
    # ------------------------------------------------------------------
    def _split_steps_by_mode(self, steps: list) -> tuple:
        """按 parallelizable 标记把步骤分成并行组与串行组。

        未开启并行模式时，全部步骤走串行路径。
        """
        if not self.parallel_execution:
            return [], list(steps)

        parallel_steps = [s for s in steps if s.get("parallelizable", False)]
        serial_steps = [s for s in steps if not s.get("parallelizable", False)]
        return parallel_steps, serial_steps

    def _dispatch_steps(
        self,
        topic: str,
        parallel_steps: list,
        serial_steps: list,
        on_thought_cb=None,
        on_code_cb=None,
        on_geom_cb=None,
    ) -> tuple:
        """执行全部步骤，返回 ``(codes, geom_commands)``。"""
        all_codes: list = []
        all_geom_commands: list = []

        if parallel_steps:
            if on_thought_cb:
                on_thought_cb(f"🚀 启动并行执行模式：{len(parallel_steps)} 个独立步骤同时调度...")
            codes, geoms = self._run_parallel_steps(topic, parallel_steps, on_thought_cb, on_code_cb, on_geom_cb)
            all_codes.extend(codes)
            all_geom_commands.extend(geoms)

        for step in serial_steps:
            num, success, code, geom_cmds = self._run_step(topic, step, on_thought_cb, on_code_cb, on_geom_cb)
            all_geom_commands.extend(geom_cmds)
            if success and code:
                all_codes.append(code)
                if on_thought_cb:
                    on_thought_cb(f"  ✅ 第 {num} 步完成")
            elif on_thought_cb:
                on_thought_cb(f"  ⚠️ 第 {num} 步未能产出完整结果，继续下一步")

        return all_codes, all_geom_commands

    def _run_parallel_steps(
        self,
        topic: str,
        steps: list,
        on_thought_cb=None,
        on_code_cb=None,
        on_geom_cb=None,
    ) -> tuple:
        """用线程池并发执行互不依赖的步骤，返回 ``(codes, geom_commands)``。"""
        results = {}
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_step = {
                executor.submit(self._run_step, topic, step, on_thought_cb, on_code_cb, on_geom_cb): step
                for step in steps
            }
            for future in as_completed(future_to_step):
                try:
                    num, success, code, geom_cmds = future.result()
                    results[num] = (success, code, geom_cmds)
                    if on_thought_cb:
                        if success:
                            on_thought_cb(f"  ✅ 第 {num} 步完成 (并行)")
                        else:
                            on_thought_cb(f"  ⚠️ 第 {num} 步未能产出完整结果 (并行)")
                except Exception as e:
                    logger.error("并行步骤执行异常: %s", e, exc_info=True)
                    if on_thought_cb:
                        on_thought_cb(f"  ❌ 并行步骤异常: {e}")

        codes: list = []
        geoms: list = []
        # 按 step num 排序收集，保证输出顺序与大纲一致
        for num in sorted(results.keys()):
            success, code, geom_cmds = results[num]
            geoms.extend(geom_cmds)
            if success and code:
                codes.append(code)
        return codes, geoms

    # ------------------------------------------------------------------
    # 环节 3：单个步骤的执行
    # ------------------------------------------------------------------
    def _run_step(
        self,
        topic: str,
        step: dict,
        on_thought_cb=None,
        on_code_cb=None,
        on_geom_cb=None,
    ) -> tuple:
        """执行单个教学步骤，返回 ``(num, success, code, geom_commands)``。"""
        num = step.get("num", 0)
        title = step.get("title", "处理中...")
        hint = step.get("hint_for_teacher", "")
        cognitive_level = step.get("cognitive_level", "理解")

        sub_prompt = self._build_step_prompt(topic, num, title, hint, cognitive_level)
        agent_key = self._pick_sub_agent(title, hint)
        sub_info = self._lookup_sub_agent(agent_key)

        if on_thought_cb:
            on_thought_cb(f"\n{'─' * 20}\n📖 第 {num} 步：{title}")
            on_thought_cb(f"  🎯 调度：{agent_key}")
            if hint:
                on_thought_cb(f"  💡 提示：{hint}")

        self._notify_step_dispatch(num, agent_key, title, cognitive_level, topic)

        # 子 Agent 未注册时由教研组长自己顶上
        if sub_info is None:
            if on_thought_cb:
                on_thought_cb(f"  ⚠️ 子 Agent「{agent_key}」未注册，正在自行执行...")
            return self._run_step_by_self(sub_prompt, num, on_thought_cb, on_code_cb, on_geom_cb)

        return self._run_step_by_agent(
            sub_info["instance"],
            sub_prompt,
            num,
            agent_key,
            title,
            on_thought_cb,
            on_code_cb,
            on_geom_cb,
        )

    def _build_step_prompt(self, topic: str, num, title: str, hint: str, cognitive_level: str) -> str:
        """拼装子步骤的提示词，并注入 Bloom 层级行为约束。"""
        sub_prompt = f"在教学主题「{topic}」的框架下，完成第 {num} 步：{title}。\n教学提示：{hint}"
        if self._pedagogical_builder:
            step_constraint = self._pedagogical_builder.build_step_execution_constraint(
                step_title=title,
                cognitive_level=cognitive_level,
                hint=hint,
            )
            sub_prompt += f"\n\n{step_constraint}"
        return sub_prompt

    def _lookup_sub_agent(self, agent_key: str):
        """在注册表里查子 Agent 信息，未注册或无注册表时返回 None。"""
        registry = getattr(self, "agent_registry", None)
        if not registry or not registry.agents:
            return None
        return registry.agents.get(agent_key)

    def _notify_step_dispatch(self, num, agent_key: str, title: str, cognitive_level: str, topic: str) -> None:
        """在消息总线上广播本步骤的派发意图（仅用于可观测性）。

        [P1 修复] 这里原先发的是 TASK_REQUEST：MessageRouter 收到后会**同步**调用
        目标 Agent 的 solve_problem，而下面又直接调了一次 —— 每个子任务被执行两遍
        （双份 token 花费、代码与几何命令重复回传）。总线路径产出的 TASK_RESULT
        全仓没有任何订阅者，所以真正的执行路径是直调；总线上行降级为 NOTIFICATION。
        """
        if not self._message_bus:
            return

        from mathlab.core.agent_message import MessageType

        self.send_message(
            receiver_id=agent_key,
            msg_type=MessageType.NOTIFICATION,
            content=f"[Step {num}] 计划派发: {title} -> {agent_key}",
            step_num=num,
            cognitive_level=cognitive_level,
            topic=topic,
            conversation_id=self._conversation_id,
        )

    def _run_step_by_self(self, sub_prompt: str, num, on_thought_cb=None, on_code_cb=None, on_geom_cb=None) -> tuple:
        """子 Agent 缺失时，教研组长自己执行该步骤（走基类的代码闭环）。"""

        def _noop_finish_cb(success, content):
            pass

        result = super(PlannerAgent, self).solve_problem(
            sub_prompt,
            on_thought_cb=on_thought_cb,
            on_code_cb=on_code_cb,
            on_finish_cb=_noop_finish_cb,
            on_geom_cb=on_geom_cb,
        )
        if isinstance(result, dict) and result.get("status") == "ok":
            return (num, True, result.get("code", ""), result.get("geom_commands", []))
        return (num, False, "", [])

    def _run_step_by_agent(
        self,
        sub_agent,
        sub_prompt: str,
        num,
        agent_key: str,
        title: str,
        on_thought_cb=None,
        on_code_cb=None,
        on_geom_cb=None,
    ) -> tuple:
        """委派给已注册的子 Agent 执行，并汇总其回调输出。"""
        collector = StepResultCollector(num, on_thought_cb, on_code_cb, on_geom_cb)

        try:
            sub_result = sub_agent.solve_problem(
                sub_prompt,
                on_thought_cb=collector.make_thought_cb(),
                on_code_cb=collector.make_code_cb(),
                on_finish_cb=collector.make_finish_cb(),
                on_geom_cb=collector.make_geom_cb(),
            )
            if isinstance(sub_result, dict) and sub_result.get("status") == "ok":
                collector.success = True
                collector.code = sub_result.get("code", "")
                collector.geom.extend(sub_result.get("geom_commands", []))
        except Exception as e:
            logger.error("子 Agent「%s」执行异常: %s", agent_key, e, exc_info=True)
            if on_thought_cb:
                on_thought_cb(f"  ❌ 子 Agent「{agent_key}」执行异常: {e}")

        self._notify_step_progress(num, title, collector.success)
        return collector.as_tuple()

    def _notify_step_progress(self, num, title: str, success: bool) -> None:
        """广播本步骤的完成进度。"""
        if not self._message_bus:
            return

        from mathlab.core.agent_message import MessageType

        self.send_message(
            receiver_id="broadcast",
            msg_type=MessageType.TASK_PROGRESS,
            content=f"步骤 {num} 完成: {title} ({'成功' if success else '失败'})",
            step_num=num,
            success=success,
            conversation_id=self._conversation_id,
        )

    # ------------------------------------------------------------------
    # 环节 4：汇总与质量评估
    # ------------------------------------------------------------------
    def _aggregate(
        self,
        topic: str,
        steps: list,
        all_codes: list,
        all_geom_commands: list,
        user_prompt: str,
        plan: dict,
        cbs: SolveCallbacks,
    ) -> dict:
        """拼接最终代码、跑教学质量评估，返回统一结果字典。"""
        final_code = "\n\n# ---- Planner 聚合代码 ----\n" + "\n\n".join(all_codes)
        cbs.thought(f"\n{'─' * 20}\n🏁 教研组已完成所有教学步骤！")

        result = {
            "status": "ok",
            "code": final_code,
            "topic": topic,
            "steps_executed": len(steps),
            "geom_commands": all_geom_commands,
        }

        if self._quality_evaluator:
            quality_report = self._run_quality_evaluation(final_code, user_prompt, plan, cbs)
            if quality_report:
                result["quality_report"] = quality_report

        cbs.finish(True, final_code)
        return result

    # ------------------------------------------------------------------
    # 拆解与路由
    # ------------------------------------------------------------------
    def _decompose_problem(self, user_prompt: str) -> dict:
        """调用 LLM 将用户问题拆解为教学大纲。

        Returns:
            ``{"topic": "...", "steps": [{"num": 1, "title": "...",
            "hint_for_teacher": "...", "parallelizable": false}]}``

            ``parallelizable=true`` 表示该步骤可与其他可并行步骤同时执行。
            调用失败时返回一个三段式兜底大纲。
        """
        adaptive_strategy = ""
        if self._adaptive_engine:
            adaptive_strategy = self._adaptive_engine.build_adaptive_prompt(user_prompt)

        pedagogical_constraint = ""
        if self._pedagogical_builder:
            pedagogical_constraint = self._pedagogical_builder.build_decomposition_constraint()

        decompose_prompt = f"""请将以下数学问题拆解为 3-5 个由浅入深、循序渐进的教学步骤。

用户问题：{user_prompt}
{adaptive_strategy}
{pedagogical_constraint}

你必须严格按照以下 JSON 格式返回，不要包含任何其他文本：
{{
    "topic": "本次课题的主题",
    "steps": [
        {{"num": 1, "title": "第一步标题", "hint_for_teacher": "给授课老师的提示", "cognitive_level": "记忆/理解/应用/分析/评价/创造", "parallelizable": false}},
        {{"num": 2, "title": "第二步标题", "hint_for_teacher": "给授课老师的提示", "cognitive_level": "记忆/理解/应用/分析/评价/创造", "parallelizable": false}}
    ]
}}

要求：
1. 步骤从易到难，逐步引导，每个步骤标注 Bloom 认知层级
2. 每个步骤聚焦一个核心探索点
3. 不要一次性给最终答案
4. 如果涉及画图，优先在前几步让几何专家画图
5. parallelizable 设为 true 仅当该步骤不依赖任何前序步骤的输出结果（如独立画图、独立计算）
6. 根据学生认知画像调整步骤难度梯度，确保在最近发展区内
7. 认知层级必须大致递增（如：记忆→理解→应用→分析），不要跳级超过2层
8. 每个步骤只引入一个新概念，后续步骤建立在前序成果之上"""
        try:
            response = self.ai_manager.client.chat.completions.create(
                model=self._get_effective_model(),
                messages=[{"role": "user", "content": decompose_prompt}],
                temperature=0.3,
                timeout=30,
                response_format={"type": "json_object"},
            )
            return json.loads(response.choices[0].message.content)
        except Exception:
            logger.warning("教学大纲拆解失败，使用兜底大纲", exc_info=True)
            return {"topic": user_prompt, "steps": [dict(s) for s in _FALLBACK_PLAN_STEPS]}

    def _pick_sub_agent(self, step_title: str, hint: str) -> str:
        """根据步骤标题和提示文本，推断应该派发给哪个子 Agent。

        Returns:
            AgentRegistry 中注册的名字（如 'GeometryAgent' 或 'DataVizAgent'）。
        """
        registry = getattr(self, "agent_registry", None)
        if not registry or not registry.agents:
            return "GeometryAgent"

        # 优先查找 DataViz 相关专家：关键词命中才走可视化
        viz_hit = self._match_agent(registry, _VIZ_AGENT_HINTS)
        if viz_hit and any(kw in f"{step_title} {hint}".lower() for kw in _VIZ_KEYWORDS):
            return viz_hit

        # 默认查找几何专家
        geometry_hit = self._match_agent(registry, _GEOMETRY_AGENT_HINTS)
        if geometry_hit:
            return geometry_hit

        # 回退到第一个非自身的注册 Agent
        for name in registry.agents:
            if name != "PlannerAgent":
                return name

        return next(iter(registry.agents))

    @staticmethod
    def _match_agent(registry, hints) -> str:
        """在注册表里按描述关键词匹配 Agent 名字，未命中返回空串。"""
        for name, info in registry.agents.items():
            desc = info.get("description", "").lower()
            if any(kw in desc for kw in hints):
                return name
        return ""

    def _run_quality_evaluation(
        self,
        content: str,
        user_prompt: str,
        plan: dict,
        cbs: SolveCallbacks = None,
    ) -> dict:
        """执行教学质量评估并生成报告。

        评估三维度：内容理解、上下文连贯性、教学设计。

        Args:
            content: 待评估的聚合代码。
            user_prompt: 原始用户问题。
            plan: 拆解出的教学大纲。
            cbs: 回调集合（可选），用于把评估结果推送到思考流。

        Returns:
            序列化后的报告字典；评估失败返回 None。
        """
        try:
            from mathlab.core.pedagogical_engine import QualityDimension

            reports = self._quality_evaluator.evaluate(
                content=content,
                user_prompt=user_prompt,
                plan=plan,
            )
            overall = self._quality_evaluator.get_overall_score(reports)

            if cbs:
                dim_names = {
                    QualityDimension.CONTENT_UNDERSTANDING: "内容理解",
                    QualityDimension.CONTEXT_COHERENCE: "连贯性",
                    QualityDimension.PEDAGOGICAL_DESIGN: "教学设计",
                }
                cbs.thought(f"\n📊 教学质量评估完成（总分: {overall:.0%}）:")
                for dim, report in reports.items():
                    icon = "✅" if report.passed else "❌"
                    name = dim_names.get(dim, dim.value)
                    extra = f" — {report.issues[0]}" if report.issues else ""
                    cbs.thought(f"  {icon} {name}: {report.score:.0%}{extra}")

            return {
                "overall_score": overall,
                "dimensions": {dim.value: report.to_dict() for dim, report in reports.items()},
            }
        except Exception as e:
            logger.error("教学质量评估失败: %s", e, exc_info=True)
            return None
