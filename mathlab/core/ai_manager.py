import importlib.util
import threading
from typing import Optional

import numpy as np

from mathlab.core.ai_tools import GEOMETRY_DRAW_TOOL, execute_math_task
from mathlab.core.skill_manager import SkillLibrary

if importlib.util.find_spec("sklearn") is not None:
    SKLEARN_AVAILABLE = True
else:
    SKLEARN_AVAILABLE = False
import json
import os
from enum import Enum

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
        QObject, QThread, Signal = object, object, object

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

from mathlab.core.memory_manager import ChatMemoryManager
from mathlab.utils.logger import get_logger

logger = get_logger(__name__)

# HTTP 客户端超时与重试：openai SDK 默认 read timeout 是 600 秒，
# 网关挂住时用户要等 10 分钟才看到错误；这里收紧到"连接快、读取宽松、失败少量重试"。
AI_CONNECT_TIMEOUT = 10.0
AI_READ_TIMEOUT = 120.0
AI_WRITE_TIMEOUT = 30.0
AI_POOL_TIMEOUT = 10.0
AI_MAX_RETRIES = 2


def describe_api_error(exc: Exception) -> str:
    """把 SDK/网络异常翻译成面向用户的简短提示。

    [P1 修复] 原先直接把 ``str(exc)`` 发到 UI：自建网关的 base_url、上游返回体、
    请求 id 都会原样出现在聊天区（既泄露部署细节，对用户也没有可读性）。
    完整异常仍然写日志，只是不再进 UI。
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


# 工具 Schema 统一从 ai_tools.py 导入（消除重复定义）
DRAW_TOOL_SCHEMA = GEOMETRY_DRAW_TOOL  # 别名，供 quiz_panel 等模块使用

# Torch availability check — 使用 find_spec 快速检测，避免模块级 import 加载重型库
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


def _lazy_import_torch():
    """延迟导入 PyTorch，仅在 fit_neural_network 首次调用时加载"""
    import torch
    import torch.nn as nn

    return torch, nn


# --- 1. 引入严格的生成状态机 ---


class AIProvider(Enum):
    OPENAI = "openai"
    CLAUDE = "claude"
    GEMINI = "gemini"
    DEEPSEEK = "deepseek"
    KIMI = "kimi"
    MINIMAX = "minimax"
    QWEN = "qwen"
    ZHIPU = "zhipu"
    DOUBAO = "doubao"
    OLLAMA = "ollama"
    LOCAL = "local"


class AIRequestConfig:
    def __init__(
        self,
        provider: AIProvider = AIProvider.LOCAL,
        api_key: str = "",
        base_url: str = "",
    ):
        self.provider = provider
        self.api_key = api_key
        self.base_url = base_url


class AIState(Enum):
    IDLE = "空闲"
    THINKING = "思考中..."  # 已发请求，等待首字节 (TTFB)
    GENERATING = "生成中..."  # 正在打字输出
    EXECUTING_TOOL = "执行工具中..."  # 正在调用画笔等本地函数
    FINISHED = "完成"
    ERROR = "出错了"


class AIEngineWorker(QThread):
    """
    统一、纯净的流式 AI 核心线程
    全面废弃野路子正则，严格使用 Function Calling，支持 Token 统计
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

            response = self.client.chat.completions.create(**kwargs)

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

                if not has_started_typing and (
                    getattr(delta, "content", None) or getattr(delta, "tool_calls", None)
                ):  # noqa: E501
                    has_started_typing = True
                    self.state_changed.emit(AIState.GENERATING)

                if getattr(delta, "content", None):
                    full_text += delta.content
                    self.chunk_received.emit(delta.content)

                if getattr(delta, "tool_calls", None):
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls_buffer:
                            name = (tc.function.name or "") if tc.function else ""
                            tool_calls_buffer[idx] = {"name": name, "arguments": ""}
                        elif tc.function and tc.function.name:
                            tool_calls_buffer[idx]["name"] = tc.function.name

                        if tc.function and tc.function.arguments:
                            tool_calls_buffer[idx]["arguments"] += tc.function.arguments  # noqa: E501

            if tool_calls_buffer:
                self.state_changed.emit(AIState.EXECUTING_TOOL)
                for tc in tool_calls_buffer.values():
                    try:
                        args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                    except (json.JSONDecodeError, TypeError):
                        args = {}
                    self.tool_call_received.emit(tc["name"], args)

            if not self._is_cancelled:
                self.state_changed.emit(AIState.FINISHED)
                self.finished_text.emit(full_text)
            else:
                self.state_changed.emit(AIState.IDLE)

        except Exception as e:
            self.state_changed.emit(AIState.ERROR)
            # [P1 修复] 不再把 str(e) 原样发给 UI（会带出 base_url / 上游响应体），
            # 完整异常只写日志
            self.error_occurred.emit(describe_api_error(e))
            logger.error("AI Worker Error: %s", e, exc_info=True)


