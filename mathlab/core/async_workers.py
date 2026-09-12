import multiprocessing
import threading
import traceback

from PySide6.QtCore import QCoreApplication, QObject, QRunnable, QThreadPool, Signal

from mathlab.utils.logger import get_logger

logger = get_logger(__name__)


class WorkerSignals(QObject):
    """定义通用异步任务的信号 (QRunnable 本身不能发信号，必须借由 QObject)"""

    finished = Signal(object)  # 任务成功完成，返回结果字典/对象
    error = Signal(str)  # 任务失败，返回错误堆栈
    progress = Signal(int)  # (预留) 任务进度 0-100


class _CallbackRelay(QObject):
    """后台线程 → 创建线程（通常是主线程）的回调中继。

    PySide6 中信号连接普通 Python 函数时，回调会在“发射信号的线程”直接执行；
    若 worker 线程直接跑 UI 更新代码属于未定义行为。通过本中继对象（归属于
    主线程）中转，Qt 会自动以 QueuedConnection 把回调投递到主线程执行。
    """

    invoke = Signal(object)  # 参数为无参可调用对象

    def __init__(self):
        super().__init__()
        self.invoke.connect(self._execute)

    def _execute(self, fn):
        try:
            fn()
        except Exception:
            logger.exception("异步任务回调执行异常")


class TaskWorker(QRunnable):
    """
    统一的底层执行单元
    你可以将任何阻塞函数抛给它，无需再为每个功能写单独的 QThread
    """

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        # 设置自动删除，执行完后释放内存
        self.setAutoDelete(True)

    def run(self):
        try:
            # 动态执行传入的阻塞型函数
            result = self.fn(*self.args, **self.kwargs)
            self.signals.finished.emit(result)
        except Exception as e:
            err_msg = traceback.format_exc()
            logger.exception(f"异步任务 {self.fn.__name__} 执行异常:\n{err_msg}")
            self.signals.error.emit(str(e))


