import os
import queue
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from typing import Any, Dict, Optional

try:
    from jupyter_client import KernelManager
except ImportError:
    KernelManager = None  # type: ignore

try:
    from mathlab.utils.logger import get_logger

    logger = get_logger(__name__)
except ImportError:
    import logging

    logger = logging.getLogger(__name__)

from mathlab.core.sandbox_security import is_code_safe

# ============================================================
#  JupyterSandbox — 进程级隔离的代码执行沙箱
# ============================================================


class JupyterSandbox:
    """
    进程级隔离的 Jupyter 执行沙盒
    支持状态保持、超时中断、富文本/图像输出捕获、内存监控
    """

    # 默认内存上限（MB），超过时自动重启内核
    _MEMORY_LIMIT_MB = 512

    def __init__(self) -> None:
        if KernelManager is None:
            raise ImportError("jupyter_client 未安装，无法启动 JupyterSandbox。")

        self.km = KernelManager(kernel_name="python3")
        self.km.start_kernel()
        self.kc = self.km.client()
        self.kc.start_channels()

        # 等待内核启动
        try:
            self.kc.wait_for_ready(timeout=10)
            logger.info("Jupyter 内核已成功启动并在后台待命。")
        except RuntimeError:
            logger.warning("Jupyter 内核启动超时。")

        # 初始化内存监控
        try:
            from mathlab.utils.config_manager import get_config

            jupyter_cfg = get_config("jupyter", {})
            self._memory_limit_mb = jupyter_cfg.get("memory_limit_mb", self._MEMORY_LIMIT_MB)
        except Exception:
            self._memory_limit_mb = self._MEMORY_LIMIT_MB

        self._psutil_available = False
        try:
            import psutil

            self._psutil_available = True
            self._psutil = psutil
        except ImportError:
            self._psutil = None
            logger.debug("psutil 未安装，内存监控功能已降级。")

    def execute_code(self, code: str, timeout: int = 5) -> Dict[str, Any]:
        """
        同步执行代码并收集所有输出
        """
        # 1. 静态安全检查
        safe, msg = is_code_safe(code)
        if not safe:
            return {"status": "error", "traceback": [msg], "text": "", "images": []}

        # 2. 执行前检查内存占用
        self._check_memory()

        # 3. 发送给后台 Jupyter 内核执行
        self.kc.execute(code)

        output_text: list = []
        output_images: list = []
        error_traceback: list = []
        status = "ok"

        # 4. 阻塞等待并捕获输出 (具备超时熔断机制)
        try:
            while True:
                # 从 iopub 频道获取执行结果
                msg = self.kc.get_iopub_msg(timeout=timeout)  # type: ignore
                msg_type = msg["header"]["msg_type"]
                content = msg["content"]

                if msg_type == "stream":
                    # 捕获 print() 输出
                    output_text.append(content["text"])

                elif msg_type == "execute_result" or msg_type == "display_data":
                    # 捕获表达式结果或图片 (例如 matplotlib 输出)
                    if "text/plain" in content["data"]:
                        output_text.append(content["data"]["text/plain"])
                    if "image/png" in content["data"]:
                        output_images.append(content["data"]["image/png"])

                elif msg_type == "error":
                    # 捕获代码报错信息
                    status = "error"
                    error_traceback.extend(content["traceback"])

                elif msg_type == "status" and content["execution_state"] == "idle":
                    # 内核执行完毕并回到空闲状态
                    break

        except queue.Empty:
            status = "timeout"
            error_traceback.append(f"执行超时 (超过 {timeout} 秒被强制中断)。已防止陷入死循环。")
            # 发生严重超时（死循环）时，直接强杀并重启内核
            self.restart_kernel()

        return {
            "status": status,
            "text": "".join(output_text),
            "images": output_images,
            "traceback": error_traceback,
        }

    def restart_kernel(self) -> None:
        """强杀并重启内核（用于清理内存或打破死循环）"""
        logger.info("正在重启 Jupyter 内核...")
        # [BUG修复] 关闭旧客户端通道，防止 ZeroMQ socket 泄漏
        if hasattr(self, "kc") and self.kc:
            try:
                self.kc.stop_channels()
            except Exception:
                logger.warning("关闭旧内核通道时出现异常", exc_info=True)
        self.km.restart_kernel(now=True)
        self.kc = self.km.client()
        self.kc.start_channels()
        self.kc.wait_for_ready(timeout=10)

    def shutdown(self) -> None:
        """关闭内核并释放所有资源"""
        try:
            if hasattr(self, "kc") and self.kc:
                self.kc.stop_channels()
        except Exception:
            logger.warning("关闭内核通道时出现异常", exc_info=True)
        try:
            if hasattr(self, "km") and self.km:
                self.km.shutdown_kernel(now=True)
        except Exception:
            logger.warning("关闭内核时出现异常", exc_info=True)
        logger.info("Jupyter 内核已关闭。")

    def get_memory_usage_mb(self) -> Optional[float]:
        """获取当前内核进程的内存占用（MB），psutil 不可用时返回 None"""
        if not self._psutil_available or self._psutil is None:
            return None
        try:
            pid = self.km.kernel.pid  # type: ignore
            if pid is None:
                return None
            proc = self._psutil.Process(pid)
            # 包含子进程的内存
            mem = proc.memory_info().rss
            for child in proc.children(recursive=True):
                try:
                    mem += child.memory_info().rss
                except (self._psutil.NoSuchProcess, self._psutil.AccessDenied):
                    pass
            return mem / (1024 * 1024)
        except Exception:
            return None

    def _check_memory(self) -> None:
        """执行前检查内存，超限时自动重启内核"""
        mem_mb = self.get_memory_usage_mb()
        if mem_mb is not None and mem_mb > self._memory_limit_mb:
            logger.warning(
                "内核内存占用 %.1f MB 超过限制 %d MB，自动重启内核。",
                mem_mb,
                self._memory_limit_mb,
            )
            self.restart_kernel()


