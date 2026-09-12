import json
import os
import re
import threading

from PySide6.QtCore import QObject, Qt, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget

try:
    from mathlab.core.jupyter_manager import get_jupyter_sandbox
except ImportError:
    get_jupyter_sandbox = None

# 预编译代码围栏正则：AI 流式输出过程中每个 chunk 都会调用一次过滤
_CODE_FENCE_PY_RE = re.compile(r"```python\n?")
_CODE_FENCE_RE = re.compile(r"```\n?")


class EditorBackend(QObject):
    execution_finished = Signal(dict)
    # 增加两个信号：告知主面板错误状态，以便外部处理
    error_occurred = Signal(str, str)
    success_occurred = Signal()
    echarts_data_ready = Signal(dict)

    @Slot(str)
    def sync_code(self, code):
        if hasattr(self.parent_widget, "_cached_code"):
            self.parent_widget._cached_code = code

    def __init__(self, parent_widget):
        super().__init__()
        self.parent_widget = parent_widget

    @Slot(str)
    def execute_code(self, code):
        if not get_jupyter_sandbox:
            self.execution_finished.emit({"status": "error", "traceback": ["Jupyter 沙盒未就绪"]})
            return

        from mathlab.core.async_workers import TaskManager

        def process_result(result):
            if "text" in result:
                result["text"] = self._parse_sandbox_output(result["text"])

            if result.get("status") == "error" or result.get("status") == "timeout":
                error_list = self._parse_traceback(result.get("traceback", []))
                js_cmd = f"setEditorErrors('{json.dumps(error_list)}');"
                self.parent_widget.web_view.page().runJavaScript(js_cmd)

                # 记录崩溃时的代码和错误，并触发悬浮按钮
                error_msg = "\n".join(result.get("traceback", []))
                self.error_occurred.emit(code, error_msg)
            else:
                self.parent_widget.web_view.page().runJavaScript("setEditorErrors('[]');")
                self.success_occurred.emit()

            self.execution_finished.emit(result)

        def process_error(err_msg):
            self.execution_finished.emit({"status": "error", "traceback": [err_msg]})

        TaskManager().submit(
            fn=get_jupyter_sandbox().execute_code,
            on_success=process_result,
            on_error=process_error,
            code=code,
            timeout=10,
        )

    def _parse_traceback(self, traceback_list):
        errors = []
        full_trace = "\n".join(traceback_list)
        match = re.search(r"line (\d+)", full_trace, re.IGNORECASE)
        if match:
            line_num = int(match.group(1))
            clean_error = re.sub(r"\x1b\[[0-9;]*m", "", traceback_list[-1])
            errors.append({"line": line_num, "message": clean_error})
        else:
            errors.append({"line": 1, "message": "执行发生错误或超时"})
        return errors

    def _parse_sandbox_output(self, raw_output):
        """解析沙箱的标准输出"""
        # 查找 IPC 魔法包裹的数据
        echarts_match = re.search(r"__ECHARTS_IPC_START__(.*?)__ECHARTS_IPC_END__", raw_output, re.DOTALL)

        if echarts_match:
            json_str = echarts_match.group(1).strip()
            try:
                chart_options = json.loads(json_str)
                # 通过信号发送给主窗口：有新的图表需要渲染！
                self.echarts_data_ready.emit(chart_options)

                # 在控制台输出中抹去这段丑陋的 JSON
                clean_output = raw_output.replace(
                    echarts_match.group(0),
                    "\n[📈 图表数据已成功发送至 ECharts 渲染引擎]\n",
                )
                return clean_output
            except:
                pass

        return raw_output

    @Slot(int, str, str)
    def request_ghost_text(self, req_id, prefix, suffix):
        """
        接收来自 Monaco 的补全请求。
        开启一个无头线程进行快速推理，确保 GUI 绝对不卡顿。
        """
        if not hasattr(self.parent_widget, "ai_manager") or not self.parent_widget.ai_manager:
            return

        # 使用后台线程避免阻塞 PyQt 事件循环
        threading.Thread(
            target=self._fetch_ghost_text_worker,
            args=(req_id, prefix, suffix),
            daemon=True,
        ).start()

    def _fetch_ghost_text_worker(self, req_id, prefix, suffix):
        """在后台线程中调用大模型获取补全片段"""
        ai_mgr = self.parent_widget.ai_manager
        if not hasattr(ai_mgr, "client") or not ai_mgr.client:
            return

        # FIM (Fill-In-the-Middle) 行业标准 Prompt 结构
        # 针对 DeepSeek 模型的特殊控制符。如果你用的是其他模型，可能需要调整。
        prompt = f"<｜fim\u2581begin｜>{prefix}<｜fim\u2581hole｜>{suffix}<｜fim\u2581end｜>"

        try:
            # 这里直接使用同步请求，配置高 Temperature 获取多样性，限制输出长度追求极速
            response = ai_mgr.client.chat.completions.create(
                model=ai_mgr.current_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,  # 代码补全需要极低的幻觉率
                max_tokens=64,  # 幽灵文本通常只需要补全 1-3 行，限制长度极大提升 TTFB (首字响应时间)
                stream=False,  # 一次性返回结果
            )

            suggestion = response.choices[0].message.content if response.choices else ""

            # 清理可能残留的 markdown 标记
            suggestion = suggestion.replace("```python\n", "").replace("\n```", "").replace("```", "")

            # 构造 JS 回调，将数据灌回 Monaco 渲染成灰色幽灵文本
            escaped_suggestion = json.dumps(suggestion)
            js_cmd = f"receiveGhostText({req_id}, {escaped_suggestion});"

            # 必须使用 QMetaObject.invokeMethod 或直接抛给主线程运行 JS
            from PySide6.QtCore import Q_ARG, QMetaObject, Qt

            QMetaObject.invokeMethod(
                self.parent_widget.web_view.page(),
                "runJavaScript",
                Qt.QueuedConnection,
                Q_ARG(str, js_cmd),
            )

        except Exception as e:
            print(f"Ghost Text Fetch Error: {e}")
            # 如果出错，发送空补全，防止 Monaco 的 Promise 永远挂起
            from PySide6.QtCore import Q_ARG, QMetaObject, Qt

            js_cmd = f"receiveGhostText({req_id}, '');"
            QMetaObject.invokeMethod(
                self.parent_widget.web_view.page(),
                "runJavaScript",
                Qt.QueuedConnection,
                Q_ARG(str, js_cmd),
            )


