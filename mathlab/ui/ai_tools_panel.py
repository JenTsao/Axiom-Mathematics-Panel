import re

from PySide6.QtCore import QObject, Qt, QThread, QThreadPool, Signal
from PySide6.QtGui import QBrush, QColor, QPen, QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QDockWidget,
    QFrame,
    QGraphicsEllipseItem,
    QGraphicsLineItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from mathlab.core.agent_registry import get_agent
from mathlab.core.ai_manager import AIProvider, AIRequestConfig, AIState
from mathlab.core.ai_tools import AVAILABLE_TOOLS, validate_tool_call
from mathlab.core.async_workers import TaskWorker
from mathlab.core.context_assembler import ContextAssembler
from mathlab.core.jupyter_manager import get_jupyter_sandbox
from mathlab.core.memory_manager import ChatMemoryManager
from mathlab.core.prompt_manager import prompt_manager
from mathlab.ui.animated_widgets import BreathingLabel, SmoothCollapsibleBox
from mathlab.ui.animations import start_breathing_effect, stop_animation
from mathlab.ui.code_editor import AutocompleteTextEdit
from mathlab.ui.latex_chat_widget import LatexChatWidget
from mathlab.ui.quiz_panel import QuizCardWidget
from mathlab.utils.i18n_manager import t

try:
    from mathlab.utils.logger import get_logger

    logger = get_logger(__name__)
except ImportError:
    import logging

    logger = logging.getLogger(__name__)