# ============================================================
#  JupyterManager — JupyterLab 服务器进程管理器
# ============================================================


def _find_free_port(start: int = 8888, end: int = 8999) -> int:
    """在指定范围内寻找可用端口"""
    for port in range(start, end + 1):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    # 兜底：让 OS 分配
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class JupyterManager:
    """
    JupyterLab 服务器进程管理器

    负责在后台启动/停止 JupyterLab 服务器子进程，
    并提供 URL 供 QWebEngineView 加载。

    用法::

        mgr = JupyterManager()
        mgr.start(timeout=45)
        url = mgr.url
        ...
        mgr.stop()
    """

    def __init__(self) -> None:
        # 从配置中读取端口范围和超时
        try:
            from mathlab.utils.config_manager import get_config

            jupyter_cfg = get_config("jupyter", {})
            port_start = jupyter_cfg.get("port_start", 8888)
            port_end = jupyter_cfg.get("port_end", 8999)
            self._default_timeout = jupyter_cfg.get("start_timeout", 30)
        except Exception:
            port_start, port_end = 8888, 8999
            self._default_timeout = 30

        self.port: int = _find_free_port(port_start, port_end)
        self._process: Optional[subprocess.Popen] = None
        self._token: str = "mathlab-embedded"
        self._url: str = ""
        self._lock = threading.Lock()
        # 子进程输出的环形缓冲：供启动失败时诊断（防止管道阻塞见 _drain_process_output）
        self._output_tail: deque = deque(maxlen=200)

    @property
    def url(self) -> str:
        """返回 JupyterLab 的完整访问 URL"""
        if self._url:
            return self._url
        return f"http://127.0.0.1:{self.port}/lab?token={self._token}"

    def start(self, timeout: int = 45) -> bool:
        """
        在后台启动 JupyterLab 服务器子进程。

        Args:
            timeout: 等待服务器就绪的最大秒数。

        Returns:
            True 表示服务器已就绪，False 表示启动失败。
        """
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                logger.info("JupyterLab 服务器已在运行中。")
                return True

            # 构造启动命令
            # 在 PyInstaller 打包环境下，sys.executable 指向 exe 本身，
            # 但 main.py 中有拦截逻辑，会正确处理 -m jupyter 调用
            cmd = [
                sys.executable,
                "-m",
                "jupyter",
                "lab",
                "--no-browser",
                "--port",
                str(self.port),
                "--ServerApp.token",
                self._token,
                "--ServerApp.password",
                "",
                "--ServerApp.allow_origin",
                "*",
                "--ServerApp.disable_check_xsrf",
                "True",
            ]

            # PyInstaller 打包环境下的特殊处理
            env = os.environ.copy()
            if getattr(sys, "frozen", False):
                env["PYINSTALLER_FROZEN"] = "1"

            try:
                logger.info("正在启动 JupyterLab 服务器 (端口 %s)...", self.port)
                self._process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    env=env,
                    # Windows 下隐藏控制台窗口
                    creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0),
                )
            except FileNotFoundError:
                logger.error("无法找到 jupyter 命令，请确认 jupyterlab 已安装。")
                return False
            except Exception as e:
                logger.error("启动 JupyterLab 失败: %s", e)
                return False

            # 启动输出排空线程：JupyterLab 启动日志量大，若 PIPE 无人读取，
            # 管道缓冲区写满后子进程会被阻塞，表现为永远无法就绪直至超时
            self._output_tail.clear()
            threading.Thread(
                target=self._drain_process_output,
                name="JupyterLabOutputDrain",
                daemon=True,
            ).start()

            # 等待服务器就绪
            if self._wait_for_ready(timeout):
                self._url = f"http://127.0.0.1:{self.port}/lab?token={self._token}"
                logger.info("JupyterLab 服务器已就绪: %s", self._url)
                return True
            else:
                logger.error("JupyterLab 服务器启动超时。")
                self._log_output_tail()
                self.stop()
                return False

    def _drain_process_output(self) -> None:
        """持续读取 JupyterLab 子进程输出，防止管道缓冲区写满导致子进程阻塞。

        JupyterLab 启动时会输出大量日志；若 stdout=PIPE 无人读取，Windows 管道
        缓冲区（约 64KB）写满后子进程的 print 会阻塞，服务器永远无法就绪，
        最终表现为"启动超时"。此守护线程持续排空管道，并把最近输出保留在
        环形缓冲中供失败诊断。
        """
        process = self._process
        if process is None or process.stdout is None:
            return
        try:
            for raw_line in iter(process.stdout.readline, b""):
                line = raw_line.decode("utf-8", errors="replace").rstrip()
                if line:
                    self._output_tail.append(line)
                    logger.debug("JupyterLab: %s", line)
        except Exception:
            pass
        finally:
            try:
                process.stdout.close()
            except Exception:
                pass

    def _log_output_tail(self, max_lines: int = 30) -> None:
        """将子进程最近输出写入日志，便于诊断启动失败原因。"""
        if not self._output_tail:
            return
        lines = list(self._output_tail)[-max_lines:]
        logger.error("JupyterLab 最近输出（最后 %d 行）:\n%s", len(lines), "\n".join(lines))

    def _wait_for_ready(self, timeout: int) -> bool:
        """轮询 HTTP 端口，等待 JupyterLab 服务器响应"""
        import urllib.error
        import urllib.parse
        import urllib.request

        deadline = time.time() + timeout
        check_url = f"http://127.0.0.1:{self.port}/api/status"

        # 安全检查：验证 URL 协议和主机
        parsed_url = urllib.parse.urlparse(check_url)
        if parsed_url.scheme not in ("http", "https") or parsed_url.hostname not in (
            "localhost",
            "127.0.0.1",
        ):
            logger.error("不允许的 URL 访问: %s", check_url)
            return False

        last_progress_log = time.time()
        while time.time() < deadline:
            # 检查进程是否已退出
            if self._process is not None and self._process.poll() is not None:
                logger.error("JupyterLab 进程意外退出，退出码: %s", self._process.poll())
                self._log_output_tail()
                return False

            try:
                req = urllib.request.Request(check_url)
                with urllib.request.urlopen(req, timeout=2) as resp:  # nosec B310 - 已验证仅访问本地地址
                    if resp.status == 200:
                        return True
            except (urllib.error.URLError, ConnectionError, OSError):
                pass
            except Exception:
                pass

            # 周期性输出等待进度，避免长时间静默
            now = time.time()
            if now - last_progress_log >= 10:
                logger.info(
                    "仍在等待 JupyterLab 服务器就绪... (已等待 %d/%d 秒)",
                    int(timeout - (deadline - now)),
                    timeout,
                )
                last_progress_log = now

            time.sleep(0.5)

        return False

    def stop(self) -> None:
        """停止 JupyterLab 服务器子进程"""
        with self._lock:
            if self._process is None:
                return

            try:
                # 优先发送 SIGTERM 优雅关闭
                self._process.terminate()
                try:
                    self._process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    # 强制杀死
                    self._process.kill()
                    self._process.wait(timeout=3)
                logger.info("JupyterLab 服务器已停止。")
            except Exception as e:
                logger.warning("停止 JupyterLab 服务器时出错: %s", e)
            finally:
                self._process = None
                self._url = ""

    def is_running(self) -> bool:
        """检查服务器进程是否仍在运行"""
        return self._process is not None and self._process.poll() is None


# ============================================================
#  全局单例管理
# ============================================================

_jupyter_sandbox_instance: Optional[JupyterSandbox] = None
_sandbox_lock = threading.Lock()


def get_jupyter_sandbox() -> JupyterSandbox:
    """获取全局唯一的 JupyterSandbox 实例（懒加载）"""
    global _jupyter_sandbox_instance
    if _jupyter_sandbox_instance is None:
        with _sandbox_lock:
            if _jupyter_sandbox_instance is None:
                _jupyter_sandbox_instance = JupyterSandbox()
    return _jupyter_sandbox_instance


def shutdown_jupyter_sandbox() -> None:
    """关闭全局 JupyterSandbox 实例，释放内核进程资源。

    应在应用退出时调用，防止内核进程泄漏。
    """
    global _jupyter_sandbox_instance
    if _jupyter_sandbox_instance is not None:
        with _sandbox_lock:
            if _jupyter_sandbox_instance is not None:
                try:
                    _jupyter_sandbox_instance.shutdown()
                except Exception as e:
                    logger.warning("关闭 JupyterSandbox 时出错: %s", e)
                _jupyter_sandbox_instance = None