class TaskManager:
    """
    全局异步任务调度中心 (单例模式)

    注：本类不继承 QObject。任务信号由各 Worker 自带的
    WorkerSignals(QObject) 承载，调度中心自身不需要 Qt 对象；
    若继承 QObject，单例在第二次实例化时会触发 libshiboken 的
    "You can't initialize a QObject object twice" RuntimeError，
    导致第二次之后的所有异步任务提交直接失败。
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init_pool()
        return cls._instance

    def __init__(self):
        # 单例：初始化已在 __new__ 中一次性完成
        pass

    def _init_pool(self):
        self.thread_pool = QThreadPool.globalInstance()
        # 获取系统 CPU 核心数，保留一个核心给主 UI 线程，防止机器整体卡顿
        max_threads = max(1, multiprocessing.cpu_count() - 1)
        self.thread_pool.setMaxThreadCount(max_threads)
        # 用于防抖与任务覆盖：跟踪各组是否有任务运行及挂起的最新请求
        self._running_groups = set()
        self._pending_requests = {}
        # 保护共享状态的线程锁
        self._state_lock = threading.Lock()
        # 保持运行中 Worker 的强引用：TaskWorker 为 QRunnable，
        # 若 Python 侧失去引用会被 GC 回收，连带 signals 对象销毁导致回调静默丢失
        self._active_workers = set()
        # 主线程回调中继：确保归属主线程，无论 TaskManager 首次在哪个线程被实例化
        self._relay = _CallbackRelay()
        app = QCoreApplication.instance()
        if app is not None and self._relay.thread() is not app.thread():
            self._relay.moveToThread(app.thread())

        logger.info(f"TaskManager 启动，最大并发线程数: {max_threads}")

    def submit(self, fn, on_success=None, on_error=None, group_id=None, *args, **kwargs):
        """
        核心 API：将阻塞任务提交至后台线程池

        :param fn: 需要执行的阻塞函数 (如 cas_provider.integrate)
        :param on_success: 成功后的回调槽函数 (UI 更新操作应放这里)
        :param on_error: 失败后的回调槽函数
        :param group_id: 任务分组 ID。提供此 ID 可防抖与抽搐拦截。
                         当同组任务正在执行时，新的请求会覆盖旧的排队请求，只执行最新一帧。
        :param args/kwargs: 传递给 fn 的参数
        """
        if group_id is not None:
            with self._state_lock:
                if group_id in self._running_groups:
                    # 已有同组任务正在执行，覆盖挂起队列中的请求
                    self._pending_requests[group_id] = {
                        "fn": fn,
                        "on_success": on_success,
                        "on_error": on_error,
                        "args": args,
                        "kwargs": kwargs,
                    }
                    return
                else:
                    self._running_groups.add(group_id)
            self._submit_internal(group_id, fn, on_success, on_error, *args, **kwargs)
        else:
            self._submit_internal(None, fn, on_success, on_error, *args, **kwargs)

    def _submit_internal(self, group_id, fn, on_success, on_error, *args, **kwargs):
        worker = TaskWorker(fn, *args, **kwargs)
        # 持有强引用直至任务结束，防止 Worker/信号被 GC 提前回收
        with self._state_lock:
            self._active_workers.add(worker)

        def _release_worker():
            with self._state_lock:
                self._active_workers.discard(worker)

        def success_interceptor(result):
            try:
                if on_success:
                    # 经由中继对象排队回主线程执行，保证 UI 回调线程安全
                    self._relay.invoke.emit(lambda: on_success(result))
            finally:
                _release_worker()
                self._check_pending(group_id)

        def error_interceptor(err):
            try:
                if on_error:
                    self._relay.invoke.emit(lambda: on_error(err))
            finally:
                _release_worker()
                self._check_pending(group_id)

        worker.signals.finished.connect(success_interceptor)
        worker.signals.error.connect(error_interceptor)

        self.thread_pool.start(worker)
        logger.debug(f"已提交任务 [{fn.__name__}] 至线程池，当前活动线程: {self.thread_pool.activeThreadCount()}")

    def _check_pending(self, group_id):
        if group_id is None:
            return

        with self._state_lock:
            if group_id in self._pending_requests:
                req = self._pending_requests.pop(group_id)
            else:
                self._running_groups.discard(group_id)
                return

        # 在锁外提交新任务
        self._submit_internal(
            group_id,
            req["fn"],
            req["on_success"],
            req["on_error"],
            *req["args"],
            **req["kwargs"],
        )


# ──────────────────────────────────────────────────────────────────────────────
# AI 专用 Worker 类
# 将 AIManager 中的同步 ML 方法包装为异步 QRunnable，防止 UI 阻塞
# ──────────────────────────────────────────────────────────────────────────────


class AIFitWorker(TaskWorker):
    """散点拟合 AI Worker：支持线性和多项式回归"""

    def __init__(self, ai_manager, points, fit_type="linear", degree=2):
        self._ai_manager = ai_manager
        self._points = points
        self._fit_type = fit_type
        self._degree = degree

        # 根据 fit_type 选择对应的函数，传给父类初始化
        # 父类 TaskWorker.__init__ 已创建 self.signals，无需重复初始化
        if fit_type == "polynomial":
            fn = ai_manager.fit_polynomial_regression
            super().__init__(fn, points, degree)
        else:
            fn = ai_manager.fit_linear_regression
            super().__init__(fn, points)

        self.setAutoDelete(True)

    def run(self):
        try:
            if self._fit_type == "polynomial":
                result = self._ai_manager.fit_polynomial_regression(self._points, self._degree)
            else:
                result = self._ai_manager.fit_linear_regression(self._points)
            self.signals.finished.emit(result)
        except Exception as e:
            err_msg = traceback.format_exc()
            logger.exception(f"AIFitWorker 执行异常:\n{err_msg}")
            self.signals.error.emit(str(e))


class AIClusterWorker(TaskWorker):
    """聚类分析 AI Worker：支持 KMeans 和 DBSCAN"""

    def __init__(self, ai_manager, points, algorithm="kmeans", **kwargs):
        self._ai_manager = ai_manager
        self._points = points
        self._algorithm = algorithm
        self._kwargs = kwargs

        super().__init__(self._execute)
        self.setAutoDelete(True)

    def _execute(self):
        if self._algorithm == "dbscan":
            eps = self._kwargs.get("eps", 0.5)
            min_samples = self._kwargs.get("min_samples", 5)
            return self._ai_manager.cluster_dbscan(self._points, eps, min_samples)
        else:
            n_clusters = self._kwargs.get("n_clusters", 3)
            return self._ai_manager.cluster_kmeans(self._points, n_clusters)


class AIRecognizeWorker(TaskWorker):
    """手写数字识别 AI Worker：调用 ONNX 模型进行推理"""

    def __init__(self, ai_manager, image_data):
        self._ai_manager = ai_manager
        self._image_data = image_data

        super().__init__(ai_manager.recognize_digit, image_data)
        self.setAutoDelete(True)


class AIGeneratePointsWorker(TaskWorker):
    """AI 生成随机数据点 Worker"""

    def __init__(self, ai_manager, n=10, x_range=(0, 100), y_range=(0, 100)):
        self._ai_manager = ai_manager
        self._n = n
        self._x_range = x_range
        self._y_range = y_range

        super().__init__(ai_manager.generate_random_points, n, x_range, y_range)
        self.setAutoDelete(True)
