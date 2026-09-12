"""AI 多智能体集成与异步 Worker 管理 Mixin。

将 MainWindow 中与 AI Agent 系统、ECharts 集成、
以及后台 AI Worker (拟合/聚类/识别/生成) 相关的方法提取到此模块。
"""

from PySide6.QtCore import QThreadPool

from mathlab.core.ai_facade import AIFacade, AITaskType
from mathlab.core.async_workers import (
    AIClusterWorker,
    AIFitWorker,
    AIGeneratePointsWorker,
    AIRecognizeWorker,
    TaskManager,
)
from mathlab.core.prompt_manager import prompt_manager
from mathlab.utils.logger import get_logger

logger = get_logger(__name__)


class AIMixin:
    """MainWindow Mixin：AI 多智能体集成与异步 Worker 管理。"""

    # 🌟 2. 处理来自 Jupyter 的指令 🌟
    def _setup_ai_integration(self):
        import os

        from mathlab.core.agent_bridge import AgentUIBridge
        from mathlab.core.agent_registry import AgentRegistry
        from mathlab.core.ai_manager import (
            DataVizAgent,
            GeometryAgent,
            PlannerAgent,
            ResourceConfig,
        )
        from mathlab.core.student_model import StudentModelManager

        # 0. 初始化学生认知模型管理器（自适应学习核心）
        self.student_model_manager = StudentModelManager()
        self.student_model = self.student_model_manager.get_model("default")

        # 1. 初始化联邦路由大脑，注入学生模型
        self.agent_registry = AgentRegistry(self.ai_manager, student_model=self.student_model)

        # 2. 注册所有领域专家（支持模型多样性和资源限制）
        # 教研组长：启用并行执行，使用默认模型，注入学生模型实现自适应教学
        self.agent_registry.register_agent(
            name="PlannerAgent",
            description="数学教研组长：将复杂问题拆解为3-5个循序渐进的教学步骤，然后调度解析几何专家和数据可视化专家协同完成教学。适合深层理解、苏格拉底式教学场景。",
            agent_instance=PlannerAgent(
                self.ai_manager,
                agent_registry=self.agent_registry,
                model_override=self._get_agent_model_override("PlannerAgent"),
                parallel_execution=True,
                max_workers=3,
                student_model=self.student_model,
            ),
        )

        # 几何专家：可指定专用模型，注入学生模型
        self.agent_registry.register_agent(
            name="GeometryAgent",
            description="擅长解决平面几何、微积分、代数方程求解，以及二维坐标系中的点线圆绘制任务。",
            agent_instance=GeometryAgent(
                self.ai_manager,
                model_override=self._get_agent_model_override("GeometryAgent"),
                student_model=self.student_model,
            ),
        )

        # 数据可视化专家：可指定专用模型，注入学生模型
        self.agent_registry.register_agent(
            name="DataVizAgent",
            description="擅长处理统计数据可视化、柱状图、折线图、南丁格尔玫瑰图、3D曲面图等 ECharts 图表渲染任务。",
            agent_instance=DataVizAgent(
                self.ai_manager,
                model_override=self._get_agent_model_override("DataVizAgent"),
                student_model=self.student_model,
            ),
        )

        # 3. 从配置目录热加载自定义专家 Agent
        agents_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data",
            "agents",
        )
        if os.path.isdir(agents_dir):
            loaded, failed = self.agent_registry.load_agents_from_directory(agents_dir)
            if loaded:
                logger.info(f"已热加载 {len(loaded)} 个自定义专家: {loaded}")

        # 3. UI 桥梁现在不再绑定单一 Agent，而是绑定整个 Registry 路由器
        self.agent_bridge = AgentUIBridge(self.agent_registry, self)

        # 4. 创建统一 AI 范式门面（自动路由 Function Calling / Agent 代码生成）
        self.ai_facade = AIFacade(
            self.ai_manager,
            self.agent_registry,
            student_model=self.student_model,
        )

        # 5. 信号与槽的严密绑定 (跨线程安全)
        # 思考 -> 打印到终端
        self.agent_bridge.thought_emitted.connect(self.console.append_agent_thought)

        # 观察 -> 打印到终端
        self.agent_bridge.observation_emitted.connect(self.console.append_agent_observation)

        # 代码 -> 注入 Monaco 编辑器
        self.agent_bridge.code_generated.connect(self._stream_code_to_editor)

        # 结束 -> 善后处理
        self.agent_bridge.task_finished.connect(self._on_agent_task_finished)

        # 几何绘图命令 -> 实时渲染到画板
        self.agent_bridge.geom_commands_emitted.connect(self._on_geom_commands_received)

        # 6. 绑定全局输入框 (OmniBar) 的回车事件
        self.omni_bar.search_submitted.connect(self._trigger_global_ai_task)

    def _get_agent_model_override(self, agent_name):
        """从 settings.json 读取 Agent 专用模型配置，实现模型多样性。

        配置格式示例 (settings.json):
        {
            "agent_models": {
                "PlannerAgent": "deepseek-reasoner",
                "GeometryAgent": "gpt-4o",
                "DataVizAgent": "deepseek-chat"
            }
        }
        """
        import json
        import os

        try:
            package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            settings_path = os.path.join(package_dir, "settings.json")
            with open(settings_path, "r", encoding="utf-8") as f:
                settings = json.load(f)
            agent_models = settings.get("agent_models", {})
            return agent_models.get(agent_name)
        except Exception:
            return None

    def _setup_echarts_integration(self):
        # 绑定刚刚解析出的信号
        self.ai_tools_panel.code_editor.backend.echarts_data_ready.connect(self._show_echarts_panel)

    def _show_echarts_panel(self, chart_options_dict):
        """唤醒 ECharts 插件面板并渲染"""
        import json

        if not hasattr(self, "plugin_manager"):
            self.console.append_agent_observation("⚠️ 未找到插件管理器！", is_error=True)
            return
        echarts_plugin = self.plugin_manager.active_plugins.get("ECharts Data Viewer")
        if not echarts_plugin:
            self.console.append_agent_observation("⚠️ 未找到 ECharts 插件实例！", is_error=True)
            return

        web_view = getattr(echarts_plugin, "web_view", None)
        if not web_view:
            return

        json_payload = json.dumps(chart_options_dict, ensure_ascii=False)
        js_command = f"if(window.updateChartOptions) {{ window.updateChartOptions({json_payload}); }} else if(window.renderChart) {{ window.renderChart('{json_payload}'); }}"
        web_view.page().runJavaScript(js_command)

        self.console.append_agent_observation("✨ 3D/2D 交互图表已在 ECharts 面板渲染就绪！", is_error=False)

    def _trigger_global_ai_task(self, user_prompt):
        """当用户在顶部搜索框按下回车时触发"""
        if hasattr(self.omni_bar, "input_field"):
            self.omni_bar.input_field.clear()

        if hasattr(self.console, "output_area"):
            self.console.output_area.append(f"<hr><b style='color:#64B5F6'>👤 用户:</b> {user_prompt}<br>")

        # 唤醒 AI 专属光标，飞入视野
        from PySide6.QtCore import QPointF

        if hasattr(self, "ai_cursor"):
            self.ai_cursor.move_to(QPointF(self.width() / 2, self.height() / 2), 600)

        # 启动后台推演
        self.agent_bridge.run_task_in_background(user_prompt)

    def _stream_code_to_editor(self, code):
        """接收到 AI 代码，安全写入前端 Monaco"""
        import json

        escaped_code = json.dumps(code)
        self.ai_tools_panel.code_editor.web_view.page().runJavaScript(f"window.editor.setValue({escaped_code});")

        # 光标小幅抖动，模拟正在打字
        if hasattr(self, "ai_cursor"):
            import random

            from PySide6.QtCore import QPointF

            curr_pos = self.ai_cursor.cursorPos
            shake_pos = QPointF(
                curr_pos.x() + random.randint(-5, 5),
                curr_pos.y() + random.randint(-5, 5),
            )
            self.ai_cursor.move_to(shake_pos, 100)

    def _on_agent_task_finished(self, success, final_content):
        """Agent 彻底跑完任务 (包含自愈和 RAG 沉淀) 后的 UI 善后"""
        if success:
            self.console.append_agent_observation("🎉 任务完美执行并渲染！", is_error=False)
            # 触发底层执行，刷新所有的画布和 C# 引擎联动
            self.ai_tools_panel.code_editor.backend.execute_code(final_content)
        else:
            self.console.append_agent_observation("⚠️ 尝试多次失败，请手动干预。", is_error=True)

        # 持久化保存学生认知画像（自适应学习）
        if hasattr(self, "student_model_manager"):
            self.student_model_manager.save_model("default")

        # AI 光标隐退
        if hasattr(self, "ai_cursor"):
            self.ai_cursor.setVisible(False)

    def execute_ai_action(self, action_data: dict) -> None:
        action = action_data.get("action")
        engine = self.geometry_engine if hasattr(self, "geometry_engine") else None

        # ── 坐标级变体：自动从坐标创建点后再连线/画圆 ──
        if action == "add_segment_auto":
            x1, y1 = action_data.get("x1", 0), action_data.get("y1", 0)
            x2, y2 = action_data.get("x2", 0), action_data.get("y2", 0)
            if engine:
                p1 = engine.add_point(x=x1, y=y1)
                p2 = engine.add_point(x=x2, y=y2)
                engine.add_segment(p1, p2)
            return

        if action == "add_circle_auto":
            cx, cy = action_data.get("cx", 0), action_data.get("cy", 0)
            r = action_data.get("r", 1.0)
            if engine:
                center = engine.add_point(x=cx, y=cy)
                engine.add_circle(center, r)
            return

        if action == "add_line_auto":
            # 无限直线退化为很长的线段
            x1, y1 = action_data.get("x1", 0), action_data.get("y1", 0)
            x2, y2 = action_data.get("x2", 0), action_data.get("y2", 0)
            # 向两端各延伸 10 倍
            dx, dy = x2 - x1, y2 - y1
            if engine:
                p1 = engine.add_point(x=x1 - dx * 10, y=y1 - dy * 10)
                p2 = engine.add_point(x=x2 + dx * 10, y=y2 + dy * 10)
                engine.add_segment(p1, p2)
            return

        if action == "add_ellipse_auto":
            # 几何引擎暂不支持椭圆，退化为圆（取平均半轴）
            cx, cy = action_data.get("cx", 0), action_data.get("cy", 0)
            rx = abs(action_data.get("rx", 1))
            ry = abs(action_data.get("ry", 1))
            r_avg = (rx + ry) / 2.0
            if engine:
                center = engine.add_point(x=cx, y=cy)
                engine.add_circle(center, r_avg)
            return

        if action == "add_polygon_auto":
            coords = action_data.get("coords", [])
            if len(coords) >= 3 and engine:
                ids = [engine.add_point(x=float(p[0]), y=float(p[1])) for p in coords]
                engine.add_polygon(ids)
            return

        # ── 原有引用级动作 ──
        if action == "add_point":
            x = action_data.get("x", 0.0)
            y = action_data.get("y", 0.0)
            z = action_data.get("z", 0.0)
            name = action_data.get("name", "")
            if engine:
                engine.add_point(x=x, y=y, z=z, name=name)
            else:
                self.on_point_added(x, y)

        elif action == "add_segment":
            point1_id = action_data.get("point1_id")
            point2_id = action_data.get("point2_id")
            if point1_id and point2_id and engine:
                engine.add_segment(point1_id, point2_id)

        elif action == "add_circle":
            center_id = action_data.get("center_id")
            radius = action_data.get("radius", 1.0)
            if center_id and engine:
                engine.add_circle(center_id, radius)

        elif action == "add_sphere":
            center_id = action_data.get("center_id")
            radius = action_data.get("radius", 1.0)
            if center_id and engine:
                engine.add_sphere(center_id=center_id, radius=radius)

        elif action == "add_polygon":
            point_ids = action_data.get("point_ids", [])
            if len(point_ids) >= 3 and engine:
                engine.add_polygon(point_ids)

        elif action == "update_point":
            point_id = action_data.get("point_id")
            x = action_data.get("x")
            y = action_data.get("y")
            z = action_data.get("z")
            if point_id and (x is not None or y is not None or z is not None) and engine:
                kwargs = {}
                if x is not None:
                    kwargs["x"] = x
                if y is not None:
                    kwargs["y"] = y
                if z is not None:
                    kwargs["z"] = z
                engine.update_point(point_id, **kwargs)

        elif action == "remove_object":
            obj_id = action_data.get("obj_id")
            if obj_id:
                self.on_object_deleted(obj_id)

        elif action == "clear":
            self.on_console_command("%clear")

        elif action == "solve":
            expression = action_data.get("expression", "")
            if expression and hasattr(self, "cas_provider"):

                def on_success(result):
                    if result.get("success"):
                        self.console.display_result(
                            {
                                "success": True,
                                "output": str(result.get("result", "")),
                                "error": "",
                                "more": False,
                            }
                        )

                def on_error(err_msg):
                    self.console.display_system_message(f"求解失败: {err_msg}", level="error")

                TaskManager().submit(
                    fn=self.cas_provider.solve_equation,
                    on_success=on_success,
                    on_error=on_error,
                    equation_str=expression,
                    variable="x",
                )

    def _on_geom_commands_received(self, commands):  # noqa: E303
        """接收沙箱中累积的几何绘图命令，逐个执行到画板。"""
        for cmd in commands:
            try:
                self.execute_ai_action(cmd)
            except Exception as e:
                logger.warning(f"执行几何绘图命令失败: {cmd} - {e}")

    def _recycle_worker(self, worker) -> None:
        """回收已结束的 Worker 引用。

        AIXxxWorker 均为 QRunnable（非 QObject），没有 deleteLater()，
        由 QThreadPool 在 run() 结束后依据 setAutoDelete(True) 自动释放。
        这里只需要清理 Python 侧的活动集合与槽位引用，避免悬垂引用。
        """
        self.active_workers.discard(worker)
        for attr in ("fit_worker", "cluster_worker", "recognize_worker", "generate_points_worker"):
            if getattr(self, attr, None) is worker:
                setattr(self, attr, None)

    def on_ai_fit_requested(self, points: list, model_type: str, params: dict = None) -> None:
        if not points:
            return

        # QRunnable 没有 isRunning()，以是否仍在活动集合中判断运行状态
        if self.fit_worker is not None and self.fit_worker in self.active_workers:
            return

        if params is None:
            params = {}

        self.ai_tools_panel.set_loading_state(True)
        self.statusBar().showMessage(f"正在训练 {model_type} 模型，请稍候...")

        self.fit_worker = AIFitWorker(self.ai_manager, points, model_type, **params)
        self.active_workers.add(self.fit_worker)
        self.fit_worker.signals.finished.connect(lambda res, w=self.fit_worker: self.on_ai_worker_finished(res, w))
        self.fit_worker.signals.error.connect(lambda msg, w=self.fit_worker: self.on_ai_worker_error(msg, w))
        QThreadPool.globalInstance().start(self.fit_worker)

    def on_ai_worker_finished(self, result: dict, worker):
        # 在回收 worker 之前完成所有 worker 类型判断，避免竞态
        if isinstance(worker, AIFitWorker):
            self.statusBar().showMessage("模型训练完成", 3000)
            self.ai_tools_panel.set_fit_result(result)
        elif isinstance(worker, AIClusterWorker):
            self.statusBar().showMessage("聚类分析完成", 3000)
            self.ai_tools_panel.set_cluster_result(result)
        elif isinstance(worker, AIRecognizeWorker):
            self.statusBar().showMessage("识别完成", 3000)
            self.ai_tools_panel.set_recognition_result(result)

        self._recycle_worker(worker)

    def on_ai_cluster_requested(self, points: list, method: str, params: dict) -> None:
        if not points:
            return

        if self.cluster_worker is not None and self.cluster_worker in self.active_workers:
            return

        self.ai_tools_panel.set_loading_state(True)
        self.statusBar().showMessage(f"正在进行 {method} 聚类分析...")

        self.cluster_worker = AIClusterWorker(self.ai_manager, points, method, params)
        self.active_workers.add(self.cluster_worker)
        self.cluster_worker.signals.finished.connect(
            lambda res, w=self.cluster_worker: self.on_ai_worker_finished(res, w)
        )
        self.cluster_worker.signals.error.connect(lambda msg, w=self.cluster_worker: self.on_ai_worker_error(msg, w))
        QThreadPool.globalInstance().start(self.cluster_worker)

    def on_ai_recognize_requested(self, image_data: list) -> None:
        if self.recognize_worker is not None and self.recognize_worker in self.active_workers:
            return

        self.ai_tools_panel.set_loading_state(True)
        self.statusBar().showMessage("正在识别数字...")

        self.recognize_worker = AIRecognizeWorker(self.ai_manager, image_data)
        self.active_workers.add(self.recognize_worker)
        self.recognize_worker.signals.finished.connect(
            lambda res, w=self.recognize_worker: self.on_ai_worker_finished(res, w)
        )
        self.recognize_worker.signals.error.connect(lambda msg, w=self.recognize_worker: self.on_ai_worker_error(msg, w))
        QThreadPool.globalInstance().start(self.recognize_worker)

    def on_ai_worker_error(self, error_msg: str, worker=None):
        if worker is not None:
            self._recycle_worker(worker)

        self.ai_tools_panel.set_loading_state(False)
        self.statusBar().showMessage(f"后台运算出错: {error_msg}", 5000)

    def on_ai_generate_points(self, n: int) -> None:
        if self.generate_points_worker is not None and self.generate_points_worker in self.active_workers:
            return

        self.ai_tools_panel.set_loading_state(True)
        self.statusBar().showMessage("正在生成随机点...")

        self.generate_points_worker = AIGeneratePointsWorker(
            self.ai_manager, n, x_range=(-200, 200), y_range=(-200, 200)
        )
        self.active_workers.add(self.generate_points_worker)
        self.generate_points_worker.signals.finished.connect(
            lambda res, w=self.generate_points_worker: self.on_generate_points_worker_finished(res, w)
        )
        self.generate_points_worker.signals.error.connect(
            lambda msg, w=self.generate_points_worker: self.on_ai_worker_error(msg, w)
        )
        QThreadPool.globalInstance().start(self.generate_points_worker)

    def on_generate_points_worker_finished(self, result: dict, worker):
        self._recycle_worker(worker)

        self.ai_tools_panel.set_loading_state(False)
        self.statusBar().showMessage("随机点生成完成", 3000)

        if result["success"]:
            self.ai_tools_panel.set_scatter_points(result["points"])
            for x, y in result["points"]:
                self.on_point_added(x, y)

    def handle_ai_explain(self, full_code, selected_code):
        if hasattr(self, "ai_dock"):
            self.ai_dock.setVisible(True)
            self.ai_dock.raise_()

        user_prompt = prompt_manager.build("code_explainer", full_code=full_code, selected_code=selected_code)

        if hasattr(self, "ai_panel"):
            self.ai_panel.chat_input.setText(user_prompt)
            self.ai_panel.on_send_message()
