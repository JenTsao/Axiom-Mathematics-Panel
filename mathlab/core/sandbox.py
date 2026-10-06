import json
import os
import signal
import subprocess
import sys
import threading
import time
from queue import Queue

from mathlab.core.sandbox_security import is_code_safe
from mathlab.utils.logger import get_logger

logger = get_logger(__name__)

# 强烈建议在环境依赖中添加 psutil 库（pip install psutil）
# 如果没有安装，我们将使用降级方案，但 psutil 是跨平台精准监控内存的最佳手段
try:
    import psutil
except ImportError:
    psutil = None


class SandboxProcess:
    def __init__(self, max_memory_mb=512, max_time_seconds=60, max_cpu_percent=80):
        self.process = None
        self.running = False
        self.output_queue = Queue()
        self.error_queue = Queue()
        self.result_queue = Queue()
        self.max_memory_mb = max_memory_mb  # 严格限制内存 (MB)
        self.max_time_seconds = max_time_seconds  # 严格限制执行时间 (秒)
        self.max_cpu_percent = max_cpu_percent  # 严格限制 CPU 占比 (%)
        self._watchdog_triggered = False
        self._watchdog_error_msg = ""

    def configure(self, max_memory_mb=None, max_time_seconds=None, max_cpu_percent=None):
        """运行时动态调整资源限制"""
        if max_memory_mb is not None:
            self.max_memory_mb = max_memory_mb
        if max_time_seconds is not None:
            self.max_time_seconds = max_time_seconds
        if max_cpu_percent is not None:
            self.max_cpu_percent = max_cpu_percent

    def configure_from(self, resource_config):
        """从 ResourceConfig 对象批量配置资源限制"""
        if resource_config:
            self.max_memory_mb = resource_config.max_memory_mb
            self.max_time_seconds = resource_config.max_time_seconds
            self.max_cpu_percent = resource_config.max_cpu_percent

    def _read_output(self, pipe, queue):
        try:
            while True:
                line = pipe.readline()
                if not line:
                    break
                queue.put(line.decode("utf-8", errors="replace"))
        except Exception:
            pass

    def _monitor_watchdog(self, timeout):
        """
        核心看门狗线程：主动轮询子进程的 CPU 时间、CPU 占比与物理内存开销
        一旦超过阈值，立刻从外部施加硬核毁灭（SIGKILL / taskkill），彻底解决任何死循环

        性能优化：自适应轮询间隔
        - 前 5 秒高频轮询 (100ms)：快速捕获瞬时爆发的死循环/内存泄漏
        - 5 秒后低频轮询 (500ms)：降低长时任务的后台 CPU 开销
        """
        start_time = time.time()
        while self.running and self.process and self.process.poll() is None:
            current_time = time.time()
            elapsed_time = current_time - start_time

            # 1. 检查时间超时（防止任何级别的 CPU 死循环）
            if elapsed_time > timeout:
                self._watchdog_triggered = True
                self._watchdog_error_msg = f"Execution timed out after {timeout} seconds."
                self.terminate()
                break

            # 2. 检查内存占用和 CPU 占比（防止旨在撑爆内存或 CPU 的死循环）
            if psutil:
                try:
                    parent = psutil.Process(self.process.pid)
                    total_memory = parent.memory_info().rss
                    total_cpu_percent = parent.cpu_percent(interval=None)

                    for child in parent.children(recursive=True):
                        total_memory += child.memory_info().rss
                        total_cpu_percent += child.cpu_percent(interval=None)

                    total_memory_mb = total_memory / (1024 * 1024)

                    # 内存超限检查
                    if total_memory_mb > self.max_memory_mb:
                        self._watchdog_triggered = True
                        self._watchdog_error_msg = (
                            f"Memory limit exceeded: Used {total_memory_mb:.1f}MB " f"/ Max {self.max_memory_mb}MB."
                        )
                        self.terminate()
                        break

                    # CPU 占比超限检查（持续高于阈值才触发，避免瞬时尖峰误杀）
                    if total_cpu_percent > self.max_cpu_percent:
                        # 二次采样确认：等待 0.2 秒后再次检查
                        time.sleep(0.2)
                        recheck_cpu = parent.cpu_percent(interval=None)
                        for child in parent.children(recursive=True):
                            recheck_cpu += child.cpu_percent(interval=None)
                        if recheck_cpu > self.max_cpu_percent:
                            self._watchdog_triggered = True
                            self._watchdog_error_msg = (
                                f"CPU limit exceeded: Used {recheck_cpu:.1f}% " f"/ Max {self.max_cpu_percent}%."
                            )
                            self.terminate()
                            break
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            # 自适应轮询间隔：前 5 秒高频，之后降为低频以节省 CPU
            poll_interval = 0.1 if elapsed_time < 5.0 else 0.5
            time.sleep(poll_interval)

    def _start_process(self):
        sandbox_script_path = os.path.join(os.path.dirname(__file__), "sandbox_script.py")
        env = os.environ.copy()
        # [安全修复] 仅保留非空的绝对路径，排除当前目录 '' 和相对路径
        sep = ";" if sys.platform == "win32" else ":"
        safe_paths = [p for p in sys.path if p and os.path.isabs(p)]
        extra_paths = sep.join(safe_paths)
        env["PYTHONPATH"] = f"{env.get('PYTHONPATH', '')}{sep}{extra_paths}".strip(sep)

        creation_flags = 0
        preexec_fn = None
        if sys.platform == "win32":
            creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            preexec_fn = getattr(os, "setsid", None)

        self.process = subprocess.Popen(
            [sys.executable, sandbox_script_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            creationflags=creation_flags,
            preexec_fn=preexec_fn,
            text=True,
        )
        self.running = True

    def run_code(self, code, timeout=None):
        # [P0 安全加固] 执行前先用强扫描器拦截。
        # 此前本方法不做任何检查，唯一的静态防线是子进程 sandbox_script.py 里的弱化副本
        # （缺少 dunder 属性 / 危险名字规则），__subclasses__ 两步式与 getattr(__globals__)
        # 等写法可以直接逃逸。现在父进程先拦一道，子进程内的副本作为最后一道防线。
        is_safe, safety_error = is_code_safe(code)
        if not is_safe:
            logger.warning("沙箱拒绝执行不安全的代码: %s", safety_error.splitlines()[0])
            return {
                "success": False,
                "output": "",
                "error": safety_error,
                "result": None,
            }

        if timeout is None:
            timeout = self.max_time_seconds

        if not self.process or self.process.poll() is not None:
            self._start_process()

        self._watchdog_triggered = False
        self._watchdog_error_msg = ""

        req = json.dumps({"code": code})
        self.process.stdin.write(req + "\n")
        self.process.stdin.flush()

        result_queue = Queue()

        def read_response():
            try:
                line = self.process.stdout.readline()
                if line:
                    result_queue.put(json.loads(line))
            except Exception:
                pass

        reader_thread = threading.Thread(target=read_response, daemon=True)
        reader_thread.start()

        # [修复] 启动独立的看门狗线程统一监控超时和内存，避免主循环重复检查
        watchdog_thread = threading.Thread(target=self._monitor_watchdog, args=(timeout,), daemon=True)
        watchdog_thread.start()

        # 主循环仅等待读取线程完成，超时/内存由看门狗处理
        reader_thread.join(timeout=timeout + 2)

        if self._watchdog_triggered:
            return {
                "success": False,
                "output": "",
                "error": self._watchdog_error_msg,
                "result": None,
            }

        if not result_queue.empty():
            res = result_queue.get()
            return {
                "success": res.get("success", False),
                "output": res.get("output", ""),
                "error": res.get("error", ""),
                "result": None,
            }

        return {
            "success": False,
            "output": "",
            "error": "Sandbox process died unexpectedly",
            "result": None,
        }

    def terminate(self):
        """
        毁灭级终止：不论是多级进程树、C层死循环，全部连根拔起
        """
        if self.process and self.running:
            try:
                if sys.platform == "win32":
                    # Windows下使用 /T 杀死进程树，/F 强制杀死
                    subprocess.call(
                        ["taskkill", "/F", "/T", "/PID", str(self.process.pid)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                else:
                    # Unix下通过向进程组 ID（负的 PID）发送 SIGKILL，全组连带子进程瞬间清除
                    try:
                        killpg = getattr(os, "killpg", None)
                        getpgid = getattr(os, "getpgid", None)
                        sigkill = getattr(signal, "SIGKILL", 9)
                        if killpg and getpgid:
                            killpg(getpgid(self.process.pid), sigkill)
                    except ProcessLookupError:
                        pass  # 进程可能已经退出
                # 等待进程退出以避免僵尸进程和竞态条件
                try:
                    self.process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    pass
            except Exception as e:
                logger.warning("终止沙箱子进程时出错: %s", e)
            finally:
                self.running = False
                self.process = None

    def is_running(self):
        return self.running


class SandboxManager:
    def __init__(self):
        self.sandboxes = {}
        self.sandbox_counter = 0

    def create_sandbox(self, resource_config=None):
        """创建沙箱实例，可选传入 ResourceConfig 配置资源限制"""
        sandbox_id = f"sandbox_{self.sandbox_counter}"
        self.sandbox_counter += 1
        sandbox = SandboxProcess()
        if resource_config:
            sandbox.configure_from(resource_config)
        self.sandboxes[sandbox_id] = sandbox
        return sandbox_id

    def run_in_sandbox(self, sandbox_id, code, timeout=None):
        if sandbox_id not in self.sandboxes:
            return {"success": False, "error": "Sandbox not found"}

        sandbox = self.sandboxes[sandbox_id]
        return sandbox.run_code(code, timeout)

    def terminate_sandbox(self, sandbox_id):
        if sandbox_id in self.sandboxes:
            self.sandboxes[sandbox_id].terminate()

    def destroy_sandbox(self, sandbox_id):
        if sandbox_id in self.sandboxes:
            self.terminate_sandbox(sandbox_id)
            del self.sandboxes[sandbox_id]

    def get_sandbox_status(self, sandbox_id):
        if sandbox_id not in self.sandboxes:
            return None
        return {"running": self.sandboxes[sandbox_id].is_running()}
