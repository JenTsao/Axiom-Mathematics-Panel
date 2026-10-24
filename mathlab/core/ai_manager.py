"""AI 调度中心与数学 Agent 基类。

历史包袱提示：本文件一度膨胀到 1664 行，已拆出两块：

* ``mathlab/core/ai_engine_worker.py`` —— Qt/openai 兼容层 + 流式工作线程
* ``mathlab/core/planner_agent.py`` —— 教研组长 ``PlannerAgent``

本文件保留 ``AIManager``（客户端与统计方法）、``ReasoningCache``、``ResourceConfig``、
``BaseMathAgent`` 以及 ``GeometryAgent`` / ``DataVizAgent`` 两个薄壳子类。
"""

import importlib.util
import threading
from enum import Enum
from typing import Optional

import numpy as np

from mathlab.core.agent_memory import get_file_memory
from mathlab.core.ai_engine_worker import (
    OPENAI_AVAILABLE,
    QT_AVAILABLE,
    AIEngineWorker,
    AIState,
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    QObject,
    QThread,
    RateLimitError,
    Signal,
    describe_api_error,
)
from mathlab.core.ai_tools import GEOMETRY_DRAW_TOOL, execute_math_task
from mathlab.core.memory_manager import ChatMemoryManager
from mathlab.core.skill_manager import SkillLibrary
from mathlab.utils.logger import get_logger

if importlib.util.find_spec("sklearn") is not None:
    SKLEARN_AVAILABLE = True
else:
    SKLEARN_AVAILABLE = False
import json
import os

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

logger = get_logger(__name__)

# 向后兼容：历史代码与测试从 ai_manager 导入这些名字，re-export 以免改一处挂一片。
# 其中 Qt / openai 系列来自 ai_engine_worker（兼容层的单一真源）。
__all__ = [
    "AIEngineWorker",
    "AIProvider",
    "AIRequestConfig",
    "AIState",
    "AIManager",
    "APIConnectionError",
    "APIStatusError",
    "APITimeoutError",
    "AuthenticationError",
    "BaseMathAgent",
    "DataVizAgent",
    "GeometryAgent",
    "OPENAI_AVAILABLE",
    "ONNX_AVAILABLE",
    "OpenAI",
    "QT_AVAILABLE",
    "QObject",
    "QThread",
    "RateLimitError",
    "REQUESTS_AVAILABLE",
    "ReasoningCache",
    "ResourceConfig",
    "Signal",
    "TORCH_AVAILABLE",
    "describe_api_error",
]


