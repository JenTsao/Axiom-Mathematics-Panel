"""信号连接与几何事件处理 Mixin。

将 MainWindow 中与 Qt 信号连接、几何引擎事件分发、
对象增删改查、控制台命令处理等相关的方法提取到此模块。
"""

import uuid

from PySide6.QtWidgets import QMessageBox

from mathlab.core.async_workers import TaskManager
from mathlab.utils.i18n_manager import t
from mathlab.utils.logger import get_logger

logger = get_logger(__name__)


class SignalsMixin:
    """MainWindow Mixin：信号连接与事件处理。"""

    def connect_signals(self):
        self.central_widget.point_added.connect(self.on_point_added)
        self.central_widget.segment_added_coords.connect(self.on_segment_added)
        self.central_widget.circle_added_coords.connect(self.on_circle_added)
        self.central_widget.polygon_added_coords.connect(self.on_polygon_added)

        # 连接 geometry_engine 的监听器
        if hasattr(self, "geometry_engine"):
            self.geometry_engine.add_listener(self.on_geometry_event)

        self.algebra_panel.object_selected.connect(self.on_algebra_item_selected)
        self.algebra_panel.object_deleted.connect(self.on_object_deleted)
        self.algebra_panel.object_renamed.connect(self.on_object_renamed)
        self.algebra_panel.equation_changed.connect(self.on_equation_changed)

        # 连接属性面板信号
        if hasattr(self, "properties_panel"):
            self.properties_panel.object_renamed.connect(self.on_object_renamed)
            self.properties_panel.color_changed.connect(self.on_object_color_changed)
            self.properties_panel.opacity_changed.connect(self.on_object_opacity_changed)
            self.properties_panel.stroke_changed.connect(self.on_object_stroke_changed)
            self.properties_panel.label_toggled.connect(self.on_object_label_toggled)

        self.central_widget.object_selected.connect(self.on_algebra_item_selected)
        self.console.execute_command.connect(self.on_console_command)
        self.command_bar.command_entered.connect(self.on_command_entered)

        self.ai_tools_panel.action_requested.connect(self.execute_ai_action)
        self.ai_tools_panel.fit_requested.connect(self.on_ai_fit_requested)
        self.ai_tools_panel.cluster_requested.connect(self.on_ai_cluster_requested)
        self.ai_tools_panel.recognize_requested.connect(self.on_ai_recognize_requested)
        self.ai_tools_panel.generate_points.connect(self.on_ai_generate_points)

        # 连接函数探索器信号
        self.function_explorer.function_added.connect(self.on_function_added)
        self.function_explorer.function_updated.connect(self.on_function_updated)
        self.function_explorer.render_integral_area.connect(self.on_render_integral_area)
        self.function_explorer.render_tangent_line.connect(self.on_render_tangent_line)

    def on_code_completion_requested(self, code_text: str, line: int, column: int):
        if hasattr(self, "python_repl"):
            completions = self.python_repl.get_completions(code_text, line, column)
            self.ai_tools_panel.code_editor.set_completions(completions)

    # 🌟 2. 处理来自 Jupyter 的指令 🌟
    def handle_kernel_command(self, msg: dict):
        cmd = msg.get("cmd")

        # 获取底层几何引擎
        engine = self.geometry_engine

        try:
            if cmd == "draw_point":
                # 调用核心几何引擎
                engine.add_point(msg["x"], msg["y"], name=msg.get("name"))

            elif cmd == "draw_line":
                p1_id = None
                p2_id = None
                for obj_id, entity in engine.objects.items():
                    if entity.name == msg.get("p1"):
                        p1_id = obj_id
                    if entity.name == msg.get("p2"):
                        p2_id = obj_id

                if p1_id and p2_id:
                    engine.add_segment(p1_id, p2_id, name=msg.get("name"))

            elif cmd == "clear":
                engine.clear()

        except Exception as e:
            logger.error(f"执行几何指令失败: {e}")

    def _add_object(self, obj_data: dict) -> None:
        obj_id = obj_data["id"]
        self._objects_data[obj_id] = obj_data
        self.algebra_panel.add_object(obj_data)
        self.central_widget.draw_object(obj_id, obj_data)

    def on_geometry_event(self, event_type: str, data):
        """处理来自 geometry_engine 的事件"""
        if event_type == "object_added":
            self._add_object(data)
        elif event_type == "object_updated":
            obj_id = data.get("id")
            if obj_id:
                self._objects_data[obj_id] = data
                self.algebra_panel.update_object(data)
                self.central_widget.update_object(obj_id, data)
        elif event_type == "object_removed":
            obj_id = data
            if obj_id in self._objects_data:
                del self._objects_data[obj_id]
                self.algebra_panel.remove_object(obj_id)
                self.central_widget.remove_object(obj_id)
        elif event_type == "canvas_cleared":
            self._objects_data.clear()
            self.algebra_panel.clear()
            self.central_widget.clear_canvas()

    def on_function_added(self, func_data: dict):
        """处理函数探索器添加的函数"""
        try:
            plot_type = func_data.get("plot_type", "FunctionPlot")
            expression = func_data.get("expression", "")

            if not expression:
                return

            # 根据类型调用不同的绘图方法
            if plot_type == "FunctionPlot":
                obj_id = self.geometry_engine.add_function_plot(
                    expression=expression,
                    x_range=func_data.get("x_range", (-10, 10)),
                    num_points=500,
                )
            elif plot_type == "ImplicitPlot":
                obj_id = self.geometry_engine.add_implicit_plot(
                    expression=expression,
                    x_range=func_data.get("x_range", (-10, 10)),
                    y_range=func_data.get("y_range", (-10, 10)),
                )
            elif plot_type == "PolarPlot":
                import math

                obj_id = self.geometry_engine.add_polar_plot(
                    expression=expression, theta_range=(0, 2 * math.pi), num_points=500
                )
            else:
                return

            # 保存当前函数ID，用于后续更新
            self.current_function_id = obj_id
            # [P0修复 Bug4] 同步给 function_explorer 面板具体的 obj_id
            self.function_explorer.current_function_id = obj_id

            # 保存原始表达式和参数信息到对象中
            obj = self.geometry_engine.get_object(obj_id)
            if obj:
                obj.original_expression = expression
                obj.parameters = func_data.get("parameters", {})
        except Exception as e:
            QMessageBox.warning(self, t("dialogs.error"), f"{t('errors.invalid_expression')}: {str(e)}")

    # [P0修复 Bug4] 接收 obj_id 并精确更新，而非依赖共享的 current_function_id
    def on_function_updated(self, obj_id: str, func_data: dict):
        """处理函数探索器更新的函数（参数变化）"""
        try:
            plot_type = func_data.get("plot_type", "FunctionPlot")
            expression = func_data.get("expression", "")
            original_expr = func_data.get("original_expression", expression)

            if not expression or not obj_id:
                return

            # 使用传入的 obj_id 定位对象
            last_func = self.geometry_engine.get_object(obj_id)
            if not last_func:
                logger.warning("函数已被删除")
                return

            if hasattr(last_func, "_generate_points"):
                last_func.expression = expression
                last_func._generate_points()

                # 通知更新
                self.on_geometry_event("object_updated", last_func.serialize())
        except Exception as e:
            logger.warning("更新函数时出错: %s", e)

    def on_render_integral_area(self, expr: str, a: float, b: float, result: float):
        if hasattr(self, "central_widget") and hasattr(self.central_widget, "render_integral_area"):
            self.central_widget.render_integral_area(expr, a, b, result)

    def on_render_tangent_line(self, expr: str, x0: float, k: float):
        if hasattr(self, "central_widget") and hasattr(self.central_widget, "render_tangent_line"):
            self.central_widget.render_tangent_line(expr, x0, k)

    # ── AI 全局交互集成 ──────────────────────────────────────────────
    def on_point_added(self, x: float, y: float) -> None:
        if hasattr(self, "geometry_engine"):
            self.geometry_engine.add_point(x, y)
        else:
            obj_id = str(uuid.uuid4())
            obj_data = {
                "id": obj_id,
                "name": t("geometry.new_point"),
                "type": "Point",
                "coordinates": {"x": x, "y": y},
            }
            self._add_object(obj_data)

    def on_segment_added(self, x1: float, y1: float, x2: float, y2: float) -> None:
        if hasattr(self, "geometry_engine"):
            p1_id = self.geometry_engine.add_point(x1, y1)
            p2_id = self.geometry_engine.add_point(x2, y2)
            self.geometry_engine.add_segment(p1_id, p2_id)
        else:
            obj_id = str(uuid.uuid4())
            obj_data = {
                "id": obj_id,
                "name": t("geometry.segment"),
                "type": "Segment",
                "coordinates": {"x1": x1, "y1": y1, "x2": x2, "y2": y2},
            }
            self._add_object(obj_data)

    def on_circle_added(self, cx: float, cy: float, radius: float) -> None:
        if hasattr(self, "geometry_engine"):
            c_id = self.geometry_engine.add_point(cx, cy)
            self.geometry_engine.add_circle(c_id, radius)
        else:
            obj_id = str(uuid.uuid4())
            obj_data = {
                "id": obj_id,
                "name": t("geometry.circle"),
                "type": "Circle",
                "coordinates": {"cx": cx, "cy": cy, "r": radius},
            }
            self._add_object(obj_data)

    def on_polygon_added(self, points: list) -> None:
        if hasattr(self, "geometry_engine"):
            p_ids = [self.geometry_engine.add_point(pt[0], pt[1]) for pt in points]
            self.geometry_engine.add_polygon(p_ids)
        else:
            obj_id = str(uuid.uuid4())
            obj_data = {
                "id": obj_id,
                "name": t("geometry.polygon"),
                "type": "Polygon",
                "coordinates": {"points": list(points)},
                "points": list(points),
            }
            self._add_object(obj_data)

    def on_algebra_item_selected(self, obj_id: str) -> None:
        self.central_widget.select_object(obj_id)
        if hasattr(self, "geometry_engine"):
            obj = self.geometry_engine.get_object(obj_id)
            if obj:
                self.properties_panel.set_object(obj.serialize())
        elif obj_id in self._objects_data:
            self.properties_panel.set_object(self._objects_data[obj_id])

    def on_object_color_changed(self, obj_id, color):
        if hasattr(self, "geometry_engine"):
            obj = self.geometry_engine.get_object(obj_id)
            if obj:
                obj.color = color
                self._update_object_display(obj_id, obj)

    def on_object_opacity_changed(self, obj_id, opacity):
        if hasattr(self, "geometry_engine"):
            obj = self.geometry_engine.get_object(obj_id)
            if obj:
                obj.opacity = opacity
                self._update_object_display(obj_id, obj)

    def on_object_stroke_changed(self, obj_id, stroke):
        if hasattr(self, "geometry_engine"):
            obj = self.geometry_engine.get_object(obj_id)
            if obj:
                obj.stroke = stroke
                self._update_object_display(obj_id, obj)

    def on_object_label_toggled(self, obj_id, show_label):
        if hasattr(self, "geometry_engine"):
            obj = self.geometry_engine.get_object(obj_id)
            if obj:
                obj.show_label = show_label
                self._update_object_display(obj_id, obj)

    def _update_object_display(self, obj_id, obj):
        obj_data = obj.serialize()
        self._objects_data[obj_id] = obj_data
        self.algebra_panel.update_object(obj_data)
        self.central_widget.update_object(obj_id, obj_data)

    def on_object_deleted(self, obj_id: str) -> None:
        if hasattr(self, "geometry_engine"):
            self.geometry_engine.remove_object(obj_id)
        else:
            self.central_widget.remove_object(obj_id)
            self.algebra_panel.remove_object(obj_id)
        self._objects_data.pop(obj_id, None)

    def on_delete_selected(self) -> None:
        if not hasattr(self, "central_widget"):
            return

        selected_items = self.central_widget.scene().selectedItems()
        for item in selected_items:
            if hasattr(item, "obj_id"):
                self.on_object_deleted(item.obj_id)

    def on_object_renamed(self, obj_id: str, new_name: str) -> None:
        if hasattr(self, "geometry_engine"):
            obj = self.geometry_engine.get_object(obj_id)
            if obj:
                obj.name = new_name
                obj_data = obj.serialize()
                self._objects_data[obj_id] = obj_data
                self.algebra_panel.update_object(obj_data)
                self.central_widget.update_object(obj_id, obj_data)
        else:
            if obj_id in self._objects_data:
                self._objects_data[obj_id]["name"] = new_name
                self.algebra_panel.update_object(self._objects_data[obj_id])
                self.central_widget.update_object(obj_id, self._objects_data[obj_id])

    def on_equation_changed(self, obj_id: str, new_equation: str) -> None:
        if not hasattr(self, "geometry_engine") or not hasattr(self, "cas_provider"):
            return

        obj = self.geometry_engine.get_object(obj_id)
        if not obj:
            return

        if obj.type in ["Line", "Segment"]:
            # 1. 定义计算成功后的更新回调（由 TaskManager 自动在主线程中触发，极其安全）
            def on_success(new_coords):
                if len(new_coords) >= 2:
                    self.geometry_engine.block_signals(True)

                    p1_id = obj.point1_id
                    p2_id = obj.point2_id

                    # 更新控制点
                    self.geometry_engine.update_point(p1_id, x=new_coords[0][0], y=new_coords[0][1])
                    self.geometry_engine.update_point(p2_id, x=new_coords[1][0], y=new_coords[1][1])

                    self.geometry_engine.block_signals(False)
                    obj.update_coordinates(self.geometry_engine)
                    # 触发全局画布重绘
                    self.on_geometry_event("object_updated", obj.serialize())

            # 2. 定义失败回调
            def on_error(err_msg):
                self.console.display_system_message(f"公式解析失败: {err_msg}", level="error")

            # 3. 将阻塞的方程反解任务丢入线程池！
            TaskManager().submit(
                fn=self.cas_provider.extract_line_control_points,
                on_success=on_success,
                on_error=on_error,
                group_id=f"eq_{obj_id}",
                equation_str=new_equation,
            )

    def on_console_command(self, command: str) -> None:
        if command == "%clear":
            self.central_widget.clear_canvas()
            self.algebra_panel.clear()
            self._objects_data.clear()
            if hasattr(self, "geometry_engine"):
                self.geometry_engine.clear()
            self.console.display_result(
                {
                    "success": True,
                    "output": t("errors.canvas_cleared") + "\n",
                    "error": "",
                    "more": False,
                }
            )
        elif hasattr(self, "python_repl"):
            # 沙箱执行会阻塞调用线程（最长 timeout+2 秒），必须移交线程池，
            # 否则执行期间整个 GUI 冻结。
            # 使用 group_id 保证沙箱命令串行：同组新请求覆盖排队请求，
            # 避免并发读写沙箱 stdin/stdout 造成结果错乱。
            TaskManager().submit(
                fn=self.python_repl.execute,
                on_success=self.console.display_result,
                on_error=lambda err: self.console.display_system_message(f"执行异常: {err}", level="error"),
                group_id="console_exec",
                code=command,
            )
        else:
            self.console.display_result(
                {
                    "success": False,
                    "output": "",
                    "error": t("errors.python_repl_not_initialized"),
                    "more": False,
                }
            )

    def on_command_entered(self, command: str) -> None:
        try:
            parts = command.split("=")
            if len(parts) == 2:
                name = parts[0].strip()
                value = parts[1].strip()

                if value.startswith("(") and value.endswith(")"):
                    coords = value[1:-1].split(",")
                    if len(coords) == 2:
                        x = float(coords[0].strip())
                        y = float(coords[1].strip())

                        if hasattr(self, "geometry_engine"):
                            self.geometry_engine.add_point(x, y, name=name)
                        else:
                            obj_id = str(uuid.uuid4())
                            obj_data = {
                                "id": obj_id,
                                "name": name,
                                "type": "Point",
                                "coordinates": {"x": x, "y": y},
                            }
                            self._add_object(obj_data)
        except Exception as e:
            QMessageBox.warning(
                self,
                t("dialogs.error"),
                t("dialogs.invalid_command", str(e)),
            )

    # ─────────────────────────────────────────────────────────────
    #  命令面板相关方法
    # ─────────────────────────────────────────────────────────────

    def handle_console_plot(self, plot_data: dict) -> None:
        """
        槽函数：接收来自 OctaveBridge.signals.plot_requested 的绘图请求。

        将 plot_data 序列化为 JSON 并通过 QWebEngineView.runJavaScript
        推送到 ECharts 前端渲染。

        同时调出 ECharts 插件的 QWebEngineView（通过 plugin_manager API 层展示）。
        """
        import json

        json_str = json.dumps(plot_data, ensure_ascii=False)
        # 调用前端统一入口函数 window.renderPlotData(payload)
        js_code = f"window.renderPlotData({json_str});"

        # 尝试通过 plugin_manager 获取 EChartsViewerPlugin 实例
        web_view = self._get_echarts_webview()
        if web_view is not None:
            web_view.page().runJavaScript(js_code)
        else:
            # 如果 ECharts 插件尚未加载，向控制台显示提示
            self.math_console.display_message("⚠ ECharts 插件未激活，请先加载并打开《高级数据调参》面板。", "warn")

    def _get_echarts_webview(self):
        """
        尝试通过 plugin_manager 获取 EChartsViewerPlugin 的 web_view。
        返回 QWebEngineView 实例，若未找到则返回 None。
        """
        if not hasattr(self, "plugin_manager"):
            return None
        try:
            # plugin_manager 注册的插件通常以类名或 id 为键
            pm = self.plugin_manager
            # 尝试常见的字典路径
            plugins = getattr(pm, "plugins", None) or getattr(pm, "_plugins", {})
            for key, plugin in (plugins.items() if hasattr(plugins, "items") else []):
                if hasattr(plugin, "web_view"):
                    return plugin.web_view
        except Exception:
            pass
        return None
