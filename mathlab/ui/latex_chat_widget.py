import json
import os

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView


class LatexChatWidget(QWebEngineView):
    """
    基于 WebEngine 的工业级 Markdown + LaTeX 渲染器
    """

    # 流式渲染节流窗口（毫秒）：窗口内到达的碎片合并为一次重绘
    _STREAM_RENDER_INTERVAL_MS = 60

    def __init__(self, parent=None):
        super().__init__(parent)

        # 加载刚才写好的 HTML 引擎
        html_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "resources", "chat_renderer.html"))
        self.setUrl(QUrl.fromLocalFile(html_path))

        # 维护一份纯净的聊天记录结构，用于整体重绘防撕裂
        self.chat_history = []
        self._current_streaming_content = ""

        # 流式渲染节流：每个 token 都会触发 update_streaming_chunk，
        # 而每次重绘都会把全部历史重新拼接推给 WebEngine，长回答下开销呈 O(n²)。
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(self._STREAM_RENDER_INTERVAL_MS)
        self._render_timer.timeout.connect(self._on_stream_render_tick)
        self._render_dirty = False

    def _stop_stream_throttle(self):
        self._render_timer.stop()
        self._render_dirty = False

    def add_message(self, role: str, content: str):
        """添加一条完整的历史消息"""
        self._stop_stream_throttle()
        self.chat_history.append({"role": role, "content": content})
        self._current_streaming_content = ""
        self._render_to_webview()

    def append(self, html: str):
        """兼容 QTextEdit 风格的 append：追加一段调用方已渲染好的 HTML 片段。

        AI 工具面板中的系统提示、费用统计等都通过 append 推送，
        与 add_message 的区别是内容不再经过 Markdown 解析。
        """
        self._stop_stream_throttle()
        self.chat_history.append({"role": "ai", "content": html, "is_html": True})
        self._current_streaming_content = ""
        self._render_to_webview()

    def update_streaming_chunk(self, chunk: str):
        """
        处理流式大模型的碎片
        【架构黑魔法】：由于网络碎片可能把 $$ 切成两半，导致渲染崩溃。
        我们的策略是：在 Python 端拼装完整 Markdown，然后让前端整体进行重绘。
        得益于 KaTeX 的极速性能，这种“整体重绘”在肉眼看来就是极其平滑的打字机效果。

        性能：按 _STREAM_RENDER_INTERVAL_MS 节流，窗口内碎片合并渲染，
        避免每个 token 都触发一次全量重绘。
        """
        self._current_streaming_content += chunk

        if self._render_timer.isActive():
            # 节流窗口内：仅标记有新内容，由窗口结束时的定时器统一渲染
            self._render_dirty = True
            return

        # 窗口空闲：立即渲染一次保证首个碎片快速可见，并开启新的节流窗口
        self._render_to_webview()
        self._render_timer.start()

    def _on_stream_render_tick(self):
        if self._render_dirty:
            self._render_dirty = False
            self._render_to_webview()

    def finalize_streaming_message(self):
        """流式输出结束，将当前内容固化到历史记录中"""
        self._stop_stream_throttle()
        if self._current_streaming_content:
            self.add_message("ai", self._current_streaming_content)

    def clear_chat(self):
        self._stop_stream_throttle()
        self.chat_history.clear()
        self._current_streaming_content = ""
        self._render_to_webview()

    def _render_to_webview(self):
        """将内部历史记录转换为 HTML 并推送到 JS 引擎"""
        html_parts = []

        # 1. 渲染历史固化消息
        for msg in self.chat_history:
            if msg["role"] == "user":
                html_parts.append(
                    f"<div class='message-container role-user'>你：<br>{self._escape_html(msg['content'])}</div>"
                )
            elif msg.get("is_html"):
                # append() 推入的已渲染 HTML，无需再交给 marked 解析
                html_parts.append(f"<div class='message-container role-ai'>{msg['content']}</div>")
            else:
                # 注意：这里我们借助 JS 端的 marked 库，所以 Python 端只需包一层外壳即可
                # 真正的 Markdown -> HTML 转换在 JS 端完成
                safe_content = json.dumps(msg["content"])
                html_parts.append(
                    f"<div class='message-container role-ai'>🤖 AI 助教：<br><span class='md-content' data-raw={safe_content}></span></div>"
                )

        # 2. 渲染当前正在打字的流式消息
        if self._current_streaming_content:
            safe_stream = json.dumps(self._current_streaming_content)
            html_parts.append(
                f"<div class='message-container role-ai'>🤖 AI 助教：<br><span class='md-content' data-raw={safe_stream}></span><span style='animation: blink 1s infinite;'> ▋</span></div>"
            )

        # 组合最终的 HTML 结构（附加一段简易的 JS 将 data-raw 解析为 markdown）
        full_html = "".join(html_parts)

        # 组装注入脚本，让前端解析刚才塞入的 data-raw 属性
        # [BUG修复] 转义反引号和 ${} 防止 JS 注入
        safe_html = full_html.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
        js_code = f"""
        (function() {{
            let rawHtml = `{safe_html}`;
            // 创建临时容器
            let tempDiv = document.createElement('div');
            tempDiv.innerHTML = rawHtml;
            
            // 将所有带有 data-raw 的 span 替换为 marked.js 解析后的纯净 HTML
            let mdSpans = tempDiv.querySelectorAll('.md-content');
            mdSpans.forEach(span => {{
                let rawText = JSON.parse(span.getAttribute('data-raw'));
                span.innerHTML = marked.parse(rawText);
            }});
            
            // 调用核心引擎刷新界面并渲染 LaTeX
            window.updateChat(tempDiv.innerHTML);
        }})();
        """

        self.page().runJavaScript(js_code)

    def _escape_html(self, text: str) -> str:
        """简单的用户输入转义，防止 XSS"""
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