def __getattr__(name: str):
    """PEP 562 延迟转发：``PlannerAgent`` 已迁到 ``planner_agent`` 模块。

    ``planner_agent`` 在顶层 import 本模块（取 ``BaseMathAgent`` / ``ResourceConfig``），
    所以本模块**不能**在顶层反向 import，否则成环。这里保留旧导入路径
    ``from mathlab.core.ai_manager import PlannerAgent``，等真正访问时再解析。
    """
    if name in ("PlannerAgent", "StepResultCollector"):
        import importlib

        module = importlib.import_module(".planner_agent", __package__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# HTTP 客户端超时与重试：openai SDK 默认 read timeout 是 600 秒，
# 网关挂住时用户要等 10 分钟才看到错误；这里收紧到"连接快、读取宽松、失败少量重试"。
AI_CONNECT_TIMEOUT = 10.0
AI_READ_TIMEOUT = 120.0
AI_WRITE_TIMEOUT = 30.0
AI_POOL_TIMEOUT = 10.0
AI_MAX_RETRIES = 2


# 工具 Schema 统一从 ai_tools.py 导入（消除重复定义）
DRAW_TOOL_SCHEMA = GEOMETRY_DRAW_TOOL  # 别名，供 quiz_panel 等模块使用


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
        # 文件式记忆系统（Codex 风格）：跨会话持久化的 Markdown 记忆，读取零副作用
        self.file_memory = get_file_memory()
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

        # 注入文件式记忆（长期记忆 / 项目指令 / 近期日志），无内容时返回空串
        try:
            memory_block = self.file_memory.get_context_block()
        except Exception as exc:  # noqa: BLE001 - 记忆层故障不得阻断对话
            logger.warning("装配文件式记忆失败，本次请求跳过: %s", exc)
            memory_block = ""
        if memory_block:
            dynamic_system_prompt = (
                dynamic_system_prompt + "\n\n" + memory_block if dynamic_system_prompt else memory_block
            )

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


class SolveCallbacks:
    """把四个可选回调收敛成一个可空安全调用的对象。

    原 ``solve_problem`` 里散落着十来处 ``if on_xxx_cb: on_xxx_cb(...)``，
    既拉长行数又抬高圈复杂度；这里统一做 None 检查。
    """

    __slots__ = ("_thought", "_code", "_finish", "_geom")

    def __init__(self, thought=None, code=None, finish=None, geom=None):
        self._thought = thought
        self._code = code
        self._finish = finish
        self._geom = geom

    def thought(self, text: str) -> None:
        """推送一条思考过程文本。"""
        if self._thought:
            self._thought(text)

    def code(self, code: str) -> None:
        """推送一次生成的代码。"""
        if self._code:
            self._code(code)

    def finish(self, success: bool, content: str) -> None:
        """推送完成事件。"""
        if self._finish:
            self._finish(success, content)

    def geom(self, commands: list) -> None:
        """推送一批几何绘图命令。"""
        if self._geom:
            self._geom(commands)


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

    # 对话历史裁剪：保留 system + 初始 user（前 2 条）+ 最近 3 轮对话（6 条），
    # 避免 ReAct 重试时上下文无限增长（BUG 6 修复）
    MAX_HISTORY_MSGS = 8

    def solve_problem(
        self,
        user_prompt: str,
        on_thought_cb=None,
        on_code_cb=None,
        on_finish_cb=None,
        on_geom_cb=None,
    ):
        """ReAct 推理闭环：缓存 → 装配提示 → 生成代码 → 沙箱执行 → 失败重试。

        Args:
            user_prompt: 用户提出的数学问题。
            on_thought_cb: 思考过程回调（可选）。
            on_code_cb: 生成代码回调（可选）。
            on_finish_cb: 完成回调 ``(success, content)``（可选）。
            on_geom_cb: 几何绘图命令回调（可选）。

        Returns:
            结果字典；成功时含 ``status="ok"`` 与 ``code``。
        """
        cbs = SolveCallbacks(on_thought_cb, on_code_cb, on_finish_cb, on_geom_cb)

        # ============== 前置校验：未配置 API 客户端时直接失败，避免 NoneType 崩溃 ==============
        if getattr(self.ai_manager, "client", None) is None:
            cbs.thought("❌ 未配置 AI API Key，无法启动推理闭环。")
            cbs.finish(False, "未配置 API Key")
            return {"status": "failed", "error": "未配置 API Key"}

        # ============== 0. 推理缓存检索阶段 ==============
        cached = self._reasoning_cache.get(user_prompt)
        if cached is not None:
            return self._replay_cached_result(cached, cbs)

        # ============== 1. 装配系统提示（RAG + 自适应 + 教学法 + 文件记忆）==============
        messages = self._build_initial_messages(user_prompt, cbs)

        # ============== 2. ReAct 重试循环 ==============
        for step in range(self.max_steps):
            cbs.thought(f"⚙️ 正在生成代码 (第 {step + 1} 次尝试)...")

            code_content = self._llm_generate_code(messages)
            cbs.code(code_content)

            execution_result = self._execute_code(code_content)

            if execution_result.get("status") == "ok":
                return self._finalize_success(user_prompt, code_content, execution_result, cbs)

            error_msg = execution_result.get("error", "未知错误")
            cbs.thought(f"❌ 代码报错 (第 {step + 1} 次尝试), 正在修正...\n报错内容: {error_msg}")
            self._append_failure_feedback(messages, code_content, error_msg)

        cbs.finish(False, "超出最大重试次数")

        # 记录失败互动（自适应学习：追踪薄弱点）
        if self.student_model and self._adaptive_engine:
            self._record_student_interaction(user_prompt, success=False)

        return {"status": "failed", "error": "超出最大重试次数"}

    # ------------------------------------------------------------------
    # solve_problem 的各个环节（拆开以压低单函数圈复杂度）
    # ------------------------------------------------------------------
    @staticmethod
    def _replay_cached_result(cached: dict, cbs: "SolveCallbacks") -> dict:
        """推理缓存命中：直接把历史结果喂给回调，跳过 LLM 调用。"""
        cbs.thought("📦 推理缓存命中！直接复用历史结果，跳过 LLM 调用。")
        cbs.code(cached.get("code", ""))
        geom_cmds = cached.get("geom_commands", [])
        if geom_cmds:
            cbs.geom(geom_cmds)
        cbs.finish(True, cached.get("code", ""))
        return cached

    def _build_initial_messages(self, user_prompt: str, cbs: "SolveCallbacks") -> list:
        """装配首轮 messages：系统提示 + 用户任务。"""
        cbs.thought("🔍 正在检索本地技能库记忆...")

        skill_context = self._build_skill_context(user_prompt, cbs)
        adaptive_context = self._build_adaptive_context(user_prompt, cbs)
        pedagogical_context = self._build_pedagogical_context(user_prompt)
        memory_context = self._build_memory_context()

        system_prompt = f"""{self.system_prompt}
{memory_context}
{skill_context}
{adaptive_context}
{pedagogical_context}
不要输出多余的 Markdown，必须且只能将代码写在 ```python 块中。"""

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"任务：{user_prompt}"},
        ]

    def _build_skill_context(self, user_prompt: str, cbs: "SolveCallbacks") -> str:
        """RAG：从本地技能库检索历史成功经验，拼成提示片段。"""
        relevant_skills = self.skill_lib.retrieve_relevant_skills(user_prompt)
        if not relevant_skills:
            return ""

        context = (
            "\n【本地技能库中的成功经验】\n"
            "以下是你过去成功写过的类似代码，你可以直接复用或参考它们的 API 调用方式：\n"
        )
        for s in relevant_skills:
            context += f"💡 意图: {s['intent']}\n```python\n{s['code']}\n```\n\n"
        cbs.thought(f"⚡ 唤醒了 {len(relevant_skills)} 条历史成功经验！")
        return context

    def _build_adaptive_context(self, user_prompt: str, cbs: "SolveCallbacks") -> str:
        """自适应教学策略（依赖学生认知模型，没有则为空串）。"""
        if not self._adaptive_engine:
            return ""

        context = self._adaptive_engine.build_adaptive_prompt(user_prompt)
        profile = self.student_model.get_profile_summary()
        cbs.thought(
            f"🎓 已加载学生认知画像："
            f"认知层级={profile['cognitive_level']}，"
            f"偏好={profile['learning_style']}，"
            f"掌握度={profile['avg_mastery']}"
        )
        return context

    def _build_pedagogical_context(self, user_prompt: str) -> str:
        """教学法约束（Bloom/ZPD/UDL/Socratic），没有学生模型则为空串。"""
        if self.student_model is None:
            return ""

        from mathlab.core.pedagogical_engine import PedagogicalPromptBuilder

        builder = PedagogicalPromptBuilder(self.student_model)
        return builder.build_code_generation_constraint(user_prompt)

    def _build_memory_context(self) -> str:
        """文件式记忆上下文；记忆层故障不得阻断推理闭环。"""
        try:
            file_memory = getattr(self.ai_manager, "file_memory", None) or get_file_memory()
            return file_memory.get_context_block()
        except Exception as exc:  # noqa: BLE001 - 记忆层是旁路，坏了就当没有
            logger.warning("装配文件式记忆失败，本次推理跳过: %s", exc)
            return ""

    @staticmethod
    def _execute_code(code_content: str) -> dict:
        """把代码丢进沙箱执行，异常统一收敛成 ``{"status": "error"}``。"""
        try:
            raw = execute_math_task(code_content)
            if isinstance(raw, dict):
                return raw
            return json.loads(raw)
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _finalize_success(
        self,
        user_prompt: str,
        code_content: str,
        execution_result: dict,
        cbs: "SolveCallbacks",
    ) -> dict:
        """沙箱执行成功后的收尾：回传几何命令 + 后台提炼 + 写缓存 + 记录互动。"""
        geom_commands = execution_result.get("geom_commands", [])
        if geom_commands:
            cbs.geom(geom_commands)

        cbs.thought(f"✅ 沙箱执行成功！输出:\n{execution_result.get('output', '')}")

        # 后台"自我提炼"：把这次跑通的代码抽象成通用函数入库
        threading.Thread(
            target=self._reflect_and_save_skill,
            args=(user_prompt, code_content),
            daemon=True,
        ).start()

        cache_result = {
            "status": "ok",
            "code": code_content,
            "result": execution_result.get("output", ""),
            "geom_commands": geom_commands,
        }
        self._reasoning_cache.put(user_prompt, cache_result)

        if self.student_model and self._adaptive_engine:
            self._record_student_interaction(user_prompt, success=True)

        cbs.finish(True, code_content)
        return cache_result

    def _append_failure_feedback(self, messages: list, code_content: str, error_msg: str) -> None:
        """把报错信息追加进对话历史，让 AI 下一次尝试自行修正。"""
        messages.append({"role": "assistant", "content": f"```python\n{code_content}\n```"})
        messages.append(
            {
                "role": "user",
                "content": f"执行失败，报错如下：\n{error_msg}\n请修正代码。",
            }
        )
        if len(messages) > self.MAX_HISTORY_MSGS:
            messages[:] = messages[:2] + messages[-(self.MAX_HISTORY_MSGS - 2) :]

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
