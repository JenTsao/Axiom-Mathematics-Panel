__version__ = "3.8.0"
__author__ = "MathLab Team"

# Lazy imports: avoid triggering the full Qt import chain at package load time.
# Tests and scripts can import submodules directly without side effects.

__all__ = [
    "MainWindow",
    "GeometryEngine",
    "CASProvider",
    "AlgoAnimator",
    "PythonREPL",
    "AIManager",
    "SandboxManager",
    "ProjectManager",
]


def __getattr__(name):
    if name == "MainWindow":
        from .ui import MainWindow

        return MainWindow
    elif name == "GeometryEngine":
        from .core import GeometryEngine

        return GeometryEngine
    elif name == "CASProvider":
        from .core import CASProvider

        return CASProvider
    elif name == "AlgoAnimator":
        from .core import AlgoAnimator

        return AlgoAnimator
    elif name == "PythonREPL":
        from .core import PythonREPL

        return PythonREPL
    elif name == "AIManager":
        from .core import AIManager

        return AIManager
    elif name == "SandboxManager":
        from .core import SandboxManager

        return SandboxManager
    elif name == "ProjectManager":
        from .data import ProjectManager

        return ProjectManager
    raise AttributeError(f"module 'mathlab' has no attribute {name!r}")
