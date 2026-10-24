"""AI 流式引擎线程（从 ``ai_manager.py`` 拆出）。

本模块同时承担两件事：

1. **Qt / OpenAI 兼容层的单一真源** —— ``ai_manager.py`` 与插件都要用 ``QObject`` /
   ``Signal`` 和 openai 的异常类，兼容导入只在这里写一遍，别处一律从本模块取。
2. **Function Calling 流式工作线程** —— ``AIEngineWorker`` 负责发请求、攒流式分片、
   聚合 tool_calls 并通过信号回传，不掺任何业务判断。

拆出动机：原 ``ai_manager.py`` 单文件 1664 行，``AIEngineWorker.run()`` 内联在
``AIManager`` 与三个 Agent 之间，改动任何一处都要在千行文件里定位。
"""

import json
import importlib.util
from enum import Enum

from mathlab.utils.logger import get_logger

logger = get_logger(__name__)

# --- Qt / OpenAI 兼容层（全仓唯一一处，别处请从本模块 import） ----------------
try:
    from PyQt5.QtCore import QObject, QThread
    from PyQt5.QtCore import pyqtSignal as Signal

    QT_AVAILABLE = True
except ImportError:
    try:
        from PySide6.QtCore import QObject, QThread, Signal

        QT_AVAILABLE = True
    except ImportError:
        QT_AVAILABLE = False
        QObject, QThread, Signal = object, object, object  # type: ignore[assignment, misc]

try:
    from openai import (
        APIConnectionError,
        APIStatusError,
        APITimeoutError,
        AuthenticationError,
        OpenAI,
        RateLimitError,
    )

    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    OpenAI = object  # type: ignore[assignment, misc]
    AuthenticationError = APIConnectionError = Exception  # type: ignore[assignment, misc]
    APIStatusError = APITimeoutError = RateLimitError = Exception  # type: ignore[assignment, misc]

# 兼容层消费方需要的重型库探测，同样集中在此
TORCH_AVAILABLE = importlib.util.find_spec("torch") is not None

try:
    import onnxruntime as ort  # noqa: F401

    ONNX_AVAILABLE = True
except ImportError:
    ONNX_AVAILABLE = False

try:
    import requests  # noqa: F401

    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False


def describe_api_error(exc: Exception) -> str:
    """把 SDK/网络异常翻译成面向用户的简短提示。

    自建网关的 base_url、上游返回体、请求 id 一律不得进 UI（既泄露部署细节，
    对用户也没有可读性）。完整异常仍然写日志，只是不再进 UI。

    Args:
        exc: openai SDK 抛出的异常（缺失 SDK 时退化为普通 ``Exception``）。

    Returns:
        可直接展示给用户的中文短句。
    """
    if isinstance(exc, AuthenticationError):
        return "API Key 无效或已过期，请在“偏好设置”里重新填写。"
    if isinstance(exc, RateLimitError):
        return "请求过于频繁或额度已用尽，请稍后再试。"
    if isinstance(exc, APITimeoutError):
        return "请求超时：模型服务器没有及时响应。"
    if isinstance(exc, APIConnectionError):
        return "无法连接到 AI 服务，请检查网络或 Base URL 是否正确。"
    if isinstance(exc, APIStatusError):
        status = getattr(exc, "status_code", None)
        if status in (404, 410):
            return f"接口或模型不存在（HTTP {status}），请检查模型名称。"
        if status and status >= 500:
            return f"AI 服务暂时不可用（HTTP {status}），请稍后再试。"
        return f"AI 服务返回错误（HTTP {status}）。" if status else "AI 服务返回错误。"
    return "AI 请求失败，详见日志。"


class AIState(Enum):
    IDLE = "空闲"
    THINKING = "思考中..."  # 已发请求，等待首字节 (TTFB)
    GENERATING = "生成中..."  # 正在打字输出
    EXECUTING_TOOL = "执行工具中..."  # 正在调用画笔等本地函数
    FINISHED = "完成"
    ERROR = "出错了"


