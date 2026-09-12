import os
import platform
import sys
import traceback

# PyInstaller打包后路径处理
if getattr(sys, "frozen", False):
    # exe运行模式
    # ONEDIR模式下：sys.executable 是 dist/MathLab/MathLab.exe
    # 资源文件被打包到 dist/MathLab/mathlab/ 下
    exe_dir = os.path.dirname(sys.executable)
    application_path = os.path.join(exe_dir, "mathlab")
    _CRASH_LOG_DIR = exe_dir

    # 修复 QtWebEngineProcess 找不到 PySide6 内部 DLL 的系统错误弹窗
    # 在 ONEDIR 模式下，PySide6 在 exe_dir 下（与 exe 同级）
    pyside_dir = os.path.join(exe_dir, "PySide6")
    if os.path.exists(pyside_dir):
        os.environ["PATH"] = pyside_dir + os.pathsep + os.environ.get("PATH", "")
        os.environ["QTWEBENGINEPROCESS_PATH"] = os.path.join(pyside_dir, "QtWebEngineProcess.exe")
    # _MEIPASS 仅在 ONEFILE 模式下存在
    elif hasattr(sys, "_MEIPASS"):
        pyside_dir = os.path.join(sys._MEIPASS, "PySide6")
        os.environ["PATH"] = pyside_dir + os.pathsep + os.environ.get("PATH", "")
        os.environ["QTWEBENGINEPROCESS_PATH"] = os.path.join(pyside_dir, "QtWebEngineProcess.exe")
else:
    # 开发模式
    application_path = os.path.dirname(os.path.abspath(__file__))
    _CRASH_LOG_DIR = application_path

mathlab_dir = application_path
sys.path.insert(0, application_path)


def _find_resource(*rel_parts: str) -> str:
    """跨打包布局解析 mathlab 包内资源文件的绝对路径。

    兼容以下布局，按顺序探测，返回第一个存在的候选：
    - PyInstaller 6.x ONEDIR：资源在 ``<exe_dir>/_internal/mathlab/`` 下（即 sys._MEIPASS）
    - PyInstaller 5.x ONEDIR：资源在 ``<exe_dir>/mathlab/`` 下
    - PyInstaller ONEFILE：资源在 ``sys._MEIPASS/mathlab/`` 下
    - 开发模式：资源在 ``mathlab/`` 源码目录下（即本文件的所在目录）

    Args:
        *rel_parts: 相对 mathlab 包根目录的路径片段，如 ("ui", "styles.qss")。

    Returns:
        第一个存在的候选路径；若都不存在，返回最可能的候选以便日志报错。
    """
    candidates: list = []
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", None)
        if base:
            # PyInstaller 6.x ONEDIR (_internal) 与 ONEFILE（临时解包目录）
            candidates.append(os.path.join(base, "mathlab", *rel_parts))
        # PyInstaller 5.x ONEDIR：数据文件与 exe 同级
        candidates.append(os.path.join(os.path.dirname(sys.executable), "mathlab", *rel_parts))
    # 开发模式：main.py 就在 mathlab/ 目录内
    candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), *rel_parts))
    for cand in candidates:
        if os.path.exists(cand):
            return cand
    return candidates[0]


def _show_error_dialog(message):
    """在 GUI 线程中显示错误对话框（console=False 时用户唯一能看到错误的方式）"""
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        # 确保有 QApplication 实例
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)

        msg_box = QMessageBox()
        msg_box.setIcon(QMessageBox.Critical)
        msg_box.setWindowTitle("MathLab 启动失败")
        msg_box.setText(message)
        msg_box.exec()
    except Exception:
        # 如果 Qt 也失败了，就只能写日志了
        pass


def _write_crash_log(exc_type, exc_value, exc_tb):
    """将启动阶段的致命错误写入崩溃日志（exe 同级目录），确保 console=False 时也能看到错误"""
    crash_file = os.path.join(_CRASH_LOG_DIR, "crash.log")
    tb_str = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    from datetime import datetime

    with open(crash_file, "a", encoding="utf-8") as f:
        f.write(f"\n[{datetime.now()}]\n")
        f.write("=" * 60 + "\n")
        f.write("MathLab 启动崩溃报告\n")
        f.write(f"Python: {sys.version}\n")
        f.write(f"Platform: {sys.platform}\n")
        f.write(f"Executable: {sys.executable}\n")
        f.write("=" * 60 + "\n\n")
        f.write(tb_str)
    # 同时打印到 stderr（开发模式可见）
    print(tb_str, file=sys.stderr)

    # 在 GUI 模式下显示错误对话框
    _show_error_dialog(
        f"MathLab 启动失败！\n\n"
        f"错误信息: {exc_value}\n\n"
        f"详细日志已保存到:\n{crash_file}\n\n"
        f"请检查日志文件以获取更多信息。"
    )


# ── 第一步：最早期初始化全局日志系统 ──────────────────────────────────────────
# 必须在任何其他 mathlab 模块导入之前完成，确保所有初始化过程都被记录
try:
    from mathlab.utils.logger import get_logger, setup_logger

    setup_logger()
    logger = get_logger(__name__)

    # ── 启动时清理旧缓存文件（避免占用 C 盘）───────────────────────────────
    from mathlab.utils.logger import cleanup_old_logs, cleanup_temp_files

    # 清理 7 天前的旧日志
    old_logs_deleted = cleanup_old_logs(max_age_days=7)
    if old_logs_deleted > 0:
        logger.info(f"已清理 {old_logs_deleted} 个过期日志文件")

    # 清理系统临时目录下的 mathlab 相关临时文件
    temp_files_deleted = cleanup_temp_files()
    if temp_files_deleted > 0:
        logger.info(f"已清理 {temp_files_deleted} 个临时文件")

    logger.info("日志系统初始化完毕，开始加载 MathLab 模块...")
