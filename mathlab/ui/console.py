from PySide6.QtCore import QEvent, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from mathlab.core.async_workers import TaskManager
from mathlab.utils.i18n_manager import t
from mathlab.utils.markdown_service import MarkdownService
from mathlab.utils.theme_tokens import get_tokens


class PythonConsole(QDockWidget):
    execute_command = Signal(str)
    stop_execution = Signal()

    def __init__(self, parent=None):
        super().__init__(t("console.title"), parent)
        self.setAllowedAreas(Qt.BottomDockWidgetArea)

        self.python_repl = None
        self.task_manager = TaskManager()

        self.widget = QWidget()
        self.layout = QVBoxLayout(self.widget)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        # ── Header row: Execute / Stop  ──────  Python 3 | Kernel: Ready ──
        self.execute_button = QPushButton(t("console.execute"))
        self.stop_button = QPushButton(t("console.stop"))
        self.stop_button.setEnabled(False)

        self.kernel_status_label = QLabel(t("console.kernel_ready"))
        self.kernel_status_label.setObjectName("consoleKernelStatus")
        self.kernel_status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.header_layout = QHBoxLayout()
        self.header_layout.setContentsMargins(6, 4, 8, 4)
        self.header_layout.setSpacing(6)
        self.header_layout.addWidget(self.execute_button)
        self.header_layout.addWidget(self.stop_button)
        self.header_layout.addStretch()
        self.header_layout.addWidget(self.kernel_status_label)
        self.layout.addLayout(self.header_layout)

        self.output_area = QTextBrowser()
        self.output_area.setOpenLinks(False)
        self.output_area.anchorClicked.connect(self.on_anchor_clicked)
        self.output_area.setReadOnly(True)
        self.output_area.setFont(QFont("Consolas", 12))
        self.output_area.setObjectName("console_output")

        self.input_line = QLineEdit()
        self.input_line.setFont(QFont("Consolas", 12))
        self.input_line.setPlaceholderText(t("console.placeholder"))
        self.input_line.setObjectName("console_input")

        self.layout.addWidget(self.output_area)
        self.layout.addWidget(self.input_line)

        self.setWidget(self.widget)

        self.history = []
        self.history_index = -1

        self.input_line.returnPressed.connect(self.on_execute)
        self.execute_button.clicked.connect(self.on_execute)
        self.stop_button.clicked.connect(self.on_stop)

        self.input_line.installEventFilter(self)

        self.append_output(t("console.welcome") + "\n")
        self.append_output(t("console.help_hint") + "\n")
        self.append_prompt()

    def eventFilter(self, obj, event):
        if obj == self.input_line:
            try:
                if event.type() == QEvent.KeyPress:
                    if event.key() == Qt.Key_Up:
                        self.navigate_history(-1)
                        return True
                    elif event.key() == Qt.Key_Down:
                        self.navigate_history(1)
                        return True
                    elif event.key() == Qt.Key_Tab:
                        self.complete_command()
                        return True
            except Exception as e:
                print(f"Error in console eventFilter: {type(e).__name__}: {e}")
        return False

    def append_output(self, text):
        cursor = self.output_area.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(text)
        self.output_area.setTextCursor(cursor)
        self.output_area.ensureCursorVisible()

    def append_prompt(self):
        self.append_output(">>> ")

    def append_agent_thought(self, thought_text):
        """渲染 AI 的思考流 (紫色系)，支持 Markdown + LaTeX"""
        tok = get_tokens()
        md_svc = MarkdownService.get_instance()
        rendered = md_svc.render_for_text_browser(
            thought_text,
            document=self.output_area.document(),
        )
        thought_lbl = t("console.agent_thought")
        html = f"""
        <div style='margin: 4px 0; font-family: "Consolas", monospace; font-size: 13px;'>
            <span style='color: {tok["obj.polygon"]}; font-weight: bold;'>{thought_lbl}</span>
            <span style='color: {tok["fg.primary"]};'> {rendered}</span>
        </div>
        """
        self.output_area.append(html)
        self.output_area.verticalScrollBar().setValue(self.output_area.verticalScrollBar().maximum())

    def append_agent_observation(self, obs_text, is_error=False):
        """渲染本地沙箱的运行反馈 (成功绿 / 报错红)，支持 Markdown"""
        tok = get_tokens()
        color = tok["danger"] if is_error else tok["success"]
        icon = "❌" if is_error else "✅"
        bg_color = tok["bg.inset"]

        md_svc = MarkdownService.get_instance()
        rendered = md_svc.render_for_text_browser(
            obs_text,
            document=self.output_area.document(),
        )
        fb_lbl = t("console.sandbox_feedback")
        html = f"""
        <div style='margin: 4px 0; padding: 6px; background-color: {bg_color}; border-left: 3px solid {color}; font-family: "Consolas", monospace; font-size: 13px;'>
            <span style='color: {color}; font-weight: bold;'>{icon} {fb_lbl}</span><br>
            <span style='color: {tok["fg.secondary"]};'>{rendered}</span>
        </div>
        """
        self.output_area.append(html)
        self.output_area.verticalScrollBar().setValue(self.output_area.verticalScrollBar().maximum())

    def on_execute(self):
        command = self.input_line.text().strip()
        if not command:
            return

        self.history.append(command)
        self.history_index = len(self.history)

        self.append_output(command + "\n")
        self.input_line.clear()

        self.execute_button.setEnabled(False)
        self.stop_button.setEnabled(True)

        self.execute_command.emit(command)

    def on_stop(self):
        # Guard: 如果 stop_button 已禁用，说明没有命令在执行，直接返回
        if not self.stop_button.isEnabled():
            return

        self.stop_execution.emit()
        self.append_output("\n" + t("console.execution_stopped") + "\n")
        self.append_prompt()

        self.execute_button.setEnabled(True)
        self.stop_button.setEnabled(False)

    def display_result(self, result):
        if result.get("output"):
            self.append_output(result["output"])

        if result.get("error"):
            self.display_system_message(result["error"], level="error")

        if not result.get("more", False):
            self.append_prompt()

        self.execute_button.setEnabled(True)
        self.stop_button.setEnabled(False)

    def navigate_history(self, direction):
        if not self.history:
            return

        self.history_index += direction

        if self.history_index < 0:
            self.history_index = 0
        elif self.history_index >= len(self.history):
            self.history_index = len(self.history)
            self.input_line.clear()
            return

        self.input_line.setText(self.history[self.history_index])

    def complete_command(self):
        current_text = self.input_line.text()
        if not current_text:
            return

        cursor_pos = self.input_line.cursorPosition()
        line = 1
        column = cursor_pos

        def process_completions(jedi_completions):
            if self.input_line.text() != current_text:
                return

            if jedi_completions:
                names = [c["name"] for c in jedi_completions]

                if len(names) == 1:
                    last_word_start = current_text.rfind(" ", 0, cursor_pos) + 1
                    prefix = current_text[last_word_start:cursor_pos]
                    completion = names[0]
                    if completion.startswith(prefix):
                        new_text = current_text[:last_word_start] + completion + current_text[cursor_pos:]
                        self.input_line.setText(new_text)
                        self.input_line.setCursorPosition(last_word_start + len(completion))
                elif len(names) > 1:
                    self.append_output("\n" + "\n".join(names) + "\n")
                    self.append_prompt()
                    self.input_line.setText(current_text)
            else:
                words = current_text.split()
                if words:
                    last_word = words[-1]
                    completions = self.get_completions(last_word)

                    if len(completions) == 1:
                        self.input_line.setText(current_text[: -len(last_word)] + completions[0])
                    elif len(completions) > 1:
                        self.append_output("\n".join(completions) + "\n")
                        self.append_prompt()
                        self.input_line.setText(current_text)

        def on_error(err_msg):
            self.display_system_message(f"{t('console.complete_error')} {err_msg}", level="error")

        if self.python_repl:
            self.task_manager.submit(
                fn=self.python_repl.get_completions,
                on_success=process_completions,
                on_error=on_error,
                code_str=current_text,
                line=line,
                column=column,
            )
        else:
            process_completions([])

    def set_python_repl(self, repl):
        self.python_repl = repl

    def get_completions(self, prefix):
        common_commands = [
            "draw_point",
            "draw_segment",
            "draw_circle",
            "clear_canvas",
            "solve",
            "simplify",
            "integrate",
            "differentiate",
            "limit",
        ]

        return [cmd for cmd in common_commands if cmd.startswith(prefix)]

    def get_jedi_completions(self, code_str: str, line: int, column: int):
        if self.python_repl:
            return self.python_repl.get_completions(code_str, line, column)
        return []

    def retranslate_ui(self):
        self.setWindowTitle(t("console.title"))
        self.input_line.setPlaceholderText(t("console.placeholder"))
        self.execute_button.setText(t("console.execute"))
        self.stop_button.setText(t("console.stop"))
        self.kernel_status_label.setText(t("console.kernel_ready"))

    def clear(self):
        self.output_area.clear()
        self.append_output(t("console.welcome") + "\n")
        self.append_prompt()

    # ──────────────────────────────────────────────────────────────
    #  命令面板 API
    # ──────────────────────────────────────────────────────────────

    def inject_variable(self, var_name: str, value_expr: str) -> None:
        """向 REPL 静默注入一个变量赋值 (异步改造版)"""
        script = f"{var_name} = {value_expr}"

        if self.python_repl is not None:
            # 1. 定义成功后的 UI 更新回调
            def on_success(result):
                if isinstance(result, dict) and result.get("error"):
                    self.display_system_message(
                        f"{t('console.inject_failed')} {var_name}: {result['error']}", level="error"
                    )
                else:
                    self.display_system_message(f"{t('console.inject_async_ok')}: {var_name} = {value_expr}")

            # 2. 定义失败后的 UI 更新回调
            def on_error(err_msg):
                self.display_system_message(f"{t('console.inject_error')} {err_msg}", level="error")

            # 3. 将阻塞的 execute 踢给后台线程池！主界面瞬间解放。
            self.task_manager.submit(
                fn=self.python_repl.execute,
                on_success=on_success,
                on_error=on_error,
                code=script,  # 传递给 execute 的参数
            )
        else:
            self.display_system_message(f"{t('console.inject_var_hint')}: {var_name} = {value_expr}")

    def insert_text_at_cursor(self, text: str) -> None:
        """将文本插入到输入框当前光标位置，焦点自动移到输入框。

        适合命令面板插入常用公式或函数模板::

            console.insert_text_at_cursor('integrate(x**2, x)')
        """
        self.input_line.insert(text)
        self.input_line.setFocus()

    def display_system_message(self, message: str, level: str = "info") -> None:
        """向终端显示系统信息，支持错误 AI 拦截"""
        tok = get_tokens()
        color = {
            "info": tok["fg.secondary"],
            "warn": tok["warning"],
            "error": tok["danger"],
        }.get(level, tok["fg.secondary"])

        if level == "error":
            safe_msg = message.replace("<", "&lt;").replace(">", "&gt;")
            safe_msg = safe_msg.replace("\n", "<br>")
            html_msg = f'<span style="color: {color};">{safe_msg}</span>'

            # 🚨 核心魔法：如果检测到 Python 异常堆栈，自动附加 AI 诊断链接！
            if "Traceback" in message or "Error:" in message or "Exception:" in message:
                import urllib.parse

                # 将错误信息进行 URL 编码，隐藏在链接中
                encoded_err = urllib.parse.quote(message)
                ask_ai_lbl = t("console.ask_ai_fix")
                html_msg += (
                    f'<br><br><a href="ask_ai:{encoded_err}" '
                    f'style="color: {tok["success"]}; text-decoration: none; font-weight: bold;">'
                    f"{ask_ai_lbl}</a><br>"
                )

            self.output_area.append(html_msg)
            self.output_area.append("<br>")
        else:
            safe_msg = message.replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
            self.output_area.append(f'<span style="color: {color};">{safe_msg}</span><br>')
            self.output_area.append("<br>")

    def on_anchor_clicked(self, url):
        """处理控制台内的超链接点击事件"""
        if url.scheme() == "ask_ai":
            import urllib.parse

            # 1. 解码出错误信息
            error_trace = urllib.parse.unquote(url.path())

            # 2. 调出 AI 面板
            main_win = self.window()
            if hasattr(main_win, "ai_tools_panel"):
                ai_panel = main_win.ai_tools_panel
                ai_panel.show()
                ai_panel.raise_()

                # 3. 自动帮用户填入 Prompt 并发送
                prompt_prefix = t("console.ai_fix_prompt")
                prompt = f"{prompt_prefix}\n```python\n{error_trace}\n```"
                ai_panel.chat_input.setText(prompt)
                ai_panel.on_send_message()
