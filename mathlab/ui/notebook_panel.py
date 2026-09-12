import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDockWidget,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from mathlab.core.notebook import CellType, MathLabNotebook
from mathlab.ui.code_editor import MonacoCodeEditor
from mathlab.ui.markdown_cell import MarkdownCellWidget
from mathlab.utils.i18n_manager import t
from mathlab.utils.markdown_service import MarkdownService


class VSCodeStyleCellWidget(QFrame):
    execute_requested = Signal(str)
    cell_ai_explain_requested = Signal(str, str)
    language_changed = Signal(str)
    code_synced = Signal(str)

    def __init__(self, cell_id, cell_type="code", content="", language="mathlab", parent=None):
        super().__init__(parent)
        self.cell_id = cell_id
        self.cell_type = cell_type

        # UI Styling
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet("""
            VSCodeStyleCellWidget {
                background-color: #252526;
                border: 1px solid #3c3c3c;
                border-radius: 4px;
                margin-bottom: 10px;
            }
            QPushButton {
                background-color: #0e639c;
                color: white;
                border: none;
                padding: 4px 10px;
                border-radius: 2px;
            }
            QPushButton:hover {
                background-color: #1177bb;
            }
        """)

        self.init_ui(content, language)

    def init_ui(self, initial_content, initial_language):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(5, 5, 5, 5)

        # Toolbar
        self.toolbar_container = QWidget()
        toolbar_layout = QHBoxLayout(self.toolbar_container)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)

        type_label = QLabel(f"[{self.cell_type.upper()}]")
        type_label.setStyleSheet("color: #cccccc;")
        toolbar_layout.addWidget(type_label)

        if self.cell_type == "code":
            self.lang_selector = QComboBox()
            self.lang_selector.addItems(["MathLab", "Python", "C# (C Sharp)"])
            if initial_language == "csharp":
                self.lang_selector.setCurrentText("C# (C Sharp)")
            elif initial_language == "python":
                self.lang_selector.setCurrentText("Python")
            else:
                self.lang_selector.setCurrentText("MathLab")
            self.lang_selector.setStyleSheet("background-color: #3c3c3c; color: white; border: none; padding: 2px;")
            self.lang_selector.currentTextChanged.connect(self.on_language_changed)
            toolbar_layout.addWidget(self.lang_selector)

        toolbar_layout.addStretch()

        self.run_btn = QPushButton(t("notebook.run"))
        self.run_btn.clicked.connect(self.on_run_clicked)
        toolbar_layout.addWidget(self.run_btn)

        # Editor
        if self.cell_type == "code":
            self.input_editor = MonacoCodeEditor(initial_text=initial_content, initial_language=initial_language)
            self.input_editor.setFixedHeight(150)
            self.input_editor.execute_requested.connect(self.on_monaco_run)
            self.input_editor.ai_explain_requested.connect(self.cell_ai_explain_requested.emit)
            self.input_editor.code_synced.connect(self.code_synced.emit)
        else:
            self.input_editor = QTextEdit(initial_content)
            self.input_editor.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4; border: 1px solid #3c3c3c;")
            self.input_editor.setFixedHeight(100)
            self.input_editor.textChanged.connect(lambda: self.code_synced.emit(self.input_editor.toPlainText()))

        # Sliders container
        self.sliders_container = QFrame()
        self.sliders_layout = QVBoxLayout(self.sliders_container)
        self.sliders_layout.setContentsMargins(0, 0, 0, 0)
        self.sliders_dict = {}

        # Output browser
        self.output_browser = QTextBrowser()
        self.output_browser.setStyleSheet(
            "background-color: #1e1e1e; color: #d4d4d4; border: none; font-family: Consolas;"
        )
        self.output_browser.hide()

        self.main_layout.addWidget(self.toolbar_container)
        self.main_layout.addWidget(self.input_editor)
        self.main_layout.addWidget(self.sliders_container)
        self.main_layout.addWidget(self.output_browser)

    def on_language_changed(self, text):
        if "C#" in text:
            self.input_editor.set_language("csharp")
            self.language_changed.emit("csharp")
        elif "Python" in text:
            self.input_editor.set_language("python")
            self.language_changed.emit("python")
        else:
            self.input_editor.set_language("mathlab")
            self.language_changed.emit("mathlab")

    def on_monaco_run(self, code: str):
        self.execute_requested.emit(code)

    def on_run_clicked(self):
        if self.cell_type == "code":
            self.input_editor.get_text(self.execute_requested.emit)
        else:
            self.execute_requested.emit(self.input_editor.toPlainText())

    def set_output(self, text):
        if not text:
            self.output_browser.hide()
        else:
            self.output_browser.setHtml(text)
            self.output_browser.show()

    def retranslate_ui(self):
        if hasattr(self, "run_btn"):
            self.run_btn.setText(t("notebook.run"))