class AIToolsPanel(QDockWidget):
    fit_requested = Signal(list, str, dict)
    cluster_requested = Signal(list, str, dict)
    recognize_requested = Signal(list)
    generate_points = Signal(int)
    action_requested = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(t("ai_tools.title"), parent)
        self.setAllowedAreas(Qt.RightDockWidgetArea)
        self.worker = None  # AIRequestWorker(QThread) 实例
        self.context_assembler = ContextAssembler(prompt_manager)

        self.widget = QWidget()
        self.layout = QVBoxLayout(self.widget)

        self.tab_widget = QTabWidget()

        # ------------------------------------------------------------------
        # Tab 0: Scatter Fitting
        # ------------------------------------------------------------------
        self.scatter_tab = QWidget()
        self.scatter_layout = QVBoxLayout(self.scatter_tab)

        self.model_combo = QComboBox()
        self.model_combo.addItem(t("ai_tools.linear_regression"), "linear_regression")
        self.model_combo.addItem(t("ai_tools.polynomial_regression"), "polynomial_regression")
        self.model_combo.addItem(t("ai_tools.neural_network"), "neural_network")

        self.degree_spin = QSpinBox()
        self.degree_spin.setRange(2, 5)
        self.degree_spin.setValue(2)

        self.fit_button = QPushButton(t("ai_tools.fit_data"))
        self.clear_points_button = QPushButton(t("ai_tools.clear_points"))
        self.generate_button = QPushButton(t("ai_tools.generate_random_points"))
        self.points_count_spin = QSpinBox()
        self.points_count_spin.setRange(5, 50)
        self.points_count_spin.setValue(10)

        self.model_type_label = QLabel(t("ai_tools.model_type"))
        self.scatter_layout.addWidget(self.model_type_label)
        self.scatter_layout.addWidget(self.model_combo)

        self.poly_degree_label = QLabel(t("ai_tools.polynomial_degree"))
        self.scatter_layout.addWidget(self.poly_degree_label)
        self.scatter_layout.addWidget(self.degree_spin)

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.fit_button)
        button_layout.addWidget(self.clear_points_button)
        button_layout.addWidget(self.generate_button)
        button_layout.addWidget(self.points_count_spin)
        self.scatter_layout.addLayout(button_layout)

        self.result_label = QLabel(t("ai_tools.result"))
        self.scatter_layout.addWidget(self.result_label)

        self.equation_label = QLabel()
        self.equation_label.setStyleSheet("font-family: serif; font-size: 14px;")
        self.scatter_layout.addWidget(self.equation_label)

        self.mse_label = QLabel()
        self.scatter_layout.addWidget(self.mse_label)

        self.tab_widget.addTab(self.scatter_tab, t("ai_tools.scatter_fitting"))

        # ------------------------------------------------------------------
        # Tab 1: Digit Recognition
        # ------------------------------------------------------------------
        self.digit_tab = QWidget()
        self.digit_layout = QVBoxLayout(self.digit_tab)

        self.drawing_view = QGraphicsView()
        self.drawing_scene = QGraphicsScene()
        self.drawing_view.setScene(self.drawing_scene)
        self.drawing_view.setFixedSize(280, 280)
        self.drawing_view.setStyleSheet("background-color: white; border: 1px solid #c3c6d7;")

        self.drawing_points = []

        self.recognize_button = QPushButton(t("ai_tools.recognize_digit"))
        self.clear_drawing_button = QPushButton(t("ai_tools.clear_drawing"))

        self.digit_layout.addWidget(self.drawing_view)
        self.digit_layout.addWidget(self.recognize_button)
        self.digit_layout.addWidget(self.clear_drawing_button)

        self.result_digit_label = QLabel(t("ai_tools.prediction"))
        self.digit_layout.addWidget(self.result_digit_label)

        self.top3_label = QLabel()
        self.digit_layout.addWidget(self.top3_label)

        self.tab_widget.addTab(self.digit_tab, t("ai_tools.digit_recognition"))

        # ------------------------------------------------------------------
        # Tab 2: Clustering
        # ------------------------------------------------------------------
        self.cluster_tab = QWidget()
        self.cluster_layout = QVBoxLayout(self.cluster_tab)

        self.cluster_method_combo = QComboBox()
        self.cluster_method_combo.addItem(t("ai_tools.kmeans"), "k-means")
        self.cluster_method_combo.addItem(t("ai_tools.dbscan"), "dbscan")

        self.cluster_count_spin = QSpinBox()
        self.cluster_count_spin.setRange(2, 10)
        self.cluster_count_spin.setValue(3)

        self.cluster_button = QPushButton(t("ai_tools.run_clustering"))

        self.cluster_method_label = QLabel(t("ai_tools.method"))
        self.cluster_layout.addWidget(self.cluster_method_label)
        self.cluster_layout.addWidget(self.cluster_method_combo)

        self.cluster_count_label = QLabel(t("ai_tools.number_of_clusters"))
        self.cluster_layout.addWidget(self.cluster_count_label)
        self.cluster_layout.addWidget(self.cluster_count_spin)
        self.cluster_layout.addWidget(self.cluster_button)

        self.cluster_result_label = QLabel()
        self.cluster_layout.addWidget(self.cluster_result_label)

        self.tab_widget.addTab(self.cluster_tab, t("ai_tools.clustering"))

        # ------------------------------------------------------------------
        # Tab 3: Training Notebook
        # ------------------------------------------------------------------
        self.training_tab = QWidget()
        self.training_layout = QVBoxLayout(self.training_tab)

        self.code_editor = AutocompleteTextEdit()
        self.code_editor.setPlaceholderText(t("ai_tools.write_training_code"))
        self.code_editor.setStyleSheet("""
            QPlainTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                font-family: Consolas, monospace;
                font-size: 12px;
            }
        """)

        self.run_button = QPushButton(t("ai_tools.run_training"))
        self.stop_training_button = QPushButton(t("ai_tools.stop"))

        self.progress_bar = QProgressBar()

        self.output_area = QTextBrowser()
        self.output_area.setOpenExternalLinks(True)
        self.output_area.setStyleSheet("""
            QTextBrowser {
                background-color: #1e1e1e;
                color: #d4d4d4;
                font-family: Consolas, monospace;
                font-size: 11px;
            }
        """)

        self.training_layout.addWidget(self.code_editor)
        self.training_layout.addWidget(self.run_button)
        self.training_layout.addWidget(self.stop_training_button)
        self.training_layout.addWidget(self.progress_bar)
        self.training_layout.addWidget(self.output_area)

        self.tab_widget.addTab(self.training_tab, t("ai_tools.training_notebook"))

        # ------------------------------------------------------------------
        # Tab 4: AI Assistant Chat
        # ------------------------------------------------------------------
        self.assistant_tab = QWidget()
        self.assistant_layout = QVBoxLayout(self.assistant_tab)

        self.provider_combo = QComboBox()
        self.provider_combo.addItem("Local Demo", AIProvider.LOCAL.value)
        self.provider_combo.addItem("OpenAI", AIProvider.OPENAI.value)
        self.provider_combo.addItem("Claude", AIProvider.CLAUDE.value)
        self.provider_combo.addItem("Gemini", AIProvider.GEMINI.value)
        self.provider_combo.addItem("DeepSeek", AIProvider.DEEPSEEK.value)
        self.provider_combo.addItem("Kimi", AIProvider.KIMI.value)
        self.provider_combo.addItem("Minimax", AIProvider.MINIMAX.value)
        self.provider_combo.addItem("Qwen (通义千问)", AIProvider.QWEN.value)
        self.provider_combo.addItem("Zhipu (智谱清言)", AIProvider.ZHIPU.value)
        self.provider_combo.addItem("Doubao (豆包)", AIProvider.DOUBAO.value)
        self.provider_combo.addItem("Ollama", AIProvider.OLLAMA.value)

        provider_layout = QHBoxLayout()
        provider_layout.addWidget(QLabel(t("ai_tools.provider")))
        provider_layout.addWidget(self.provider_combo)
        provider_layout.addStretch()
        self.assistant_layout.addLayout(provider_layout)

        # ✨ 新增：教学计划状态池
        self.active_plan_steps = []
        self.current_step_index = 0

        # 1. 顶部：可平滑折叠的教学规划区
        self.plan_box = SmoothCollapsibleBox("📋 教学大纲 (点击折叠/展开)")
        plan_inner_layout = QVBoxLayout()
        self.plan_list_view = QListWidget()
        self.plan_list_view.setFixedHeight(120)  # 限制最高高度
        self.plan_list_view.setStyleSheet("border: 1px solid #E0E0E0; border-radius: 4px;")

        self.start_teach_btn = QPushButton("🚀 开始分步互动讲解")
        self.start_teach_btn.setEnabled(False)
        self.start_teach_btn.setStyleSheet("background-color: #27AE60; color: white; padding: 6px; border-radius: 4px;")
        self.start_teach_btn.clicked.connect(self._start_execution_teaching)

        plan_inner_layout.addWidget(self.plan_list_view)
        plan_inner_layout.addWidget(self.start_teach_btn)
        self.plan_box.set_content_layout(plan_inner_layout)

        # 初始状态下静默折叠隐藏
        self.plan_box.collapse_silently()
        self.plan_box.setVisible(False)

        # 2. 中部：富文本渲染的聊天历史 (我们在上一节刚换上的 WebEngine)
        self.chat_display = LatexChatWidget()

        self.card_layout = QVBoxLayout()

        # 教学控制条：上一步、下一步
        self.step_control_bar = QHBoxLayout()
        self.current_step_banner = QLabel("🚶‍♂️ 准备就绪")
        self.current_step_banner.setStyleSheet("color: #007ACC; font-weight: bold;")
        self.next_step_btn = QPushButton("⏭️ 下一步提示")
        self.next_step_btn.setVisible(False)
        self.next_step_btn.clicked.connect(self._trigger_next_step_lecture)

        self.step_control_bar.addWidget(self.current_step_banner)
        self.step_control_bar.addStretch()
        self.step_control_bar.addWidget(self.next_step_btn)

        # 3. 底部：输入区
        self.chat_input = QLineEdit()
        self.chat_input.setFixedHeight(40)
        self.chat_input.setStyleSheet("border: 1px solid #CCC; border-radius: 6px; padding: 4px;")
        self.chat_input.setPlaceholderText(t("ai_tools.ask_question"))
        self.chat_input.returnPressed.connect(self.on_send_message)

        self.send_button = QPushButton(t("ai_tools.send"))
        self.send_button.clicked.connect(self.on_send_message)

        input_layout = QHBoxLayout()
        input_layout.addWidget(self.chat_input)
        input_layout.addWidget(self.send_button)

        # 4. 最底部：带呼吸特效的状态栏
        self.status_bar = QWidget()
        status_layout = QHBoxLayout(self.status_bar)
        status_layout.setContentsMargins(0, 0, 0, 0)

        self.current_agent_id = "general"
        agent = get_agent(self.current_agent_id)

        self.agent_label = QLabel(f"{agent.icon} {agent.name} (@{agent.id})")
        # ✨ 换上我们带有呼吸律动特性的 Label
        self.action_label = BreathingLabel("💤 就绪")
        self.action_label.setStyleSheet("font-weight: bold; color: #555;")
        self.token_label = QLabel("⚡ 0 Tokens")

        status_layout.addWidget(self.agent_label)
        status_layout.addStretch()
        status_layout.addWidget(self.action_label)
        status_layout.addStretch()
        status_layout.addWidget(self.token_label)

        # 垂直组装所有部件
        self.assistant_layout.addWidget(self.plan_box)
        self.assistant_layout.addWidget(self.chat_display)
        self.assistant_layout.addLayout(self.card_layout)
        self.assistant_layout.addLayout(self.step_control_bar)
        self.assistant_layout.addLayout(input_layout)
        self.assistant_layout.addWidget(self.status_bar)

        self.tab_widget.addTab(self.assistant_tab, t("ai_tools.ai_assistant"))

        # ------------------------------------------------------------------
        self.layout.addWidget(self.tab_widget)
        self.setWidget(self.widget)

        # Signal connections
        self.fit_button.clicked.connect(self.on_fit)
        self.clear_points_button.clicked.connect(self.on_clear_points)
        self.generate_button.clicked.connect(self.on_generate_points)
        self.recognize_button.clicked.connect(self.on_recognize)
        self.clear_drawing_button.clicked.connect(self.on_clear_drawing)
        self.cluster_button.clicked.connect(self.on_cluster)
        self.run_button.clicked.connect(self.on_run_training)
        self.stop_training_button.clicked.connect(self.on_stop_training)

        self.drawing_view.mousePressEvent = self.on_drawing_press
        self.drawing_view.mouseMoveEvent = self.on_drawing_move

        self.scatter_points = []
        self.is_generating = False

    # ------------------------------------------------------------------
    # i18n
    # ------------------------------------------------------------------
    def retranslate_ui(self):
        self.setWindowTitle(t("ai_tools.title"))

        # Tab titles
        self.tab_widget.setTabText(0, t("ai_tools.scatter_fitting"))
        self.tab_widget.setTabText(1, t("ai_tools.digit_recognition"))
        self.tab_widget.setTabText(2, t("ai_tools.clustering"))
        self.tab_widget.setTabText(3, t("ai_tools.training_notebook"))

        # Scatter tab
        self.model_type_label.setText(t("ai_tools.model_type"))
        self.model_combo.setItemText(0, t("ai_tools.linear_regression"))
        self.model_combo.setItemText(1, t("ai_tools.polynomial_regression"))
        self.model_combo.setItemText(2, t("ai_tools.neural_network"))
        self.poly_degree_label.setText(t("ai_tools.polynomial_degree"))
        self.fit_button.setText(t("ai_tools.fit_data"))
        self.clear_points_button.setText(t("ai_tools.clear_points"))
        self.generate_button.setText(t("ai_tools.generate_random_points"))
        self.result_label.setText(t("ai_tools.result"))

        # Digit tab
        self.recognize_button.setText(t("ai_tools.recognize_digit"))
        self.clear_drawing_button.setText(t("ai_tools.clear_drawing"))
        self.result_digit_label.setText(t("ai_tools.prediction"))

        # Cluster tab
        self.cluster_method_label.setText(t("ai_tools.method"))
        self.cluster_method_combo.setItemText(0, t("ai_tools.kmeans"))
        self.cluster_method_combo.setItemText(1, t("ai_tools.dbscan"))
        self.cluster_count_label.setText(t("ai_tools.number_of_clusters"))
        self.cluster_button.setText(t("ai_tools.run_clustering"))

        # Training tab
        self.code_editor.setPlaceholderText(t("ai_tools.write_training_code"))
        self.run_button.setText(t("ai_tools.run_training"))
        self.stop_training_button.setText(t("ai_tools.stop"))

    # ------------------------------------------------------------------
    # Slot handlers
    # ------------------------------------------------------------------
    def on_fit(self):
        # Use stored userData key instead of parsing display text
        model_type = self.model_combo.currentData()

        if model_type == "polynomial_regression":
            params = {"degree": self.degree_spin.value()}
        else:
            params = {}

        self.fit_requested.emit(self.scatter_points, model_type, params)

    def on_clear_points(self):
        self.scatter_points.clear()
        self.equation_label.clear()
        self.mse_label.clear()

    def on_generate_points(self):
        n = self.points_count_spin.value()
        self.generate_points.emit(n)

    def on_recognize(self):
        image_data = self.get_drawing_data()
        self.recognize_requested.emit(image_data)

    def on_clear_drawing(self):
        self.drawing_scene.clear()
        self.drawing_points.clear()

    def on_cluster(self):
        # Use stored userData key instead of parsing display text
        method = self.cluster_method_combo.currentData()
        params = {"n_clusters": self.cluster_count_spin.value()}
        self.cluster_requested.emit(self.scatter_points, method, params)

    def on_run_training(self):
        code = self.code_editor.toPlainText()
        if not code.strip():
            return

        self.output_area.clear()
        self.output_area.append(t("ai_tools.running_training"))
        self.set_loading_state(True)

        # 将任务推入线程池
        worker = TaskWorker(get_jupyter_sandbox().execute_code, code, timeout=10)
        worker.signals.finished.connect(self.on_execution_finished)
        worker.signals.error.connect(self._on_training_error)
        QThreadPool.globalInstance().start(worker)

    def _on_training_error(self, error_msg: str):
        """训练任务异常兜底：恢复按钮状态并提示错误，避免永久卡在 loading。"""
        self.set_loading_state(False)
        self.output_area.append(f"<span style='color:red;'>❌ {error_msg}</span>")

    def on_execution_finished(self, result_dict):
        # 恢复按钮
        self.set_loading_state(False)

        if result_dict["status"] == "error" or result_dict["status"] == "timeout":
            # 渲染红色报错信息
            error_text = "<br>".join(result_dict["traceback"]).replace("\n", "<br>")
            self.output_area.append(f"<span style='color:red;'>{error_text}</span>")
        else:
            # 渲染正常的 print 输出
            if result_dict["text"]:
                self.output_area.append(result_dict["text"].replace("\n", "<br>"))

            # 渲染 Base64 图像 (如果使用了 matplotlib)
            for base64_img in result_dict.get("images", []):
                html_img = f"<img src='data:image/png;base64,{base64_img}' width='400'>"
                self.output_area.append(html_img)

    def on_stop_training(self):
        self.output_area.append("Training stopped / Kernel Restarting...")
        get_jupyter_sandbox().restart_kernel()
        self.set_loading_state(False)

    def on_drawing_press(self, event):
        scene_pos = self.drawing_view.mapToScene(event.pos())
        self.drawing_points.append((scene_pos.x(), scene_pos.y()))

        dot = QGraphicsEllipseItem(scene_pos.x() - 5, scene_pos.y() - 5, 10, 10)
        dot.setBrush(QBrush(QColor("#0b1c30")))
        self.drawing_scene.addItem(dot)

    def on_drawing_move(self, event):
        if self.drawing_points:
            scene_pos = self.drawing_view.mapToScene(event.pos())
            last_x, last_y = self.drawing_points[-1]

            line = QGraphicsLineItem(last_x, last_y, scene_pos.x(), scene_pos.y())
            line.setPen(QPen(QColor("#0b1c30"), 8))
            self.drawing_scene.addItem(line)

            self.drawing_points.append((scene_pos.x(), scene_pos.y()))

    # ------------------------------------------------------------------
    # Data helpers
    # ------------------------------------------------------------------
    def get_drawing_data(self, stroke_radius=2):
        data = [[0] * 28 for _ in range(28)]

        for x, y in self.drawing_points:
            grid_x = min(max(0, int(x / 10)), 27)
            grid_y = min(max(0, int(y / 10)), 27)

            for dy in range(-stroke_radius, stroke_radius + 1):
                for dx in range(-stroke_radius, stroke_radius + 1):
                    nx = grid_x + dx
                    ny = grid_y + dy
                    if 0 <= nx < 28 and 0 <= ny < 28:
                        distance = (dx**2 + dy**2) ** 0.5
                        if distance <= stroke_radius:
                            intensity = int(255 * (1 - distance / (stroke_radius + 1)))
                            data[ny][nx] = max(data[ny][nx], intensity)

        return data

    def set_scatter_points(self, points):
        self.scatter_points = points

    def set_fit_result(self, result):
        if result.get("success"):
            self.equation_label.setText(result.get("equation", ""))
            self.mse_label.setText(f'MSE: {result.get("mse", 0):.4f}')

    def set_recognition_result(self, result):
        if result.get("success"):
            self.result_digit_label.setText(f'{t("ai_tools.prediction")} {result["prediction"]}')
            top3 = result.get("top3", [])
            top3_text = "\n".join([f'{item["digit"]}: {item["probability"]:.2%}' for item in top3])
            self.top3_label.setText(f'{t("ai_tools.top3")}\n{top3_text}')

    def set_cluster_result(self, result):
        if result.get("success"):
            self.cluster_result_label.setText(f'{t("ai_tools.cluster_count")} {result.get("n_clusters", 0)}')

    def append_training_output(self, text):
        self.output_area.append(text)

    def set_loading_state(self, is_loading: bool):
        self.fit_button.setEnabled(not is_loading)
        self.cluster_button.setEnabled(not is_loading)
        self.recognize_button.setEnabled(not is_loading)
        self.generate_button.setEnabled(not is_loading)
        self.run_button.setEnabled(not is_loading)
        self.stop_training_button.setEnabled(is_loading)

    # ------------------------------------------------------------------
    # AI Assistant Chat Methods
    # ------------------------------------------------------------------
    def switch_agent(self, agent_id: str):
        """切换 UI 状态栏和底层上下文"""
        agent = get_agent(agent_id)
        self.current_agent_id = agent.id
        self.agent_label.setText(f"{agent.icon} {agent.name} (@{agent.id})")

    def _handle_slash_command(self, text: str):
        """解析并执行 / 开头的本地指令"""
        parts = text.split(maxsplit=1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        main_window = self.window()
        engine = getattr(main_window, "geometry_engine", None)

        if command == "/clear":
            if engine:
                if hasattr(engine, "clear"):
                    engine.clear()
                self.chat_display.add_message("ai", "**[系统]** 画板已清空。")

        elif command == "/draft":
            if engine:
                if not getattr(engine, "is_draft_mode", False):
                    if hasattr(engine, "begin_draft"):
                        engine.begin_draft()
                    self.chat_display.add_message("ai", "**[系统]** 👻 已进入画板草稿模式。")
                else:
                    if hasattr(engine, "commit_draft"):
                        engine.commit_draft()
                    self.chat_display.add_message("ai", "**[系统]** ✅ 草稿已合并至正式画板。")

        elif command == "/quiz":
            self.switch_agent("quiz")
            topic = args if args else "当前画板上的几何图形"
            self.chat_input.setText(f"请根据 {topic} 出一道测试题。")
            self.on_send_message()

        elif command == "/help":
            help_text = """
            <b>⚡ 快捷指令指南：</b><br>
            <kbd>/clear</kbd> - 清空当前画板<br>
            <kbd>/draft</kbd> - 开启/确认草稿模式<br>
            <kbd>/quiz [知识点]</kbd> - 强制生成测验<br>
            <kbd>@geometry</kbd> - 召唤几何专家画图<br>
            """
            self.chat_display.add_message("ai", help_text)

        else:
            self.chat_display.add_message("ai", f"**[错误]** 未知指令: {command}，输入 /help 查看支持的命令。")

    def on_send_message(self):
        if self.is_generating:
            main_win = self.window()
            if hasattr(main_win, "ai_manager") and getattr(main_win.ai_manager, "current_worker", None):
                main_win.ai_manager.current_worker.cancel()
            self.on_request_finished(was_cancelled=True)
            self.chat_display.add_message("ai", "*[已停止生成]*")
            return

        raw_text = self.chat_input.text().strip()
        if not raw_text:
            return

        self.chat_input.clear()

        # --- 1. 拦截本地快捷指令 (/) ---
        if raw_text.startswith("/"):
            self._handle_slash_command(raw_text)
            return

        # --- 2. 拦截专家调度指令 (@) ---
        match = re.match(r"^@([a-zA-Z0-9_]+)\s*(.*)", raw_text)
        if match:
            target_agent = match.group(1).lower()
            prompt_text = match.group(2).strip()
            self.switch_agent(target_agent)
            if not prompt_text:
                return
            user_text = prompt_text
        else:
            user_text = raw_text

        # --- 3. 发送给指定的专家处理 ---
        if not hasattr(self, "current_agent_id"):
            self.current_agent_id = "general"
        agent = get_agent(self.current_agent_id)

        self.chat_display.add_message("user", user_text)

        self.chat_input.setEnabled(False)
        self.send_button.setText("⏹ 停止生成")
        self.send_button.setStyleSheet("background-color: #E74C3C; color: white;")
        self.is_generating = True

        main_win = self.window()
        tracker = getattr(main_win, "canvas_tracker", None)
        current_canvas_state = tracker.current_state_json if tracker else None

        # ✨ 核心魔法：调用动态组装器，生成纯净且精准的超级 Prompt
        dynamic_system_prompt = self.context_assembler.build_dynamic_system_prompt(
            base_system_prompt=agent.system_prompt,
            user_text=user_text,
            canvas_tracker=tracker,
        )

        self._current_response = ""
        self._last_user_text = user_text

        if hasattr(main_win, "ai_manager"):
            main_win.ai_manager.ask(
                user_prompt=user_text,
                system_prompt=dynamic_system_prompt,
                tools=agent.tools,
                canvas_state=current_canvas_state,
                on_state_change=self._on_state_change,
                on_chunk=self.on_chunk_received,
                on_tool=self.on_tool_call_received,
                on_usage=self._on_usage_reported,
                on_finish=self.on_request_finished,
                on_error=self.on_request_error,
            )
            self.breath_anim = start_breathing_effect(self.send_button)
        else:
            self.on_request_error("AIManager 未初始化！")

    def _get_system_context(self):
        system_context = {}
        main_win = self.window()

        if hasattr(main_win, "geometry_engine"):
            try:
                system_context["geometry"] = main_win.geometry_engine.serialize_all()
            except Exception:
                system_context["geometry"] = {}

        if hasattr(main_win, "cas_provider"):
            system_context["cas_enabled"] = True

        return system_context

    def on_chunk_received(self, text_chunk: str):
        self.chat_display.update_streaming_chunk(text_chunk)

    def on_action_required(self, action_data: dict):
        self.action_requested.emit(action_data)

    def _on_nested_request_finished(self, was_cancelled=False):
        self._nested_ask_in_progress = False
        self.on_request_finished(was_cancelled)

    def on_request_finished(self, was_cancelled=False):
        if getattr(self, "_nested_ask_in_progress", False):
            return

        self.chat_input.setEnabled(True)
        self.send_button.setEnabled(True)
        self.send_button.setText(t("ai_tools.send"))
        self.send_button.setStyleSheet("")
        self.chat_input.setFocus()
        self.is_generating = False

        if hasattr(self, "breath_anim"):
            stop_animation(self.send_button)

        if not was_cancelled:
            # 流式结束，固化到 WebEngine 内部状态
            self.chat_display.finalize_streaming_message()

    def _execute_with_reflection(self, tool_name: str, args_dict: dict, retry_count: int):
        """
        核心反思机制：带最大尝试次数的智能容错执行器
        """
        MAX_RETRIES = 3

        main_window = self.window()
        engine = getattr(main_window, "geometry_engine", None)

        if retry_count >= MAX_RETRIES:
            self.chat_display.add_message("ai", "🚨 **AI 尝试了 3 次修正均告失败，已自动中止操作。**")
            self.action_label.setText("❌ 执行中止")
            if engine and hasattr(engine, "discard_draft"):
                engine.discard_draft()
            return

        try:
            commands = args_dict.get("commands", [])
            if not commands and "cmd" in args_dict:
                commands = [args_dict]

            if engine:
                if retry_count == 0 and hasattr(engine, "begin_draft"):
                    engine.begin_draft()  # 开启草稿模式保护

                if hasattr(engine, "validate_commands"):
                    engine.validate_commands(commands)

                if hasattr(main_window, "central_widget"):
                    main_window.central_widget.execute_commands_with_animation(engine, commands)

                self._render_draft_review_card()  # 弹出采纳/撤销卡片
                self.action_label.setText("✅ 画图完成")

                self.chat_display.add_message("ai", "✨ *AI 助教正在您的画板上绘制...*")

        except Exception as e:
            error_msg = str(e)

            self.action_label.setText(f"🛠️ 正在修复 ({retry_count+1}/{MAX_RETRIES})...")

            import json

            reflection_prompt = f"""
你在调用 `{tool_name}` 时发生了严重的运行时错误！
❌ 错误信息详情：
{error_msg}

原参数输出：
{json.dumps(args_dict, ensure_ascii=False)}

请立刻反思错误原因（如：是否引用了未创建的点？是否参数名称写错了？）。
根据当前的画板状态，修正你的逻辑，并**直接再次调用画图工具**。禁止输出废话。
"""
            if hasattr(main_window, "ai_manager"):
                self._nested_ask_in_progress = True
                self.chat_input.setEnabled(False)
                main_window.ai_manager.ask(
                    user_prompt=reflection_prompt,
                    system_prompt="你是一个具备极强自我反省能力的数学专家。当系统报错时，你必须通过再次调用工具来修复它。",
                    tools=get_agent(self.current_agent_id).tools,
                    on_tool=lambda name, new_args: self._execute_with_reflection(name, new_args, retry_count + 1),
                    on_finish=self._on_nested_request_finished,
                    on_error=lambda err: logger.error("静默修复网络异常: %s", err),
                )

    def _handle_agent_handoff(self, args_dict: dict):
        """核心路由引擎：处理智能体之间的无缝切换"""
        try:
            target_agent_id = args_dict.get("target_agent")
            notes = args_dict.get("handover_notes")

            # 获取上一个专家的身份（用于 UI 展示）
            prev_agent = get_agent(self.current_agent_id)

            # 1. 在聊天框打印极其极客的“内部交接日志”
            handoff_msg = (
                f'🤝 **[协作协议触发]** {prev_agent.name} 将任务移交给了 @{target_agent_id}\n\n*内部工单: "{notes}"*'
            )
            self.chat_display.add_message("ai", handoff_msg)

            # 2. 视觉与逻辑同步：一键切换到目标专家
            self.switch_agent(target_agent_id)
            new_agent = get_agent(self.current_agent_id)

            # 3. 构造冰冷的“系统级指令”，强制唤醒新专家干活！
            relay_prompt = f"""
[系统内部工作交接单]
前任专家给你留下了以下任务需求：
"{notes}"

请立即调动你的专业知识和专属工具执行上述任务。直接给出结果，禁止输出任何如“好的，我收到了交接单”之类的废话。
"""
            # 4. 静默发起内部请求（新专家开始接手跑流水线）
            self.action_label.setText(f"🏃‍♂️ {new_agent.name} 接手处理...")

            main_window = self.window()
            if hasattr(main_window, "ai_manager"):
                self._nested_ask_in_progress = True
                self.chat_input.setEnabled(False)
                main_window.ai_manager.ask(
                    user_prompt=relay_prompt,
                    system_prompt=new_agent.system_prompt,
                    tools=new_agent.tools,
                    on_state_change=self._on_state_change,
                    on_tool=self.on_tool_call_received,
                    on_chunk=self.on_chunk_received,
                    on_usage=self._on_usage_reported,
                    on_finish=self._on_nested_request_finished,
                    on_error=self.on_request_error,
                )

        except Exception as e:
            logger.error("Agent 接力失败: %s", e)

    def on_tool_call_received(self, tool_name, args_dict):
        main_window = self.window()

        # === 工具参数校验 ===
        is_valid, error_msg = validate_tool_call(tool_name, args_dict)
        if not is_valid:
            logger.warning("工具参数校验失败: tool=%s, error=%s", tool_name, error_msg)
            self.chat_display.add_message(
                "ai",
                f"⚠️ **[参数校验失败]** 工具 `{tool_name}` 的参数无效：\n\n> {error_msg}",
            )
            return

        # === 审计日志 ===
        import time

        _start_time = time.time()
        logger.info(
            "工具调用开始: tool=%s, args_keys=%s",
            tool_name,
            list(args_dict.keys()) if isinstance(args_dict, dict) else "N/A",
        )

        if tool_name == "submit_teaching_plan":
            try:
                self.active_plan_steps = args_dict.get("steps", [])
                topic = args_dict.get("topic", "新课题")

                # 刷新 UI 大纲列表
                self.plan_box.toggle_btn.setText(f"📋 教学大纲: {topic} (点击折叠/展开)")
                self.plan_list_view.clear()

                for step in self.active_plan_steps:
                    item_text = f"第 {step['num']} 步: {step['title']}"
                    item = QListWidgetItem(item_text)
                    self.plan_list_view.addItem(item)

                # 激活解锁按钮，强制弹回 Plan Tab 让用户审查
                self.start_teach_btn.setEnabled(True)
                self.plan_box.setVisible(True)
                # 💡 触发平滑展开动画
                self.plan_box.expand_silently()

            except Exception as e:
                logger.error("解析大纲 JSON 失败: %s", e)
        elif tool_name == "transfer_to_agent":
            self._handle_agent_handoff(args_dict)
        elif tool_name == "generate_math_quiz":
            try:
                quiz_card = QuizCardWidget(args_dict, main_window.ai_manager)
                self.card_layout.addWidget(quiz_card)
            except Exception as e:
                logger.error("生成测验卡片失败: %s", e)
        elif tool_name == "execute_geometry_draw":
            self._execute_with_reflection(tool_name, args_dict, retry_count=0)
        elif tool_name == "speak_at_location":
            try:
                target_name = args_dict.get("target_element")
                text = args_dict.get("text")
                if hasattr(main_window, "geometry_engine") and hasattr(main_window, "central_widget"):
                    engine = main_window.geometry_engine
                    canvas = main_window.central_widget
                    target_obj = None
                    for obj in engine.objects.values():
                        if getattr(obj, "name", "") == target_name:
                            target_obj = obj
                            break
                    if target_obj and hasattr(canvas, "spawn_spatial_bubble"):
                        canvas.spawn_spatial_bubble(target_obj.id, text)
                        magic_html = f"<div style='color: #8E44AD; margin-left: 10px;'><i>📍 已在 {target_name} 旁生成讲解气泡</i></div><br>"
                        self.chat_display.append(magic_html)
            except Exception as e:
                logger.error("生成空间气泡失败: %s", e)
        elif tool_name == "highlight_geometry_elements":
            try:
                element_names = args_dict.get("element_names", [])
                color = args_dict.get("color", "orange")

                if hasattr(main_window, "geometry_engine") and hasattr(main_window, "central_widget"):
                    main_window.central_widget.highlight_elements(main_window.geometry_engine, element_names, color)
                    magic_html = f"<div style='background-color: #FEF9E7; color: #D35400; padding: 8px; border-radius: 4px; border-left: 4px solid #F39C12;'><i>🔦 激光笔已激活：正在引导关注 {', '.join(element_names)} </i></div><br>"
                    self.chat_display.append(magic_html)
            except Exception as e:
                logger.error("高亮指令执行失败: %s", e)

        # === 审计日志：记录完成 ===
        _elapsed = time.time() - _start_time
        logger.info("工具调用完成: tool=%s, 耗时=%.3fs", tool_name, _elapsed)

    def _render_draft_review_card(self):
        card_widget = QWidget()
        card_layout = QHBoxLayout(card_widget)
        card_layout.setContentsMargins(10, 5, 10, 5)

        msg_label = QLabel("✨ AI 画好了一个草稿图，是否采纳？")
        msg_label.setStyleSheet("color: #0078D7; font-weight: bold;")

        btn_accept = QPushButton("✅ 采纳")
        btn_accept.setStyleSheet(
            "background-color: #E8F5E9; border: 1px solid #4CAF50; border-radius: 4px; padding: 4px 8px;"
        )

        btn_discard = QPushButton("❌ 撤销")
        btn_discard.setStyleSheet(
            "background-color: #FFEBEE; border: 1px solid #F44336; border-radius: 4px; padding: 4px 8px;"
        )

        card_layout.addWidget(msg_label)
        card_layout.addStretch()
        card_layout.addWidget(btn_accept)
        card_layout.addWidget(btn_discard)

        self.card_layout.addWidget(card_widget)

        def on_accept():
            main_window = self.window()
            if hasattr(main_window, "geometry_engine") and hasattr(main_window.geometry_engine, "commit_draft"):
                main_window.geometry_engine.commit_draft()
            card_widget.deleteLater()
            self.chat_display.append("<div style='color: #27AE60;'><i>[系统] 您已采纳 AI 的画图方案。</i></div><br>")

        def on_discard():
            main_window = self.window()
            if hasattr(main_window, "geometry_engine") and hasattr(main_window.geometry_engine, "discard_draft"):
                main_window.geometry_engine.discard_draft()
            card_widget.deleteLater()
            self.chat_display.append("<div style='color: #E74C3C;'><i>[系统] 草稿已撤销。</i></div><br>")

        btn_accept.clicked.connect(on_accept)
        btn_discard.clicked.connect(on_discard)

    def _execute_geometry_commands(self, engine, commands: list):
        for cmd in commands:
            op = cmd.get("cmd")
            # 兼容防幻觉重命名
            if op == "draw_point":
                op = "add_point"
            if op == "draw_circle":
                op = "add_circle"
            if op == "draw_segment":
                op = "add_segment"
            if op == "draw_polygon":
                op = "add_polygon"

            try:
                if op == "add_point":
                    engine.add_point(cmd.get("x", 0), cmd.get("y", 0), cmd.get("name"))
                elif op == "add_circle":
                    engine.add_circle(cmd["center"], cmd.get("radius", 1))
                elif op == "add_polygon":
                    engine.add_polygon(cmd["points"])
                elif op == "add_segment":
                    engine.add_segment(cmd["p1"], cmd["p2"])
            except Exception as e:
                print(f"执行指令 {op} 失败: {e}")

    def on_request_error(self, error_msg: str):
        self.chat_display.append(
            f"<span style='color: #dc2626;'><b>❌ {t('ai_tools.error')}:</b> {error_msg}</span><hr>"
        )
        self.chat_input.setEnabled(True)
        self.send_button.setEnabled(True)
        self.send_button.setText(t("ai_tools.send"))
        if hasattr(self, "breath_anim"):
            self.breath_anim.stop()
            from mathlab.ui.animations import get_opacity_effect

            get_opacity_effect(self.send_button).setOpacity(1.0)

    def _on_state_change(self, state: AIState):
        """让 UI 随 AI 状态实时呼吸"""
        if state in (AIState.IDLE, AIState.FINISHED):
            self.send_button.setText(t("ai_tools.send"))
            self.send_button.setEnabled(True)
            self.action_label.stop_breathing()
            self.action_label.setText("💤 就绪")
            self.action_label.setStyleSheet("color: #555;")

        elif state == AIState.THINKING:
            self.send_button.setText("🤔 思考中...")
            self.send_button.setEnabled(False)
            self.action_label.setText("🤔 正在进行数学推理...")
            self.action_label.setStyleSheet("color: #E67E22;")  # 橙色
            # 💡 触发呼吸灯律动特效！
            self.action_label.start_breathing()

        elif state == AIState.GENERATING:
            self.send_button.setText("✍️ 生成中...")
            self.send_button.setEnabled(False)
            # 停止呼吸，保持高亮常亮
            self.action_label.stop_breathing()
            self.action_label.setText("✍️ 正在生成排版...")
            self.action_label.setStyleSheet("color: #007ACC;")  # 蓝色

        elif state == AIState.EXECUTING_TOOL:
            self.send_button.setText("⚙️ 执行中...")
            self.send_button.setEnabled(False)
            self.action_label.stop_breathing()
            self.action_label.setText("⚙️ 魔法画笔执行中...")
            self.action_label.setStyleSheet("color: #27AE60;")  # 绿色

        elif state == AIState.ERROR:
            self.send_button.setText(t("ai_tools.send"))
            self.send_button.setEnabled(True)
            self.action_label.stop_breathing()
            self.action_label.setText("❌ 连接异常")
            self.action_label.setStyleSheet("color: #E74C3C;")

    def _start_execution_teaching(self):
        """用户点击开始讲解"""
        # 💡 触发平滑折叠动画，优雅退场
        self.plan_box.collapse_silently()

        self.current_step_index = 0
        self.next_step_btn.setVisible(True)
        self._trigger_next_step_lecture()

    def _trigger_next_step_lecture(self):
        if self.current_step_index < len(self.active_plan_steps):
            step_info = self.active_plan_steps[self.current_step_index]
            self.current_step_banner.setText(
                f"🚶‍♂️ 当前: {step_info['title']} ({self.current_step_index+1}/{len(self.active_plan_steps)})"
            )
            self.switch_agent("general")
            self.chat_input.setText(
                f"现在请执行第 {step_info['num']} 步：{step_info['title']}。{step_info.get('description', '')}"
            )
            self.on_send_message()
            self.current_step_index += 1
        else:
            self.current_step_banner.setText("🎉 讲解已完成！")
            self.next_step_btn.setVisible(False)

    def _on_usage_reported(self, prompt_tokens, completion_tokens):
        total = prompt_tokens + completion_tokens

        provider = self.provider_combo.currentData()
        prices_per_1k = {
            AIProvider.OPENAI.value: 0.05,
            AIProvider.CLAUDE.value: 0.1,
            AIProvider.GEMINI.value: 0.02,
            AIProvider.DEEPSEEK.value: 0.01,
            AIProvider.KIMI.value: 0.015,
            AIProvider.MINIMAX.value: 0.01,
            AIProvider.QWEN.value: 0.005,
            AIProvider.ZHIPU.value: 0.005,
            AIProvider.DOUBAO.value: 0.005,
            AIProvider.LOCAL.value: 0.0,
            AIProvider.OLLAMA.value: 0.0,
        }
        price = prices_per_1k.get(provider, 0.01)
        cost_estimate = (total / 1000) * price

        cost_text = f"约 ￥{cost_estimate:.4f}" if cost_estimate > 0 else "免费"

        usage_html = f"""
        <div style='text-align: right; color: #aaa; font-size: 10px; margin-top: 5px;'>
            ⚡ 消耗: {total} Tokens (上下文 {prompt_tokens} + 生成 {completion_tokens}) 
            | {cost_text}
        </div>
        """
        self.chat_display.append(usage_html)
        self.token_label.setText(f"⚡ {total} Tokens")

    def on_ai_generate_request(self, user_prompt):
        from mathlab.core.ai_manager import GeometryAgent
        from mathlab.core.async_workers import TaskWorker

        if not hasattr(self, "ai_agent"):
            main_win = self.window()
            ai_mgr = getattr(main_win, "ai_manager", None)
            self.ai_agent = GeometryAgent(ai_mgr) if ai_mgr else None

        if not self.ai_agent:
            self.chat_display.add_message("ai", "**[错误]** AI Manager 未初始化，无法生成代码。")
            return

        # 1. 开启子线程调用 Agent，防止 UI 卡顿
        worker = TaskWorker(self.ai_agent.solve_problem, user_prompt)

        def on_complete(result):
            if result["status"] != "failed":
                # 自动将代码填入 Monaco 编辑器
                self.code_editor.set_code(result["code"])
                # 在控制台显示结果
                if hasattr(self, "output_area"):
                    self.output_area.append(str(result["result"]))
                elif hasattr(self, "console"):
                    self.console.append(str(result["result"]))

        worker.signals.finished.connect(on_complete)
        QThreadPool.globalInstance().start(worker)
