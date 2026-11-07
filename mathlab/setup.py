import os

from setuptools import find_packages, setup

# 从统一版本管理模块读取版本号
version = "3.8.0"
_version_file = os.path.join(os.path.dirname(__file__), "utils", "version.py")
if os.path.exists(_version_file):
    with open(_version_file, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("__version__"):
                version = line.split("=")[1].strip().strip('"').strip("'")
                break

setup(
    name="mathlab",
    version=version,
    description="Interactive Mathematics and AI Teaching Software",
    author="MathLab Team",
    packages=find_packages(),
    # ── 运行依赖（与根 requirements.txt / mathlab/requirements.txt 同一套下界）──
    # 此前这里只列 7 项，把 Jupyter / openai / matplotlib / pythonnet 全放进
    # extras，导致 `pip install mathlab` 装出的包跑不起来（CI 却按根清单安装，
    # 本地与 CI 判定分叉）。运行必需的一律进 install_requires。
    install_requires=[
        "PySide6>=6.6.0",
        "numpy>=1.26",
        "sympy>=1.12",
        "scipy>=1.11",
        "scikit-learn>=1.3",
        "matplotlib>=3.8",
        "pyqtgraph>=0.13",
        "openai>=1.0",
        "PyYAML>=6.0",
        "jupyterlab>=4.0",
        "jupyter_client>=8.0",
        "ipykernel>=6.0",
        "jupyter_server>=2.0",
        "requests>=2.31",
        "pythonnet>=3.0",
        "markdown>=3.5",
        "Pygments>=2.17",
        "jedi>=0.19",
        "networkx>=3.1",
        "psutil>=5.9",
    ],
    # ── 可选功能依赖 ─────────────────────────────────────────────────
    # 安装示例: pip install mathlab[ai]
    extras_require={
        "ai": [
            "scikit-learn>=1.3",
            "onnxruntime>=1.16",
        ],
        "neural": [
            "torch>=2.0",
        ],
        "visualization": [
            "matplotlib>=3.8",
            "pyqtgraph>=0.13",
        ],
        "full": [
            "scikit-learn>=1.3",
            "onnxruntime>=1.16",
            "matplotlib>=3.8",
            "pyqtgraph>=0.13",
        ],
    },
    entry_points={
        "console_scripts": [
            "mathlab=mathlab.main:main",
        ],
    },
    include_package_data=True,
    zip_safe=False,
)