from mathlab.ui.interactive_widgets import MathSlider


class NotebookPanel(QWidget):
    """
    交互式笔记本的宏观容器
    负责管理多个 Cell 的 UI 排列，并与底层的 MathLabNotebook 保持数据同步
    """

    # 笔记本级别的 AI 解释请求信号 (cell_id, code)
    ai_explain_requested = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.backend = MathLabNotebook()
        self.ui_cells = {}
        self.current_executing_cell_id = None

        # 监听内核发出的滑块请求（只连接一次，避免语言切换时重复连接）
        self.backend.kernel.signals.slider_requested.connect(self.handle_slider_requested)

        # 构建 UI 并创建首个单元格。
        # 此前 UI 构建依赖 retranslate_ui() 触发，导致：
        # 1) 面板在首次语言切换前一直是空白；2) 首次调用时访问尚未创建的控件直接报错。
        self.init_ui()
        self.add_new_cell(CellType.CODE)

    def retranslate_ui(self):
        """仅更新界面文案，不重建 UI、不新增单元格。"""
        self.btn_save.setText(f"💾 {t('notebook.save') or 'Save'}")
        self.btn_load.setText(f"📂 {t('notebook.open') or 'Open'}")
        self.btn_add_code.setText(t("notebook.add_code"))
        self.btn_add_markdown.setText(t("notebook.add_markdown"))
        self.btn_run_all.setText(t("notebook.run_all"))
        self.btn_clear_all.setText(t("notebook.clear_all"))
        for ui_cell in self.ui_cells.values():
            if hasattr(ui_cell, "retranslate_ui"):
                ui_cell.retranslate_ui()

    def init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # ── 1. 顶部全局工具栏 ──
        self.toolbar = QFrame()
        self.toolbar.setFixedHeight(40)
        self.toolbar.setStyleSheet("background-color: #252526; border-bottom: 1px solid #333;")
        toolbar_layout = QHBoxLayout(self.toolbar)
        toolbar_layout.setContentsMargins(10, 0, 10, 0)

        self.btn_save = self._create_toolbar_btn(f"💾 {t('notebook.save') or 'Save'}", "#d7ba7d")
        self.btn_load = self._create_toolbar_btn(f"📂 {t('notebook.open') or 'Open'}", "#d7ba7d")
        self.btn_add_code = self._create_toolbar_btn(t("notebook.add_code"), "#007acc")
        self.btn_add_markdown = self._create_toolbar_btn(t("notebook.add_markdown"), "#608b4e")
        self.btn_run_all = self._create_toolbar_btn(t("notebook.run_all"), "#c586c0")
        self.btn_clear_all = self._create_toolbar_btn(t("notebook.clear_all"), "#858585")

        toolbar_layout.addWidget(self.btn_load)
        toolbar_layout.addWidget(self.btn_save)
        toolbar_layout.addWidget(self.btn_add_code)
        toolbar_layout.addWidget(self.btn_add_markdown)
        toolbar_layout.addSpacerItem(QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        toolbar_layout.addWidget(self.btn_run_all)
        toolbar_layout.addWidget(self.btn_clear_all)

        self.btn_save.clicked.connect(self.save_notebook)
        self.btn_load.clicked.connect(self.load_notebook)
        self.btn_add_code.clicked.connect(lambda: self.add_new_cell(CellType.CODE))
        self.btn_add_markdown.clicked.connect(lambda: self.add_new_cell(CellType.MARKDOWN))
        self.btn_run_all.clicked.connect(self.run_all_cells)
        self.btn_clear_all.clicked.connect(self.clear_all_outputs)

        # ── 2. 可滚动的画布区域 ──
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("QScrollArea { border: none; background-color: #1e1e1e; }")

        self.canvas_widget = QWidget()
        self.canvas_widget.setStyleSheet("background-color: #1e1e1e;")
        self.canvas_layout = QVBoxLayout(self.canvas_widget)
        self.canvas_layout.setContentsMargins(40, 20, 40, 40)
        self.canvas_layout.setSpacing(15)
        self.canvas_layout.addStretch(1)

        self.scroll_area.setWidget(self.canvas_widget)

        self.main_layout.addWidget(self.toolbar)
        self.main_layout.addWidget(self.scroll_area)

    def _create_toolbar_btn(self, text, hover_color):
        btn = QPushButton(text)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent; color: #cccccc; border: none; padding: 6px 12px; font-weight: bold;
            }}
            QPushButton:hover {{ background-color: #333333; color: {hover_color}; border-radius: 4px; }}
        """)
        btn.setCursor(Qt.PointingHandCursor)
        return btn

    def add_new_cell(self, cell_type: CellType):
        """用户点击 '+' 时新增格子"""
        backend_cell = self.backend.add_cell(cell_type, "")
        if cell_type == CellType.MARKDOWN:
            backend_cell.content = "### 奇异值分解定理\n设 $A$ 是一个 $m \\times n$ 实矩阵，则存在正交矩阵 $U$ 和 $V$，使得：\n$$ A = U \\Sigma V^T $$"
        self._create_ui_from_backend(backend_cell)

    def _create_ui_from_backend(self, backend_cell):
        """
        统一的 UI 工厂方法：无论是新建还是从文件加载，都走这里
        """
        # 创建 UI
        if backend_cell.type == CellType.CODE:
            ui_cell = VSCodeStyleCellWidget(backend_cell.id, "code", backend_cell.content, backend_cell.language)

            # 监听执行信号
            ui_cell.execute_requested.connect(lambda code, cid=backend_cell.id: self.execute_single_cell(cid, code))

            # [BUG修复] 恢复对 code_synced 的连接，修复直接保存导致代码丢失的问题
            ui_cell.code_synced.connect(lambda new_code, cid=backend_cell.id: self._sync_backend_content(cid, new_code))
            ui_cell.language_changed.connect(lambda lang, cid=backend_cell.id: self._sync_backend_language(cid, lang))
            ui_cell.cell_ai_explain_requested.connect(self.ai_explain_requested.emit)

        else:  # Markdown
            ui_cell = MarkdownCellWidget(backend_cell.id, backend_cell.content)
            ui_cell.btn_delete.clicked.connect(lambda _, cid=backend_cell.id: self.delete_cell(cid))
            ui_cell.code_synced.connect(lambda new_code, cid=backend_cell.id: self._sync_backend_content(cid, new_code))

            # 为了能在 load 的时候自动显示公式而不是显示源码，你可以直接调用渲染
            if backend_cell.content:
                ui_cell.switch_to_view()

        self.ui_cells[backend_cell.id] = ui_cell
        self.canvas_layout.insertWidget(self.canvas_layout.count() - 1, ui_cell)

    def _sync_backend_content(self, cell_id: str, new_code: str):
        """心跳同步回调"""
        for cell in self.backend.cells:
            if cell.id == cell_id:
                cell.content = new_code
                break

    def _sync_backend_language(self, cell_id: str, new_lang: str):
        for cell in self.backend.cells:
            if cell.id == cell_id:
                cell.language = new_lang
                break

    def delete_cell(self, cell_id: str):
        if cell_id in self.ui_cells:
            ui_cell = self.ui_cells.pop(cell_id)
            self.canvas_layout.removeWidget(ui_cell)
            ui_cell.deleteLater()
        self.backend.remove_cell(cell_id)

    def on_cell_execute(self, cell_id, code):
        self.execute_single_cell(cell_id, code, is_silent=False)

    def execute_single_cell(self, cell_id: str, current_code: str, is_silent=False):
        """执行单元格，is_silent=True表示是由滑块拖动触发的，不需要获取焦点"""
        self.current_executing_cell_id = cell_id

        # 同步前台代码到后台
        cell = next((c for c in self.backend.cells if c.id == cell_id), None)
        if cell is None:
            return
        if not is_silent:
            cell.content = current_code

        # 后台执行
        self.backend.execute_cell(cell_id)

        # 渲染输出
        self._render_cell_output(cell_id)

    def handle_slider_requested(self, data: dict):
        """收到底层的滑块请求，在对应的 UI 单元格里画出来"""
        if not self.current_executing_cell_id:
            return
        ui_cell = self.ui_cells.get(self.current_executing_cell_id)
        if not ui_cell:
            return

        name = data["name"]
        # 如果滑块还没创建，就创建它
        if name not in ui_cell.sliders_dict:
            slider = MathSlider(name, data["min"], data["max"], data["val"])
            ui_cell.sliders_layout.addWidget(slider)
            ui_cell.sliders_dict[name] = slider

            # 当滑块拖动时，更新变量并静默重跑代码
            slider.value_changed.connect(
                lambda var_name, new_val, cid=self.current_executing_cell_id: self.on_slider_dragged(
                    cid, var_name, new_val
                )
            )

    def on_slider_dragged(self, cell_id: str, var_name: str, new_val: float):
        """处理滑块拖动事件"""
        # 1. 强行修改内核环境中的变量值
        self.backend.kernel.env[var_name] = new_val

        # 2. 从后端拿到当前单元格的最新代码
        cell = next((c for c in self.backend.cells if c.id == cell_id), None)
        if cell is None:
            return

        # 3. 触发静默执行！
        self.execute_single_cell(cell_id, cell.content, is_silent=True)

    def run_all_cells(self):
        # Monaco editor async fetch omitted for brevity, just execute backend cells directly
        self.backend.execute_all()
        for backend_cell in self.backend.cells:
            self._render_cell_output(backend_cell.id)

    def clear_all_outputs(self):
        for ui_cell in self.ui_cells.values():
            if ui_cell.cell_type == "code":
                ui_cell.set_output("")

    # ──────────────────────────────────────────────────────────
    # 核心持久化逻辑
    # ──────────────────────────────────────────────────────────

    def save_notebook(self):
        """将当前笔记本保存到磁盘"""
        # 1. 弹出保存对话框
        import os

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "保存 MathLab 笔记本",
            "",  # 默认路径
            "MathLab Notebook (*.mlnb);;所有文件 (*.*)",
        )
        if not file_path:
            return  # 用户取消了保存

        # 2. 自动补全后缀名
        if not file_path.endswith(".mlnb"):
            file_path += ".mlnb"

        # 3. 调用我们在 core/notebook.py 里写好的保存逻辑
        try:
            # 注意：因为有了心跳同步，此时 backend 里的 content 绝对是最新的
            self.backend.save_to_file(file_path)
            # 在状态栏或弹窗提示成功
            QMessageBox.information(self, "保存成功", f"笔记本已安全保存至:\n{os.path.basename(file_path)}")
        except Exception as e:
            QMessageBox.critical(self, "保存失败", f"无法写入文件:\n{str(e)}")

    def load_notebook(self):
        """从磁盘读取并重建笔记本现场"""
        # 1. 弹出打开对话框
        file_path, _ = QFileDialog.getOpenFileName(
            self, "打开 MathLab 笔记本", "", "MathLab Notebook (*.mlnb);;所有文件 (*.*)"
        )
        if not file_path:
            return

        try:
            # 2. 从文件解析 JSON 到内存 (调用 core 的逻辑)
            self.backend.load_from_file(file_path)

            # 3. 核弹级清理：把当前 UI 上的所有格子炸掉
            for ui_cell in self.ui_cells.values():
                self.canvas_layout.removeWidget(ui_cell)
                ui_cell.deleteLater()
            self.ui_cells.clear()

            # 4. 根据读入的 backend_cell 数据重建整个 UI
            for backend_cell in self.backend.cells:
                self._create_ui_from_backend(backend_cell)

        except Exception as e:
            QMessageBox.critical(self, "加载失败", f"文件解析错误:\n{str(e)}")

    def _render_cell_output(self, cell_id: str):
        backend_cell = next((c for c in self.backend.cells if c.id == cell_id), None)
        ui_cell = self.ui_cells.get(cell_id)

        if not backend_cell or not ui_cell:
            return

        if not backend_cell.outputs:
            ui_cell.output_browser.hide()
            return

        # 获取 MarkdownService 单例
        md_svc = MarkdownService.get_instance()

        html_output = ""
        for out in backend_cell.outputs:
            if out["type"] == "error":
                html_output += f"<div style='color: #f14c4c; padding: 5px;'><b>错误:</b> {out['data']}</div>"
            elif out["type"] == "result":
                html_output += self._format_data_to_html(out["data"])
            elif out["type"] == "markdown":
                # 使用混合架构渲染：Python 引擎处理 Markdown + LaTeX→PNG
                html_output += md_svc.render_for_text_browser(
                    out["data"],
                    document=ui_cell.output_browser.document(),
                )

        exec_count = backend_cell.execution_count or "*"
        prefix = f"<div style='color: #569cd6; font-size: 10px; margin-bottom: 4px;'>Out [{exec_count}]:</div>"

        ui_cell.set_output(prefix + html_output)
        ui_cell.output_browser.show()

    def _format_data_to_html(self, result) -> str:
        if isinstance(result, np.ndarray):
            return f"<span style='color: #4EC9B0;'>[NumPy Array Shape: {result.shape}]</span><br>"
        elif isinstance(result, dict):
            return "<span style='color: #9cdcfe;'>[Dictionary Result]</span><br>"
        return f"<span style='color: #b5cea8;'>{result}</span><br>"