class AutocompleteTextEdit(QWidget):
    def __init__(self, ai_manager=None, parent=None):
        super().__init__(parent)
        self.ai_manager = ai_manager  # 引入全局 AI 调度中心
        self._last_failed_code = ""
        self._last_error_msg = ""
        self._ai_buffer = ""  # 暂存 AI 流式输出的 buffer
        self._cached_code = ""  # 缓存编辑器内容，以便同步获取
        self._build_ui()

    def toPlainText(self):
        return self._cached_code

    def setPlainText(self, text):
        self._cached_code = text
        escaped_text = json.dumps(text)
        self.web_view.page().runJavaScript(f"if (window.mathEditor) {{ window.mathEditor.setCode({escaped_text}); }}")

    def set_code(self, text):
        self.setPlainText(text)

    def setPlaceholderText(self, text):
        pass

    def setStyleSheet(self, style):
        super().setStyleSheet(style)

    def _build_ui(self):
        # 使用绝对定位来放置悬浮按钮，因此主 Layout 不再管理它
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.web_view = QWebEngineView(self)
        layout.addWidget(self.web_view)

        self.channel = QWebChannel()
        self.backend = EditorBackend(self)
        self.channel.registerObject("backend", self.backend)
        self.web_view.page().setWebChannel(self.channel)

        html_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "resources", "monaco.html"))
        self.web_view.setUrl(QUrl.fromLocalFile(html_path))

        # --- 新增：智能修复悬浮按钮 ---
        self.fix_btn = QPushButton("✨ AI 自动修复", self.web_view)
        self.fix_btn.setStyleSheet("""
            QPushButton {
                background-color: #7B61FF; color: white;
                border-radius: 15px; padding: 5px 15px;
                font-weight: bold; font-family: 'Segoe UI', Arial;
            }
            QPushButton:hover { background-color: #8C75FF; }
        """)
        self.fix_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.fix_btn.hide()  # 初始隐藏
        self.fix_btn.clicked.connect(self._start_ai_fix)

        # 绑定后端信号
        self.backend.error_occurred.connect(self._on_execution_error)
        self.backend.success_occurred.connect(self._on_execution_success)

    def resizeEvent(self, event):
        """保持悬浮按钮始终在编辑器右下角"""
        super().resizeEvent(event)
        btn_width, btn_height = 120, 30
        margin_x, margin_y = 30, 30
        self.fix_btn.setGeometry(
            self.width() - btn_width - margin_x,
            self.height() - btn_height - margin_y,
            btn_width,
            btn_height,
        )

    def _on_execution_error(self, code, error_msg):
        self._last_failed_code = code
        self._last_error_msg = error_msg
        self.fix_btn.show()  # 代码报错，弹出修复按钮

    def _on_execution_success(self):
        self.fix_btn.hide()  # 修复成功或执行成功，隐藏按钮

    def _start_ai_fix(self):
        if not self.ai_manager:
            print("错误：AI Manager 未挂载至编辑器。")
            return

        self.fix_btn.setText("修复中...")
        self.fix_btn.setEnabled(False)
        self._ai_buffer = ""

        # 1. 准备严密的 Prompt
        prompt = f"""你是一个高级 Python 几何/数据处理专家。
以下代码在 Jupyter 运行环境中报错了：

【原始代码】
```python
{self._last_failed_code}
```

【报错日志】
{self._last_error_msg}

请定位问题并给出修复后的完整代码。
规则：只返回最终修复的 Python 代码块，必须用 `python 和 ` 包裹，不要输出任何多余的解释语言或 Markdown 结构。"""

        # 2. 清空编辑器，准备打字机渲染
        self.web_view.page().runJavaScript("clearForAIFix();")

        # 3. 调用 AI 引擎的流式接口
        self.ai_manager.ask(
            user_prompt=prompt,
            on_chunk=self._on_ai_chunk,
            on_finish=self._on_ai_finish,
            on_error=self._on_ai_error,
        )

    def _on_ai_chunk(self, chunk):
        """流式接收并处理 Markdown 拦截"""
        self._ai_buffer += chunk

        # 实时过滤掉 AI 输出的 ```python 和 ``` 标记，实现纯净代码流输入
        display_text = _CODE_FENCE_PY_RE.sub("", self._ai_buffer)
        display_text = _CODE_FENCE_RE.sub("", display_text)

        # 每次清空并全量替换能避免因为正则截断导致的流式乱码问题
        escaped_code = json.dumps(display_text)
        self.web_view.page().runJavaScript(f"window.mathEditor.editor.setValue({escaped_code});")

    def _on_ai_finish(self):
        self.fix_btn.setText("✨ AI 自动修复")
        self.fix_btn.setEnabled(True)
        self.fix_btn.hide()

        # 修复完成后，自动帮你按下 Ctrl+Enter 验证代码
        # JS 层可以派发一个按键事件，或者我们直接在后端再调一次 execute_code
        self.web_view.page().runJavaScript("getEditorContent();", self.backend.execute_code)

    def _on_ai_error(self, err_msg):
        self.fix_btn.setText("✨ AI 自动修复")
        self.fix_btn.setEnabled(True)
        print(f"AI 修复失败: {err_msg}")