class AIEngineWorker(QThread):
    """统一、纯净的流式 AI 核心线程。

    全面废弃野路子正则，严格使用 Function Calling，支持 Token 统计。
    """

    state_changed = Signal(AIState)
    chunk_received = Signal(str)
    tool_call_received = Signal(str, object)
    usage_reported = Signal(int, int)
    finished_text = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, client: OpenAI, model: str, messages: list, tools: list = None):
        super().__init__()
        self.client = client
        self.model = model
        self.messages = messages
        self.tools = tools
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def stop(self):
        self.cancel()

    def run(self):
        self.state_changed.emit(AIState.THINKING)
        try:
            response = self._create_stream()
            full_text, tool_calls_buffer = self._consume_stream(response)

            if tool_calls_buffer:
                self._emit_tool_calls(tool_calls_buffer)

            if not self._is_cancelled:
                self.state_changed.emit(AIState.FINISHED)
                self.finished_text.emit(full_text)
            else:
                self.state_changed.emit(AIState.IDLE)

        except Exception as e:
            self.state_changed.emit(AIState.ERROR)
            # 不把 str(e) 原样发给 UI（会带出 base_url / 上游响应体），完整异常只写日志
            self.error_occurred.emit(describe_api_error(e))
            logger.error("AI Worker Error: %s", e, exc_info=True)

    # ------------------------------------------------------------------
    # 内部步骤（拆开只为让 run() 保持线性可读）
    # ------------------------------------------------------------------
    def _create_stream(self):
        """发起带 Function Calling 的流式请求。"""
        kwargs = {
            "model": self.model,
            "messages": self.messages,
            "stream": True,
            "temperature": 0.3,
            "stream_options": {"include_usage": True},
        }
        if self.tools:
            kwargs["tools"] = self.tools
            kwargs["tool_choice"] = "auto"
        return self.client.chat.completions.create(**kwargs)

    def _consume_stream(self, response):
        """遍历流式分片，返回 (纯文本, tool_calls 缓冲)。

        tool_calls 按 index 聚合，因为 SDK 会把函数名与参数切成多个分片下发。
        """
        full_text = ""
        tool_calls_buffer = {}
        has_started_typing = False

        for chunk in response:
            if self._is_cancelled:
                break

            if chunk.usage is not None:
                self.usage_reported.emit(chunk.usage.prompt_tokens, chunk.usage.completion_tokens)
                continue

            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta
            content = getattr(delta, "content", None)
            delta_tool_calls = getattr(delta, "tool_calls", None)

            if not has_started_typing and (content or delta_tool_calls):
                has_started_typing = True
                self.state_changed.emit(AIState.GENERATING)

            if content:
                full_text += content
                self.chunk_received.emit(content)

            if delta_tool_calls:
                for tc in delta_tool_calls:
                    self._accumulate_tool_call(tool_calls_buffer, tc)

        return full_text, tool_calls_buffer

    @staticmethod
    def _accumulate_tool_call(buffer: dict, tc) -> None:
        """把一个 tool_call 分片并入缓冲区。"""
        idx = tc.index
        if idx not in buffer:
            name = (tc.function.name or "") if tc.function else ""
            buffer[idx] = {"name": name, "arguments": ""}
        elif tc.function and tc.function.name:
            buffer[idx]["name"] = tc.function.name

        if tc.function and tc.function.arguments:
            buffer[idx]["arguments"] += tc.function.arguments

    def _emit_tool_calls(self, tool_calls_buffer: dict) -> None:
        """把攒好的 tool_calls 逐个解析成参数字典并发出。"""
        self.state_changed.emit(AIState.EXECUTING_TOOL)
        for tc in tool_calls_buffer.values():
            try:
                args = json.loads(tc["arguments"]) if tc["arguments"] else {}
            except (json.JSONDecodeError, TypeError):
                args = {}
            self.tool_call_received.emit(tc["name"], args)
