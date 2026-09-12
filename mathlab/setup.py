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
    # ── 核心依赖（运行必须） ──────────────────────────────────────────
    install_requires=[
        "PySide6>=6.5.0",
        "sympy>=1.12",
        "numpy>=1.26",
        "scipy>=1.11",
        "networkx>=3.1",
        "jedi>=0.19",
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