except Exception:
    # 日志系统本身崩溃时，写崩溃日志并退出
    _write_crash_log(*sys.exc_info())
    sys.exit(1)

from mathlab.core.error_manager import install_error_handler  # noqa: E402

install_error_handler()
# ─────────────────────────────────────────────────────────────────────────────

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QFont, QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

# ── 配置 QtWebEngine 缓存（避免占用 C 盘 AppData）───────────────────────────
try:
    from PySide6.QtWebEngineCore import QWebEngineProfile

    # 设置 WebEngine 缓存路径到程序目录下的 webcache/ 文件夹
    web_cache_dir = os.path.join(mathlab_dir, "webcache")
    os.makedirs(web_cache_dir, exist_ok=True)

    # 获取默认配置文件并设置缓存路径
    profile = QWebEngineProfile.defaultProfile()
    profile.setCachePath(web_cache_dir)
    profile.setPersistentStoragePath(web_cache_dir)
    # 设置 HTTP 缓存大小限制为 50MB
    profile.setHttpCacheMaximumSize(50 * 1024 * 1024)
    logger.info(f"QtWebEngine 缓存路径已设置: {web_cache_dir}")
except ImportError:
    pass

from mathlab.ui.main_window import MainWindow  # noqa: E402
from mathlab.utils.version import __version__  # noqa: E402


def main():
    logger.info("正在初始化 QApplication...")
    try:
        # 🚨 2. 开启高 DPI 缩放支持
        if hasattr(Qt, "AA_EnableHighDpiScaling"):
            QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        if hasattr(Qt, "AA_UseHighDpiPixmaps"):
            QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

        app = QApplication(sys.argv)

        # 🚨 修复字体环境：根据不同操作系统注入最完美的无衬线黑体
        sys_os = platform.system()
        if sys_os == "Windows":
            font_family = "Microsoft YaHei"
        elif sys_os == "Darwin":
            font_family = ".AppleSystemUIFont"
        else:
            font_family = "Microsoft YaHei, Noto Sans CJK SC, Ubuntu"

        font = QFont(font_family, 10)
        font.setStyleStrategy(QFont.PreferAntialias)
        app.setFont(font)

        app.setApplicationName("MathLab")
        app.setApplicationVersion(__version__)

        icon_path = _find_resource("resources", "icons", "app_icon.png")
        app.setWindowIcon(QIcon(icon_path))

        try:
            stylesheet_path = _find_resource("ui", "styles.qss")
            with open(stylesheet_path, "r", encoding="utf-8") as f:
                app.setStyleSheet(f.read())
            logger.debug("样式表加载完毕: %s", stylesheet_path)
        except FileNotFoundError:
            logger.warning("样式表文件未找到: %s", stylesheet_path)
        except Exception as e:
            logger.warning("样式表加载失败: %s", e)

        logger.info("正在创建主窗口...")
        # MainWindow.__init__ 内部完成所有引擎初始化、REPL 命名空间注入、
        # 事件监听注册和插件系统启动，消除双重初始化反模式
        window = MainWindow()
        window.show()

        # ── 关闭 PyInstaller Splash Screen ──
        try:
            import pyi_splash

            if pyi_splash.is_alive():
                pyi_splash.close()
                logger.info("已关闭 PyInstaller 启动画面。")
        except ImportError:
            pass

        logger.info("主窗口加载完毕，进入 Qt 事件循环。")
        sys.exit(app.exec())

    except Exception as e:
        logger.critical("系统启动失败: %s", e, exc_info=True)
        _write_crash_log(*sys.exc_info())
        sys.exit(1)


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()

    if multiprocessing.current_process().name != "MainProcess":
        sys.exit(0)  # 避免子进程进 GUI

    # ── 拦截子进程调用 (解决 PyInstaller 无限弹黑窗口闪退问题) ──
    if len(sys.argv) >= 2:
        # 拦截 JupyterLab 的启动 (-m jupyter)
        if sys.argv[1] == "-m" and len(sys.argv) >= 3 and sys.argv[2] == "jupyter":
            # 调整 sys.argv 为 jupyter 期望的格式
            sys.argv = ["jupyter"] + sys.argv[3:]
            from jupyterlab.labapp import main as jupyter_main

            jupyter_main()
            sys.exit(0)
        # 拦截 Jupyter kernel 的启动 (-m ipykernel_launcher)
        if sys.argv[1] == "-m" and len(sys.argv) >= 3 and sys.argv[2] == "ipykernel_launcher":
            from ipykernel import kernelapp

            kernelapp.launch_new_instance()
            sys.exit(0)
        # 拦截我们自己沙盒进程的启动 (sandbox_script.py)
        elif sys.argv[1].endswith("sandbox_script.py"):
            import runpy

            if getattr(sys, "frozen", False):
                runpy.run_module("mathlab.core.sandbox_script", run_name="__main__")
            else:
                runpy.run_path(sys.argv[1], run_name="__main__")
            sys.exit(0)

    # ── 最外层崩溃捕获：确保导入阶段或 main() 之前的错误也能被记录 ──
    try:
        main()
    except Exception:
        _write_crash_log(*sys.exc_info())
        sys.exit(1)