class MonacoCodeEditor(QWidget):
    """
    Notebook 单元格使用的轻量级 Monaco 风格代码编辑器。
    基于 QPlainTextEdit 实现，提供多语言切换与执行信号。
    接口与 notebook_panel.py 中 VSCodeStyleCellWidget 的调用约定对齐。
    """

    execute_requested = Signal(str)
    ai_explain_requested = Signal(str, str)
    code_synced = Signal(str)

    def __init__(self, initial_text="", initial_language="mathlab", parent=None):
        super().__init__(parent)
        self._language = initial_language
        self._build_ui()
        if initial_text:
            self._editor.setPlainText(initial_text)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        from PySide6.QtWidgets import QPlainTextEdit

        self._editor = QPlainTextEdit()
        self._editor.setStyleSheet("""
            QPlainTextEdit {
                background-color: #1e1e1e;
                color: #d4d4d4;
                border: 1px solid #3c3c3c;
                font-family: Consolas, 'Courier New', monospace;
                font-size: 13px;
            }
        """)
        self._editor.textChanged.connect(self._on_text_changed)
        layout.addWidget(self._editor)

    def _on_text_changed(self):
        self.code_synced.emit(self._editor.toPlainText())

    def set_language(self, language: str):
        """切换语法高亮语言（mathlab / python / csharp）"""
        self._language = language

    def get_text(self, callback=None):
        """获取编辑器内容，可通过 callback 回传给调用方"""
        text = self._editor.toPlainText()
        if callback:
            callback(text)
        return text

    def set_text(self, text: str):
        self._editor.setPlainText(text)

    def clear(self):
        self._editor.clear()
