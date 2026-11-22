from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from mathlab.core.ai_manager import DRAW_TOOL_SCHEMA


class QuizCardWidget(QWidget):
    """
    动态生成的交互式测验卡片
    """

    def __init__(self, quiz_data: dict, ai_manager, parent=None):
        super().__init__(parent)
        self.quiz_data = quiz_data
        self.ai_manager = ai_manager
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # 卡片样式由 styles.qss `QuizCardWidget` 规则提供（三主题自适应）
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # 1. 知识点标签
        kp_label = QLabel(f"🧠 考点：{self.quiz_data.get('knowledge_point', '综合应用')}")
        kp_label.setObjectName("knowledge")
        layout.addWidget(kp_label)

        # 2. 题目正文 (支持简单的富文本或桥接 LaTeX 渲染器)
        q_label = QLabel(self.quiz_data.get("question_text", ""))
        q_label.setObjectName("question")
        q_label.setWordWrap(True)
        layout.addWidget(q_label)

        # 3. 动态作答区
        self.answer_group = QButtonGroup(self)
        self.input_field = None

        if self.quiz_data.get("question_type") == "multiple_choice":
            options = self.quiz_data.get("options", [])
            for i, opt_text in enumerate(options):
                # 生成 A, B, C, D 选项
                prefix = chr(65 + i)
                rb = QRadioButton(f"{prefix}. {opt_text}")
                self.answer_group.addButton(rb, i)
                layout.addWidget(rb)
        else:
            self.input_field = QLineEdit()
            self.input_field.setPlaceholderText("请输入你的计算结果...")
            layout.addWidget(self.input_field)

        # 4. 提交按钮
        self.submit_btn = QPushButton("提交答案")
        self.submit_btn.setObjectName("submit")
        self.submit_btn.clicked.connect(self.check_answer)
        layout.addWidget(self.submit_btn)

    def check_answer(self):
        user_answer = ""
        if self.quiz_data.get("question_type") == "multiple_choice":
            checked_id = self.answer_group.checkedId()
            if checked_id == -1:
                return
            user_answer = chr(65 + checked_id)
        else:
            if not self.input_field.text().strip():
                return
            user_answer = self.input_field.text().strip()

        correct_answer = self.quiz_data.get("correct_answer", "")

        # 禁用操作，防止重复提交
        self.submit_btn.setEnabled(False)
        if self.input_field:
            self.input_field.setEnabled(False)
        for rb in self.answer_group.buttons():
            rb.setEnabled(False)

        if user_answer.lower() == correct_answer.lower():
            self.submit_btn.setText("✅ 回答正确！")
            self.submit_btn.setProperty("result", "correct")
        else:
            self.submit_btn.setText("❌ 回答错误，正在呼叫 AI 讲解...")
            self.submit_btn.setProperty("result", "wrong")
            # 触发 AI 错题解析机制
            self.trigger_visual_explanation(user_answer)
        self.submit_btn.style().unpolish(self.submit_btn)
        self.submit_btn.style().polish(self.submit_btn)

    def trigger_visual_explanation(self, wrong_answer):
        """将错题上下文发送给 AI，要求它讲解并在画布上作图"""
        prompt = f"""
我在做这道题时答错了：
【题目】：{self.quiz_data.get('question_text')}
【我的答案】：{wrong_answer}
【正确答案】：{self.quiz_data.get('correct_answer')}

请帮我分析我为什么会做错（薄弱点在哪里）。
为了让我更直观地理解，**请务必调用画图工具（execute_geometry_draw）**，在我的画板上画出一个辅助图形或反例来配合你的讲解。
"""
        # 将请求扔给主界面的 AI 侧边栏进行处理
        self.ai_manager.ask(
            user_prompt=prompt,
            system_prompt="你是一个极度耐心的数学私教。请指出学生的认知误区，并利用画板视觉化地教授正确概念。",
            tools=[DRAW_TOOL_SCHEMA],
        )