class AIManager(QObject):
    """
    单一职责的全局 AI 调度中心
    """

    def __init__(self, settings_manager=None):
        super().__init__()
        self.settings_manager = settings_manager
        self.client = None
        self.current_worker = None
        self.memory = ChatMemoryManager()
        self.models = {}
        self.sandbox = None
        self.current_model = "deepseek-chat"
        self.reload_config()

    def reload_config(self):
        """当用户在偏好设置中修改 API 后，自动重载客户端"""
        # [修复] 使用 __package__ 获取包目录，更健壮
        try:
            package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            settings_path = os.path.join(package_dir, "settings.json")
        except Exception:
            # 降级方案：使用当前文件路径
            settings_path = os.path.join(os.getcwd(), "settings.json")

        settings = {}
        if os.path.exists(settings_path):
            try:
                with open(settings_path, "r", encoding="utf-8") as f:
                    settings = json.load(f)
            except Exception as e:
                logger.error(f"加载 settings.json 失败: {e}")

        api_key = settings.get("ai_api_key", "")
        base_url = settings.get("ai_base_url", "https://api.deepseek.com/v1")
        self.current_model = settings.get("ai_model", "deepseek-chat")

        if api_key and OPENAI_AVAILABLE:
            # [P1 修复] 显式设定超时与重试：默认 read timeout 600s 会让挂死的网关
            # 占据用户整整 10 分钟，且 SDK 默认不重试。
            self.client = OpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=(AI_CONNECT_TIMEOUT, AI_READ_TIMEOUT),
                max_retries=AI_MAX_RETRIES,
            )
            logger.info("AI 引擎已初始化: %s [%s]", base_url, self.current_model)
        else:
            self.client = None

    def abort_current_task(self):
        if self.current_worker and self.current_worker.isRunning():
            self.current_worker.cancel()
            self.current_worker.wait(5000)

    def ask(
        self,
        user_prompt: str,
        system_prompt: str = "",
        tools: list = None,  # noqa: E501
        canvas_state: str = None,
        on_state_change=None,
        on_chunk=None,
        on_tool=None,
        on_usage=None,
        on_finish=None,
        on_error=None,
    ):  # noqa: E501

        if not self.client:
            if on_error:
                on_error("未配置 API Key。")
            return

        self.memory.add_message("user", user_prompt)
        messages = self.memory.get_context()

        dynamic_system_prompt = system_prompt
        if canvas_state and canvas_state != "{}":
            dynamic_system_prompt += f"""\n\n
【系统自动注入的视觉环境上下文】
你可以"看到"用户当前的画板状态。以下是画板上所有几何图形的实时 JSON 快照：
```json
{canvas_state}
```
当用户问"这个图怎么解"、"为什么我画的不对"等模糊问题时，请务必参考上述快照数据进行推导和回答。
"""

        if dynamic_system_prompt:
            messages.insert(0, {"role": "system", "content": dynamic_system_prompt})

        if self.current_worker and self.current_worker.isRunning():
            self.current_worker.cancel()
            if not self.current_worker.wait(5000):
                self.current_worker.disconnect()
                # [BUG修复] 移除危险的 terminate()，改为警告并断开连接
                logger.warning("AI Worker 未在 5 秒内停止，已断开信号连接")

        self.current_worker = AIEngineWorker(self.client, self.current_model, messages, tools)

        if on_state_change:
            self.current_worker.state_changed.connect(on_state_change)
        if on_chunk:
            self.current_worker.chunk_received.connect(on_chunk)
        if on_tool:
            self.current_worker.tool_call_received.connect(on_tool)
        if on_usage:
            self.current_worker.usage_reported.connect(on_usage)
        if on_error:
            self.current_worker.error_occurred.connect(on_error)

        def internal_finish(full_text):
            if full_text:
                self.memory.add_message("assistant", full_text)
            if on_finish:
                on_finish()

        self.current_worker.finished_text.connect(internal_finish)
        self.current_worker.start()

    def load_onnx_model(self, model_path, model_name):
        if not ONNX_AVAILABLE:
            return {"success": False, "error": "ONNX Runtime not available"}

        try:
            session = ort.InferenceSession(model_path)
            self.models[model_name] = {
                "session": session,
                "input_name": session.get_inputs()[0].name,
                "output_name": session.get_outputs()[0].name,
            }
            return {
                "success": True,
                "message": f"Model {model_name} loaded successfully",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def predict(self, model_name, input_data):
        if model_name not in self.models:
            return {"success": False, "error": "Model not found"}

        model = self.models[model_name]
        try:
            input_data = np.array(input_data, dtype=np.float32)
            if len(input_data.shape) == 1:
                input_data = input_data.reshape(1, -1)

            result = model["session"].run([model["output_name"]], {model["input_name"]: input_data})

            return {"success": True, "prediction": result[0].tolist()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def fit_linear_regression(self, points):
        if not SKLEARN_AVAILABLE:
            return {"success": False, "error": "scikit-learn not available"}
        if len(points) < 2:
            return {"success": False, "error": "Need at least 2 points"}

        from sklearn.linear_model import LinearRegression
        from sklearn.metrics import mean_squared_error

        X = np.array([[p[0]] for p in points], dtype=np.float32)
        y = np.array([p[1] for p in points], dtype=np.float32)

        model = LinearRegression()
        model.fit(X, y)

        slope = float(model.coef_[0])
        intercept = float(model.intercept_)

        predictions = model.predict(X)
        mse = float(mean_squared_error(y, predictions))

        return {
            "success": True,
            "slope": slope,
            "intercept": intercept,
            "equation": f"y = {slope:.4f}x + {intercept:.4f}",
            "mse": mse,
            "predictions": predictions.tolist(),
        }

    def fit_polynomial_regression(self, points, degree=2):
        if not SKLEARN_AVAILABLE:
            return {"success": False, "error": "scikit-learn not available"}
        if len(points) < degree + 1:
            return {"success": False, "error": f"Need at least {degree + 1} points"}

        from sklearn.metrics import mean_squared_error

        X = np.array([p[0] for p in points], dtype=np.float64)
        y = np.array([p[1] for p in points], dtype=np.float64)

        coefficients = np.polyfit(X, y, degree)[::-1]
        poly = np.poly1d(coefficients[::-1])

        predictions = poly(X)
        mse = float(mean_squared_error(y, predictions))

        # 规范化公式字符串，避免多行输出
        # coefficients 已经是低次到高次排列（经过 [::-1] 反转），i 即为幂次
        terms = []
        for i, c in enumerate(coefficients):
            power = i
            if abs(c) < 1e-10:
                continue
            if power == 0:
                terms.append(f"{c:.4f}")
            elif power == 1:
                terms.append(f"{c:.4f}x")
            else:
                terms.append(f"{c:.4f}x^{power}")
        equation = "y = " + " + ".join(terms) if terms else "y = 0"

        return {
            "success": True,
            "coefficients": coefficients.tolist(),
            "intercept": float(coefficients[0]),  # coefficients[0] 是常数项（低次在前）
            "equation": equation,
            "mse": mse,
            "predictions": predictions.tolist(),
        }

    def fit_neural_network(self, points, epochs=100, hidden_size=10):
        if not TORCH_AVAILABLE:
            return {"success": False, "error": "PyTorch not available"}

        if len(points) < 2:
            return {"success": False, "error": "Need at least 2 points"}

        # 延迟导入 PyTorch，避免启动时加载重型库
        torch, nn = _lazy_import_torch()

        X = torch.tensor([[p[0]] for p in points], dtype=torch.float32)
        y = torch.tensor([[p[1]] for p in points], dtype=torch.float32)

        model = nn.Sequential(nn.Linear(1, hidden_size), nn.ReLU(), nn.Linear(hidden_size, 1))

        criterion = nn.MSELoss()
        optimizer = torch.optim.Adam(model.parameters(), lr=0.01)

        loss_history = []

        for epoch in range(epochs):
            optimizer.zero_grad()
            outputs = model(X)
            loss = criterion(outputs, y)
            loss.backward()
            optimizer.step()

            loss_history.append(float(loss.item()))

        with torch.no_grad():
            predictions = model(X).numpy().flatten()

        # [P0修复 Bug1] 移除错误的 self.emit()：AIManager 不是 QObject，无此方法
        # 使用 PyTorch 计算 MSE，移除对 sklearn 的隐式依赖
        mse = float(criterion(torch.tensor(predictions).reshape(-1, 1), y).item())

        return {
            "success": True,
            "loss_history": loss_history,
            "mse": mse,
            "predictions": predictions.tolist(),
            "epochs": epochs,
        }

    def cluster_kmeans(self, points, n_clusters=3):
        if not SKLEARN_AVAILABLE:
            return {"success": False, "error": "scikit-learn not available"}
        if len(points) < n_clusters:
            return {
                "success": False,
                "error": "Not enough points for clusters",
            }  # noqa: E501

        from sklearn.cluster import KMeans

        X = np.array(points, dtype=np.float32)

        model = KMeans(n_clusters=n_clusters, n_init=10)
        model.fit(X)

        labels = model.labels_.tolist()
        centers = model.cluster_centers_.tolist()

        return {
            "success": True,
            "labels": labels,
            "centers": centers,
            "inertia": float(model.inertia_),
        }

    def cluster_dbscan(self, points, eps=0.5, min_samples=5):
        if not SKLEARN_AVAILABLE:
            return {"success": False, "error": "scikit-learn not available"}
        if len(points) < min_samples:
            return {"success": False, "error": "Not enough points"}

        from sklearn.cluster import DBSCAN

        X = np.array(points, dtype=np.float32)

        model = DBSCAN(eps=eps, min_samples=min_samples)
        model.fit(X)

        labels = model.labels_.tolist()
        n_clusters = len(set(labels)) - (1 if -1 in labels else 0)

        return {
            "success": True,
            "labels": labels,
            "n_clusters": n_clusters,
            "n_noise": list(labels).count(-1),
        }

    def recognize_digit(self, image_data):
        if not ONNX_AVAILABLE:
            return {"success": False, "error": "ONNX Runtime not available"}

        if "mnist" not in self.models:
            return {"success": False, "error": "MNIST model not loaded"}

        model = self.models["mnist"]

        try:
            image_data = np.array(image_data, dtype=np.float32).reshape(1, 1, 28, 28) / 255.0

            result = model["session"].run([model["output_name"]], {model["input_name"]: image_data})

            predictions = result[0][0]
            top3_indices = np.argsort(predictions)[::-1][:3]
            top3_probs = predictions[top3_indices].tolist()
            top3_digits = top3_indices.tolist()

            return {
                "success": True,
                "prediction": int(np.argmax(predictions)),
                "probabilities": predictions.tolist(),
                "top3": [{"digit": d, "probability": p} for d, p in zip(top3_digits, top3_probs)],  # noqa: E501
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def generate_random_points(self, n=10, x_range=(0, 100), y_range=(0, 100)):
        points = []
        for _ in range(n):
            x = np.random.uniform(x_range[0], x_range[1])
            y = np.random.uniform(y_range[0], y_range[1])
            points.append((x, y))
        return {"success": True, "points": points}

    def run_training_sandbox(self, code):
        from mathlab.core.sandbox import SandboxProcess

        sandbox = SandboxProcess()
        result = sandbox.run_code(code)
        return result


class ReasoningCache:
    """推理结果缓存：对相似问题复用历史推理结果，避免重复计算。

    使用 prompt 归一化 + TF-IDF 相似度匹配，当命中阈值时直接返回缓存结果。
    """

    def __init__(self, cache_path=None, similarity_threshold=0.85):
        self._cache_path = cache_path or os.path.join(os.path.dirname(__file__), "..", "data", "reasoning_cache.json")
        self._similarity_threshold = similarity_threshold
        self._cache = []
        self._lock = threading.Lock()
        self._vectorizer = None
        self._tfidf_matrix = None
        self._load()

    def _load(self):
        if os.path.exists(self._cache_path):
            try:
                with open(self._cache_path, "r", encoding="utf-8") as f:
                    self._cache = json.load(f)
            except Exception as e:
                logger.error(f"加载推理缓存失败: {e}")
                self._cache = []

    def _save(self):
        os.makedirs(os.path.dirname(self._cache_path), exist_ok=True)
        with open(self._cache_path, "w", encoding="utf-8") as f:
            json.dump(self._cache, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _normalize_prompt(prompt):
        """归一化 prompt：去除多余空白、统一大小写"""
        return " ".join(prompt.lower().split())

    def get(self, user_prompt):
        """检索缓存，返回匹配的结果或 None"""
        with self._lock:
            if not self._cache:
                return None

            normalized = self._normalize_prompt(user_prompt)

            # 快速精确匹配
            for entry in self._cache:
                if self._normalize_prompt(entry["prompt"]) == normalized:
                    logger.info(f"📦 推理缓存精确命中: {user_prompt[:40]}...")
                    return entry["result"]

            # TF-IDF 相似度匹配
            if SKLEARN_AVAILABLE and len(self._cache) > 1:
                try:
                    from sklearn.feature_extraction.text import TfidfVectorizer
                    from sklearn.metrics.pairwise import cosine_similarity as _cos_sim

                    corpus = [self._normalize_prompt(e["prompt"]) for e in self._cache]
                    if self._vectorizer is None:
                        self._vectorizer = TfidfVectorizer()
                        self._tfidf_matrix = self._vectorizer.fit_transform(corpus)

                    query_vec = self._vectorizer.transform([normalized])
                    sims = _cos_sim(query_vec, self._tfidf_matrix)[0]
                    best_idx = int(np.argmax(sims))

                    if sims[best_idx] >= self._similarity_threshold:
                        logger.info(f"📦 推理缓存相似命中 (sim={sims[best_idx]:.3f}): " f"{user_prompt[:40]}...")
                        return self._cache[best_idx]["result"]
                except Exception as e:
                    logger.error(f"缓存相似度检索失败: {e}")

            return None

    def put(self, user_prompt, result, ttl_keys=None):
        """存入缓存结果。ttl_keys 为可选的失效标记键列表。"""
        with self._lock:
            normalized = self._normalize_prompt(user_prompt)
            # 去重：已存在相似 prompt 则覆盖
            for i, entry in enumerate(self._cache):
                if self._normalize_prompt(entry["prompt"]) == normalized:
                    self._cache[i] = {
                        "prompt": user_prompt,
                        "result": result,
                        "ttl_keys": ttl_keys or [],
                    }
                    self._save()
                    self._invalidate_cache()
                    return

            self._cache.append(
                {
                    "prompt": user_prompt,
                    "result": result,
                    "ttl_keys": ttl_keys or [],
                }
            )
            self._save()
            self._invalidate_cache()
            logger.info(f"📦 推理结果已缓存: {user_prompt[:40]}...")

    def _invalidate_cache(self):
        self._vectorizer = None
        self._tfidf_matrix = None

    def invalidate_all(self):
        """清空全部缓存"""
        with self._lock:
            self._cache = []
            self._invalidate_cache()
            self._save()
            logger.info("📦 推理缓存已全部清空")


class ResourceConfig:
    """Agent 执行资源限制配置：防止恶意代码耗尽 CPU/内存。

    Attributes:
        max_memory_mb: 沙箱最大内存上限 (MB)
        max_time_seconds: 单次执行最大耗时 (秒)
        max_cpu_percent: 单次执行最大 CPU 占比 (%)
        max_steps: ReAct 循环最大重试次数
    """

    DEFAULT = None  # 类级默认实例，延迟初始化

    def __init__(self, max_memory_mb=512, max_time_seconds=60, max_cpu_percent=80, max_steps=5):
        self.max_memory_mb = max_memory_mb
        self.max_time_seconds = max_time_seconds
        self.max_cpu_percent = max_cpu_percent
        self.max_steps = max_steps

    def to_dict(self):
        return {
            "max_memory_mb": self.max_memory_mb,
            "max_time_seconds": self.max_time_seconds,
            "max_cpu_percent": self.max_cpu_percent,
            "max_steps": self.max_steps,
        }

    @classmethod
    def get_default(cls):
        if cls.DEFAULT is None:
            cls.DEFAULT = cls()
        return cls.DEFAULT

    @classmethod
    def for_agent(cls, agent_name):
        """根据 Agent 名称返回预设的资源限制"""
        presets = {
            "PlannerAgent": cls(max_memory_mb=512, max_time_seconds=120, max_cpu_percent=80, max_steps=5),
            "GeometryAgent": cls(max_memory_mb=256, max_time_seconds=60, max_cpu_percent=70, max_steps=5),
            "DataVizAgent": cls(max_memory_mb=512, max_time_seconds=90, max_cpu_percent=80, max_steps=5),
        }
        return presets.get(agent_name, cls.get_default())


class BaseMathAgent:
    def __init__(
        self,
        ai_manager,
        model="deepseek-chat",
        model_override=None,
        resource_config=None,
        student_model=None,
        agent_id=None,
    ):
        self.ai_manager = ai_manager
        self.model = model
        # 模型多样性：允许每个 Agent 使用不同的模型
        self.model_override = model_override  # 如 "gpt-4o", "deepseek-reasoner"
        self.max_steps = 5
        self.skill_lib = SkillLibrary()  # 实例化本地技能库
        # 推理缓存：相似问题复用历史结果
        self._reasoning_cache = ReasoningCache()
        # 资源限制配置
        self.resource_config = resource_config or ResourceConfig.get_default()
        self.max_steps = self.resource_config.max_steps
        # 学生认知模型：支持自适应教学
        self.student_model = student_model
        self._adaptive_engine = None
        if student_model is not None:
            from mathlab.core.student_model import AdaptiveEngine

            self._adaptive_engine = AdaptiveEngine(student_model)
        # 结构化通信协议：Agent ID 和消息总线
        self.agent_id = agent_id or self.__class__.__name__
        self._message_bus = None
        self._conversation_id = None
        self.system_prompt = "你是一个资深的数学科研助手与高级 Python 程序员。\n请通过 Thought, Action, Observation 闭环结构的计算过程解决问题。"  # noqa: E501

    def set_message_bus(self, message_bus):
        """绑定消息总线实例（由 AgentRegistry 在注册时调用）。"""
        self._message_bus = message_bus

    def send_message(
        self,
        receiver_id: str,
        msg_type,
        content,
        **metadata,
    ) -> Optional[str]:
        """通过消息总线发送结构化消息。

        Args:
            receiver_id: 接收方 Agent ID（"broadcast" 表示广播）
            msg_type: MessageType 枚举值
            content: 消息内容
            **metadata: 元数据（如 step_num, cognitive_level 等）

        Returns:
            消息 ID（如果发送成功），None 如果消息总线未绑定
        """
        if self._message_bus is None:
            logger.debug(f"Agent '{self.agent_id}' 消息总线未绑定，跳过消息发送")
            return None

        from mathlab.core.agent_message import AgentMessage

        msg = AgentMessage(
            sender_id=self.agent_id,
            receiver_id=receiver_id,
            msg_type=msg_type,
            content=content,
            metadata=metadata,
            conversation_id=self._conversation_id,
        )
        self._message_bus.publish(msg)
        return msg.id

    def _get_effective_model(self):
        """获取当前 Agent 实际使用的模型：优先 model_override，其次 ai_manager.current_model"""
        return self.model_override or getattr(self.ai_manager, "current_model", None) or self.model  # noqa: E501

    def _llm_generate_code(self, messages):
        # 真正使用时通过 ai_manager.client 调用大模型接口
        try:
            model = self._get_effective_model()
            response = self.ai_manager.client.chat.completions.create(model=model, messages=messages, temperature=0.1)
            suggestion = response.choices[0].message.content if response.choices else ""  # noqa: E501
            suggestion = suggestion.replace("```python\n", "").replace("\n```", "").replace("```", "")
            return suggestion
        except Exception as e:
            # SUGGESTION 11 修复：使用 logger 替代 print
            logger.error(f"LLM Generate Code Error: {e}")
            return "print('Error generating code')"

    def solve_problem(
        self,
        user_prompt: str,
        on_thought_cb=None,
        on_code_cb=None,
        on_finish_cb=None,
        on_geom_cb=None,
    ):
        # ============== 前置校验：未配置 API 客户端时直接失败，避免 NoneType 崩溃 ==============
        if getattr(self.ai_manager, "client", None) is None:
            if on_thought_cb:
                on_thought_cb("❌ 未配置 AI API Key，无法启动推理闭环。")
            if on_finish_cb:
                on_finish_cb(False, "未配置 API Key")
            return {"status": "failed", "error": "未配置 API Key"}

        # ============== 0. 推理缓存检索阶段 ==============
        cached = self._reasoning_cache.get(user_prompt)
        if cached is not None:
            if on_thought_cb:
                on_thought_cb("📦 推理缓存命中！直接复用历史结果，跳过 LLM 调用。")
            if on_code_cb:
                on_code_cb(cached.get("code", ""))
            geom_cmds = cached.get("geom_commands", [])
            if geom_cmds and on_geom_cb:
                on_geom_cb(geom_cmds)
            if on_finish_cb:
                on_finish_cb(True, cached.get("code", ""))
            return cached

        # ============== 1. RAG 检索阶段 ==============
        if on_thought_cb:
            on_thought_cb("🔍 正在检索本地技能库记忆...")

        relevant_skills = self.skill_lib.retrieve_relevant_skills(user_prompt)
        skill_context = ""
        if relevant_skills:
            skill_context = "\n【本地技能库中的成功经验】\n以下是你过去成功写过的类似代码，你可以直接复用或参考它们的 API 调用方式：\n"  # noqa: E501
            for s in relevant_skills:
                skill_context += f"💡 意图: {s['intent']}\n```python\n{s['code']}\n```\n\n"
            if on_thought_cb:
                on_thought_cb(f"⚡ 唤醒了 {len(relevant_skills)} 条历史成功经验！")

        # 将 RAG 内容动态注入到 System Prompt
        # 注入自适应教学策略（如果学生模型可用）
        adaptive_context = ""
        if self._adaptive_engine:
            adaptive_context = self._adaptive_engine.build_adaptive_prompt(user_prompt)
            if on_thought_cb:
                profile = self.student_model.get_profile_summary()
                on_thought_cb(
                    f"🎓 已加载学生认知画像："
                    f"认知层级={profile['cognitive_level']}，"
                    f"偏好={profile['learning_style']}，"
                    f"掌握度={profile['avg_mastery']}"
                )

        # 注入教学法约束（代码生成质量指导）
        pedagogical_context = ""
        if self.student_model is not None:
            from mathlab.core.pedagogical_engine import PedagogicalPromptBuilder

            pedagogical_builder = PedagogicalPromptBuilder(self.student_model)
            pedagogical_context = pedagogical_builder.build_code_generation_constraint(user_prompt)

        system_prompt = f"""{self.system_prompt}
{skill_context}
{adaptive_context}
{pedagogical_context}
不要输出多余的 Markdown，必须且只能将代码写在 ```python 块中。"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"任务：{user_prompt}"},
        ]

        for step in range(self.max_steps):
            if on_thought_cb:
                on_thought_cb(f"⚙️ 正在生成代码 (第 {step + 1} 次尝试)...")

            code_content = self._llm_generate_code(messages)

            if on_code_cb:
                on_code_cb(code_content)

            # 执行代码
            try:
                execution_result_str = execute_math_task(code_content)
                if isinstance(execution_result_str, dict):
                    execution_result = execution_result_str
                else:
                    execution_result = json.loads(execution_result_str)
            except Exception as e:
                execution_result = {"status": "error", "error": str(e)}

            if execution_result.get("status") == "ok":
                # 提取沙箱中累积的几何绘图命令
                geom_commands = execution_result.get("geom_commands", [])
                if geom_commands and on_geom_cb:
                    on_geom_cb(geom_commands)

                if on_thought_cb:
                    on_thought_cb(f"✅ 沙箱执行成功！输出:\n{execution_result.get('output', '')}")

                # ============== 2. 触发后台"自我提炼"机制 ==============
                threading.Thread(
                    target=self._reflect_and_save_skill,
                    args=(user_prompt, code_content),
                    daemon=True,
                ).start()

                # ============== 3. 推理缓存存储 ==============
                cache_result = {
                    "status": "ok",
                    "code": code_content,
                    "result": execution_result.get("output", ""),
                    "geom_commands": geom_commands,
                }
                self._reasoning_cache.put(user_prompt, cache_result)

                # ============== 4. 记录学生互动（自适应学习） ==============
                if self.student_model and self._adaptive_engine:
                    self._record_student_interaction(user_prompt, success=True)

                if on_finish_cb:
                    on_finish_cb(True, code_content)
                return cache_result
            else:
                error_msg = execution_result.get("error", "未知错误")
                if on_thought_cb:
                    on_thought_cb(
                        f"❌ 代码报错 (第 {step + 1} 次尝试), 正在修正...\n报错内容: {error_msg}"
                    )  # noqa: E501

                # 将报错信息加入对话历史，让 AI 修正
                messages.append({"role": "assistant", "content": f"```python\n{code_content}\n```"})
                messages.append(
                    {
                        "role": "user",
                        "content": f"执行失败，报错如下：\n{error_msg}\n请修正代码。",
                    }
                )  # noqa: E501

                # BUG 6 修复：限制历史消息数量，避免上下文无限增长
                # 保留 system + 初始 user（前2条）+ 最近3轮对话（6条）
                MAX_HISTORY_MSGS = 8
                if len(messages) > MAX_HISTORY_MSGS:
                    messages = messages[:2] + messages[-(MAX_HISTORY_MSGS - 2) :]

        if on_finish_cb:
            on_finish_cb(False, "超出最大重试次数")

        # 记录失败互动（自适应学习：追踪薄弱点）
        if self.student_model and self._adaptive_engine:
            self._record_student_interaction(user_prompt, success=False)

        return {"status": "failed", "error": "超出最大重试次数"}

    def _record_student_interaction(self, user_prompt: str, success: bool):
        """记录学生互动到认知模型中（自适应学习核心）。"""
        try:
            interaction_type = self._adaptive_engine.classify_interaction(user_prompt, success)
            knowledge_point = self._adaptive_engine.extract_knowledge_point(user_prompt)
            cognitive_demand = self._adaptive_engine.get_recommended_cognitive_demand()
            self.student_model.record_interaction(
                interaction_type=interaction_type,
                knowledge_point=knowledge_point,
                prompt_text=user_prompt,
                success=success,
                cognitive_demand=cognitive_demand,
            )
        except Exception as e:
            logger.error(f"记录学生互动失败: {e}")

    def _reflect_and_save_skill(self, original_prompt, raw_code):
        """后台静默运行：让大模型把刚刚跑通的特定业务代码，抽象为通用函数库"""
        reflection_prompt = f"""
以下代码成功解决了任务："{original_prompt}"。
请你将这段代码进行"抽象和提炼"，将其封装成一个或多个通用的 Python 函数，剥离掉与特定题目相关的硬编码数字，并加上中文注释。

你必须严格按照以下 JSON 格式返回，不要包含其他任何文本：
{{
    "intent": "一句话描述这个通用函数解决什么问题（例如：求两条曲线的交点并绘制）",
    "abstract_code": "def your_function():\\n    ..."
}}
"""
        try:
            response = self.ai_manager.client.chat.completions.create(
                model=self._get_effective_model(),
                messages=[{"role": "user", "content": reflection_prompt}],
                response_format={"type": "json_object"},  # 强制要求返回 JSON
            )
            result_json = json.loads(response.choices[0].message.content)

            # 存入本地知识库
            self.skill_lib.save_skill(result_json["intent"], result_json["abstract_code"])
        except Exception as e:
            # SUGGESTION 11 修复：使用 logger 替代 print
            logger.error(f"技能提炼失败 (后台线程): {e}")


class PlannerAgent(BaseMathAgent):
    """教研组长 —— 多智能体自治系统的顶层调度者。

    职责：
    1. 将用户的数学问题拆解为 3-5 个由浅入深的教学步骤
    2. 调度 GeometryAgent / DataVizAgent 执行每一步（支持串行/并行模式）
    3. 汇总结果并给出最终教学总结
    """

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

    def _decompose_problem(self, user_prompt: str) -> dict:
        """
        调用 LLM 将用户问题拆解为教学大纲。
        返回格式: {"topic": "...", "steps": [{"num": 1, "title": "...", "hint_for_teacher": "...", "parallelizable": false}]}
        parallelizable=true 表示该步骤可与其他可并行步骤同时执行。
        """
        # 注入自适应教学策略（基于学生认知画像）
        adaptive_strategy = ""
        if self._adaptive_engine:
            adaptive_strategy = self._adaptive_engine.build_adaptive_prompt(user_prompt)

        # 注入教学法约束（Bloom/ZPD/UDL/Socratic）
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
            plan = json.loads(response.choices[0].message.content)
            return plan
        except Exception:
            # 降级：返回一个极简大纲
            return {
                "topic": user_prompt,
                "steps": [
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
                ],
            }

    def _pick_sub_agent(self, step_title: str, hint: str) -> str:
        """根据步骤标题和提示文本，推断应该派发给哪个子 Agent。
        返回 AgentRegistry 中注册的名字（如 'GeometryAgent' 或 'DataVizAgent'）。
        """
        combined = f"{step_title} {hint}".lower()
        viz_keywords = [
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
        ]

        # BUG 7 修复：动态查找已注册的 Agent，而非硬编码名称
        registry = getattr(self, "agent_registry", None)
        if not registry or not registry.agents:
            return "GeometryAgent"

        # 优先查找 DataViz 相关专家
        for name, info in registry.agents.items():
            desc = info.get("description", "").lower()
            if any(kw in desc for kw in ["可视化", "图表", "echarts"]):
                if any(kw in combined for kw in viz_keywords):
                    return name

        # 默认查找几何专家
        for name, info in registry.agents.items():
            desc = info.get("description", "").lower()
            if any(kw in desc for kw in ["几何", "geometry"]):
                return name

        # 回退到第一个注册的 Agent（排除自身 PlannerAgent）
        for name in registry.agents:
            if name != "PlannerAgent":
                return name

        return list(registry.agents.keys())[0] if registry.agents else "GeometryAgent"

    def solve_problem(
        self,
        user_prompt: str,
        on_thought_cb=None,
        on_code_cb=None,
        on_finish_cb=None,
        on_geom_cb=None,
    ):
        """教研组长的核心调度闭环：拆解 → 串行委派 → 汇总。"""

        if getattr(self.ai_manager, "client", None) is None:
            if on_thought_cb:
                on_thought_cb("❌ 未配置 AI API Key，无法启动教研调度。")
            if on_finish_cb:
                on_finish_cb(False, "未配置 API Key")
            return {"status": "failed", "error": "未配置 API Key"}

        # 生成会话 ID，关联本轮对话的所有 Agent 间消息
        import uuid as _uuid

        self._conversation_id = str(_uuid.uuid4())[:8]

        # 通过消息总线广播教学任务开始
        if self._message_bus:
            from mathlab.core.agent_message import MessageType

            self.send_message(
                receiver_id="broadcast",
                msg_type=MessageType.NOTIFICATION,
                content=f"教学任务启动: {user_prompt[:50]}",
                conversation_id=self._conversation_id,
                topic="数学教学",
            )

        # ========== 阶段 1: 拆解教学大纲 ==========
        if on_thought_cb:
            on_thought_cb("🧠 教研组长正在分析问题，制定教学大纲...")

        # 显示学生认知画像（自适应教学）
        if self.student_model and self._adaptive_engine:
            profile = self.student_model.get_profile_summary()
            comfort, stretch = self.student_model.get_zpd_zone()
            if on_thought_cb:
                on_thought_cb(
                    f"🎓 学生画像加载完成：\n"
                    f"  ├─ 认知层级：{profile['cognitive_level']}\n"
                    f"  ├─ 学习偏好：{profile['learning_style']}\n"
                    f"  ├─ 平均掌握度：{profile['avg_mastery']}\n"
                    f"  ├─ 参与度：{profile['engagement']}\n"
                    f"  ├─ ZPD区间：{comfort.to_chinese()} → {stretch.to_chinese()}\n"
                    f"  └─ 薄弱知识点：{', '.join(profile['weakness_areas']) or '无'}"
                )

        plan = self._decompose_problem(user_prompt)
        topic = plan.get("topic", user_prompt)
        steps = plan.get("steps", [])

        if not steps:
            if on_thought_cb:
                on_thought_cb("⚠️ 教学大纲生成失败，回退到通用求解模式。")
            # 回退到基类的纯代码闭环
            return super().solve_problem(user_prompt, on_thought_cb, on_code_cb, on_finish_cb, on_geom_cb)

        # 输出大纲
        if on_thought_cb:
            on_thought_cb(f"📋 课题：{topic}")
            for s in steps:
                on_thought_cb(f"  ├─ 步骤 {s['num']}: {s['title']}" f"（💡 {s.get('hint_for_teacher', '')}）")

        # ========== 阶段 2: 调度子 Agent（支持串行/并行模式）==========
        all_codes: list[str] = []
        all_geom_commands: list = []

        # 将步骤分为可并行组和串行组
        parallel_steps = []
        serial_steps = []
        if self.parallel_execution:
            for step in steps:
                if step.get("parallelizable", False):
                    parallel_steps.append(step)
                else:
                    serial_steps.append(step)
        else:
            serial_steps = steps

        # 执行单个子步骤的通用函数（可在线程池中调用）
        def _execute_single_step(step):
            """执行单个教学步骤，返回 (num, success, code, geom_commands)"""
            num = step.get("num", 0)
            title = step.get("title", "处理中...")
            hint = step.get("hint_for_teacher", "")
            cognitive_level = step.get("cognitive_level", "理解")

            sub_prompt = f"在教学主题「{topic}」的框架下，完成第 {num} 步：{title}。" f"\n教学提示：{hint}"

            # 注入教学法约束到子步骤（Bloom 层级行为指导）
            if self._pedagogical_builder:
                step_constraint = self._pedagogical_builder.build_step_execution_constraint(
                    step_title=title,
                    cognitive_level=cognitive_level,
                    hint=hint,
                )
                sub_prompt += f"\n\n{step_constraint}"

            agent_key = self._pick_sub_agent(title, hint)
            agent_name = agent_key
            if hasattr(self, "agent_registry") and self.agent_registry:
                sub_info = self.agent_registry.agents.get(agent_key)
            else:
                sub_info = None

            if on_thought_cb:
                on_thought_cb(f"\n{'─' * 20}\n📖 第 {num} 步：{title}")
                on_thought_cb(f"  🎯 调度：{agent_name}")
                if hint:
                    on_thought_cb(f"  💡 提示：{hint}")

            # 通过消息总线广播本步骤的意图（仅用于可观测性）。
            # [P1 修复] 这里原先发的是 TASK_REQUEST：MessageRouter 收到后会**同步**调用
            # 目标 Agent 的 solve_problem（agent_message.py:373→392→427），而下面第
            # 1374 行又直接调了一次 —— 每个子任务被执行两遍（双份 token 花费、
            # 代码与几何命令重复回传）。总线路径产出的 TASK_RESULT 全仓没有任何订阅者，
            # 所以真正的执行路径是下面的直调；总线上行降级为 NOTIFICATION（只记日志）。
            if self._message_bus:
                from mathlab.core.agent_message import MessageType

                self.send_message(
                    receiver_id=agent_key,
                    msg_type=MessageType.NOTIFICATION,
                    content=f"[Step {num}] 计划派发: {title} -> {agent_name}",
                    step_num=num,
                    cognitive_level=cognitive_level,
                    topic=topic,
                    conversation_id=self._conversation_id,
                )

            if sub_info is None:
                if on_thought_cb:
                    on_thought_cb(f"  ⚠️ 子 Agent「{agent_key}」未注册，正在自行执行...")

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
                    return (
                        num,
                        True,
                        result.get("code", ""),
                        result.get("geom_commands", []),
                    )
                return (num, False, "", [])

            sub_agent = sub_info["instance"]

            # 收集子 Agent 的输出（前缀标记以示区分）
            step_result = {"success": False, "code": "", "geom": []}

            def make_sub_thought_cb(step_num):
                def _cb(text):
                    if on_thought_cb:
                        on_thought_cb(f"  [Step {step_num}] {text}")

                return _cb

            def make_sub_code_cb():
                def _cb(code):
                    if on_code_cb:
                        on_code_cb(code)
                    step_result["code"] = code

                return _cb

            def make_sub_finish_cb():
                def _cb(success, content):
                    step_result["success"] = success
                    if success and content:
                        step_result["code"] = content

                return _cb

            def make_sub_geom_cb():
                def _cb(cmds):
                    step_result["geom"].extend(cmds)
                    if on_geom_cb:
                        on_geom_cb(cmds)

                return _cb

            try:
                sub_result = sub_agent.solve_problem(
                    sub_prompt,
                    on_thought_cb=make_sub_thought_cb(num),
                    on_code_cb=make_sub_code_cb(),
                    on_finish_cb=make_sub_finish_cb(),
                    on_geom_cb=make_sub_geom_cb(),
                )
                if isinstance(sub_result, dict) and sub_result.get("status") == "ok":
                    step_result["success"] = True
                    step_result["code"] = sub_result.get("code", "")
                    step_result["geom"].extend(sub_result.get("geom_commands", []))
            except Exception as e:
                if on_thought_cb:
                    on_thought_cb(f"  ❌ 子 Agent「{agent_name}」执行异常: {e}")

            # 通过消息总线发送任务进度消息
            if self._message_bus:
                from mathlab.core.agent_message import MessageType

                self.send_message(
                    receiver_id="broadcast",
                    msg_type=MessageType.TASK_PROGRESS,
                    content=f"步骤 {num} 完成: {title} ({'成功' if step_result['success'] else '失败'})",
                    step_num=num,
                    success=step_result["success"],
                    conversation_id=self._conversation_id,
                )

            return (
                num,
                step_result["success"],
                step_result["code"],
                step_result["geom"],
            )

        # 并行执行可并行步骤
        if parallel_steps:
            if on_thought_cb:
                on_thought_cb(f"🚀 启动并行执行模式：{len(parallel_steps)} 个独立步骤同时调度...")

            from concurrent.futures import ThreadPoolExecutor, as_completed

            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                future_to_step = {executor.submit(_execute_single_step, step): step for step in parallel_steps}
                parallel_results = {}
                for future in as_completed(future_to_step):
                    step = future_to_step[future]
                    try:
                        num, success, code, geom_cmds = future.result()
                        parallel_results[num] = (success, code, geom_cmds)
                        if on_thought_cb:
                            if success:
                                on_thought_cb(f"  ✅ 第 {num} 步完成 (并行)")
                            else:
                                on_thought_cb(f"  ⚠️ 第 {num} 步未能产出完整结果 (并行)")
                    except Exception as e:
                        if on_thought_cb:
                            on_thought_cb(f"  ❌ 并行步骤异常: {e}")

            # 按 step num 排序收集结果
            for num in sorted(parallel_results.keys()):
                success, code, geom_cmds = parallel_results[num]
                all_geom_commands.extend(geom_cmds)
                if success and code:
                    all_codes.append(code)

        # 串行执行依赖步骤
        for step in serial_steps:
            num, success, code, geom_cmds = _execute_single_step(step)
            all_geom_commands.extend(geom_cmds)
            if success and code:
                all_codes.append(code)
                if on_thought_cb:
                    on_thought_cb(f"  ✅ 第 {num} 步完成")
            else:
                if on_thought_cb:
                    on_thought_cb(f"  ⚠️ 第 {num} 步未能产出完整结果，继续下一步")

        # ========== 阶段 3: 汇总 + 教学质量评估 ==========
        final_code = "\n\n# ---- Planner 聚合代码 ----\n" + "\n\n".join(all_codes)
        if on_thought_cb:
            on_thought_cb(f"\n{'─' * 20}\n🏁 教研组已完成所有教学步骤！")

        # 教学质量评估闭环：评估生成内容并反馈
        quality_report = None
        if self._quality_evaluator:
            quality_report = self._run_quality_evaluation(final_code, user_prompt, plan, on_thought_cb)

        if on_finish_cb:
            on_finish_cb(True, final_code)
        result = {
            "status": "ok",
            "code": final_code,
            "topic": topic,
            "steps_executed": len(steps),
            "geom_commands": all_geom_commands,
        }
        if quality_report:
            result["quality_report"] = quality_report
        return result

    def _run_quality_evaluation(
        self,
        content: str,
        user_prompt: str,
        plan: dict,
        on_thought_cb=None,
    ) -> dict:
        """执行教学质量评估并生成报告。

        评估三维度：内容理解、上下文连贯性、教学设计。
        如果评估不通过，将改进反馈注入到后续 Agent 对话中。
        """
        try:
            from mathlab.core.pedagogical_engine import QualityDimension

            reports = self._quality_evaluator.evaluate(
                content=content,
                user_prompt=user_prompt,
                plan=plan,
            )
            overall = self._quality_evaluator.get_overall_score(reports)

            if on_thought_cb:
                dim_names = {
                    QualityDimension.CONTENT_UNDERSTANDING: "内容理解",
                    QualityDimension.CONTEXT_COHERENCE: "连贯性",
                    QualityDimension.PEDAGOGICAL_DESIGN: "教学设计",
                }
                on_thought_cb(f"\n📊 教学质量评估完成（总分: {overall:.0%}）:")
                for dim, report in reports.items():
                    icon = "✅" if report.passed else "❌"
                    name = dim_names.get(dim, dim.value)
                    on_thought_cb(
                        f"  {icon} {name}: {report.score:.0%}" + (f" — {report.issues[0]}" if report.issues else "")
                    )

            # 序列化报告
            return {
                "overall_score": overall,
                "dimensions": {dim.value: report.to_dict() for dim, report in reports.items()},
            }
        except Exception as e:
            logger.error(f"教学质量评估失败: {e}")
            return None


class GeometryAgent(BaseMathAgent):
    def __init__(self, ai_manager, model_override=None, resource_config=None, student_model=None):
        super().__init__(
            ai_manager,
            model_override=model_override,
            resource_config=resource_config or ResourceConfig.for_agent("GeometryAgent"),
            student_model=student_model,
        )
        self.system_prompt = """你是一个【2D 解析几何与代数专家】。
你的任务是编写 Python 代码，调用 numpy 和 scipy 解决数学问题，并利用以下画板 API 在交互几何画板上作图：

可用的画板 API（坐标均以浮点数传入，无需 import）：
- draw_point(x, y, name=None)      在 (x,y) 画点，可指定标签
- draw_segment(p1, p2)             画线段（p1/p2 可以是坐标元组如 (x1,y1) 或 draw_point 返回的字典）
- draw_circle(cx, cy, r)            以 (cx,cy) 为圆心、r 为半径画圆
- draw_line(x1, y1, x2, y2)        过两点画直线
- draw_ellipse(cx, cy, rx, ry)     以 (cx,cy) 为中心、rx/ry 为半轴画椭圆（退化为圆近似）
- draw_polygon([(x1,y1), ...])     画多边形，参数为坐标元组的列表
- clear_canvas()                    清空画板

别名：add_point / add_segment / add_circle / add_line / add_ellipse / add_polygon 功能同上。
当画图需求出现时，务必在代码中调用上述 API，它们会将图形同步到用户的交互画板上。
请通过 Thought, Action, Observation 闭环进行。"""


class DataVizAgent(BaseMathAgent):
    def __init__(self, ai_manager, model_override=None, resource_config=None, student_model=None):
        super().__init__(
            ai_manager,
            model_override=model_override,
            resource_config=resource_config or ResourceConfig.for_agent("DataVizAgent"),
            student_model=student_model,
        )
        # 强制将大模型的注意力集中在生成 ECharts 字典上
        self.system_prompt = """你是一个【高级数据可视化专家 (DataVizAgent)】。
你的任务是根据用户的需求，生成极具科技感、配色高级的交互式图表。

【系统环境与限制】
1. 宿主环境已经集成了 Apache ECharts 5.5（支持 gl/3D）。
2. 你绝对不能使用 matplotlib, seaborn 或 plotly！
3. 你必须且只能使用环境内置的渲染桥接器：`mathlab.plugins.echarts_viewer.bridge`。

【代码模板标准】
你的 Action 代码必须严格遵循以下结构：
```python
import numpy as np
from mathlab.plugins.echarts_viewer.bridge import render_chart

# 1. 在这里进行数据计算（如生成随机数、计算3D曲面矩阵等）
# ...

# 2. 严格按照 ECharts Option 标准构建字典
options = {
    "backgroundColor": "transparent", # 保持背景透明以适配主线深色主题
    "tooltip": {"trigger": "item"},
    "series": [
        # 你的数据系列
    ]
}

# 3. 发送给前端渲染
render_chart(options)
```
请通过 Thought 和 Action 闭环来完成任务。要求图表配色具有 Cyberpunk 或暗黑科技感（如深紫、荧光蓝）。"""
