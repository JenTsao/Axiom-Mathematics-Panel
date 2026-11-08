"""P1 回归：C# 惰性加载、异常钩子链、Qt 绑定、依赖清单、沙箱双扫描一致性。

其中沙箱一致性是本文件的重点：``sandbox_security.py``（父进程）与
``sandbox_script.py``（子进程）刻意各持一份规则副本（子进程不保证能 import
mathlab），任何一侧单独改动都会形成防线缺口。此处同时锁定「集合相等」与
「同一段代码两侧判定相同」，把 AGENTS.md §8.6 的人工约定变成自动化断言。
"""

import ast
import inspect
import re
import sys
from pathlib import Path

import pytest

from mathlab.core import sandbox_script as child_scanner
from mathlab.core.sandbox_security import CodeSecurityScanner as ParentScanner

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[3]
_TEST_PACKAGES = {"pytest", "pytest-qt", "pytest-cov"}
_REQ_RE = re.compile(r"^([A-Za-z0-9_.-]+)\s*(.*)$")


def _requirements(path):
    """解析 requirements 文件，返回 {规范化包名: 版本约束}。"""
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = _REQ_RE.match(line)
        assert match, f"无法解析依赖行: {line!r}"
        name, spec = match.group(1).lower(), match.group(2).strip()
        if name not in _TEST_PACKAGES:
            result[name] = spec
    return result


def _setup_install_requires():
    """从 setup.py 的 setup() 调用里静态提取 install_requires。"""
    tree = ast.parse((_REPO_ROOT / "mathlab" / "setup.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "setup":
            for keyword in node.keywords:
                if keyword.arg == "install_requires":
                    return _requirements_from_literals([e.value for e in keyword.value.elts])
    raise AssertionError("setup.py 中找不到 install_requires")


def _requirements_from_literals(items):
    result = {}
    for item in items:
        match = _REQ_RE.match(item)
        assert match, f"无法解析依赖行: {item!r}"
        result[match.group(1).lower()] = match.group(2).strip()
    return result


# ── 依赖清单一致性 ──────────────────────────────────────────────────────────


class TestDependencyParity:
    def test_three_manifests_have_same_runtime_packages(self):
        root = _requirements(_REPO_ROOT / "requirements.txt")
        packaged = _requirements(_REPO_ROOT / "mathlab" / "requirements.txt")
        setup_reqs = _setup_install_requires()
        assert root == packaged, "根清单与打包清单不一致"
        assert root == setup_reqs, "setup.py install_requires 与清单不一致"

    def test_pyside6_lower_bound_matches_everywhere(self):
        root = _requirements(_REPO_ROOT / "requirements.txt")
        packaged = _requirements(_REPO_ROOT / "mathlab" / "requirements.txt")
        setup_reqs = _setup_install_requires()
        assert root["pyside6"] == packaged["pyside6"] == setup_reqs["pyside6"] == ">=6.6.0"

    def test_every_runtime_dependency_is_pinned(self):
        root = _requirements(_REPO_ROOT / "requirements.txt")
        assert root
        assert all(spec.startswith(">=") for spec in root.values()), "存在无版本下界的运行依赖"


# ── 沙箱父子双扫描 ──────────────────────────────────────────────────────────


class TestSandboxScannerParity:
    def test_banned_sets_are_identical(self):
        assert ParentScanner.BANNED_MODULES == child_scanner.BANNED_MODULES_AST
        assert ParentScanner.BANNED_FUNCTIONS == child_scanner.BANNED_FUNCTIONS_AST
        assert ParentScanner.BANNED_ATTRIBUTES == child_scanner.BANNED_ATTRIBUTES_AST
        assert ParentScanner.DANGEROUS_REFERENCES == child_scanner.DANGEROUS_REFERENCES_AST
        assert ParentScanner.SAFE_DUNDER_STRINGS == child_scanner.SAFE_DUNDER_STRINGS

    def test_runtime_denied_builtins_are_subset_of_static_ban(self):
        assert child_scanner.DANGEROUS_BUILTINS <= ParentScanner.BANNED_FUNCTIONS

    @pytest.mark.parametrize(
        "code, expected",
        [
            ("import os", False),
            ("from pathlib import Path", False),
            ("eval('1')", False),
            ("__import__('os')", False),
            ("f = open", False),
            ("type(1)", False),
            ("x.__class__", False),
            ("obj.__loader__", False),
            ("s = '__imp' + 'ort__'", False),
            ("import math", True),
            ("1 + 1", True),
        ],
    )
    def test_both_sides_reach_same_verdict(self, code, expected):
        from mathlab.core.sandbox_security import is_code_safe

        parent_ok = is_code_safe(code)[0]
        child_ok = child_scanner._scan_code_safety(code)[0]
        assert parent_ok == child_ok == expected, (code, parent_ok, child_ok)


# ── C# 几何引擎惰性化 ───────────────────────────────────────────────────────


class TestCSGeometryLazyLoading:
    def test_module_has_no_eager_instance(self):
        from mathlab.core import cs_geometry_engine as engine

        assert not hasattr(engine, "cs_geometry"), "模块级 cs_geometry 实例必须移除"
        assert callable(engine.get_cs_geometry)
        assert isinstance(engine.CS_GEOMETRY_AVAILABLE, bool)

        tree = ast.parse(inspect.getsource(engine))
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                func = node.value.func
                assert getattr(func, "id", None) != "CsGeometryEngine", "模块级不得实例化引擎"

    def test_getter_never_raises_without_dotnet(self):
        from mathlab.core import cs_geometry_engine as engine

        result = engine.get_cs_geometry()
        assert result is None or isinstance(result, engine.CsGeometryEngine)

    def test_downstream_importers_use_getter(self):
        import mathlab.core.geometry_engine as ge
        import mathlab.core.models.conic as conic
        import mathlab.core.models.locus as locus
        from mathlab.core.cs_geometry_engine import get_cs_geometry

        assert not hasattr(ge, "cs_geometry")
        assert conic.get_cs_geometry is get_cs_geometry
        assert locus.get_cs_geometry is get_cs_geometry


# ── 异常钩子链 ──────────────────────────────────────────────────────────────


class TestExceptionHookChaining:
    def test_install_chains_and_is_idempotent(self, monkeypatch):
        from mathlab.core import error_manager as em

        calls = []

        def previous(*args):
            calls.append(args)

        monkeypatch.setattr(sys, "excepthook", previous)
        monkeypatch.setattr(em, "_previous_excepthook", None)

        em.install_error_handler()
        assert sys.excepthook is em.global_exception_handler
        assert em._previous_excepthook is previous

        em.install_error_handler()
        assert em._previous_excepthook is previous, "重复安装不得把自身记为前一个钩子"

        em.global_exception_handler(KeyboardInterrupt, KeyboardInterrupt(), None)
        assert len(calls) == 1, "Ctrl+C 应委托原钩子后直接返回，不弹崩溃报告"


# ── Qt 绑定优先级 ───────────────────────────────────────────────────────────


def test_qt_binding_prefers_pyside6():
    from mathlab.core import ai_engine_worker as worker

    source = inspect.getsource(worker)
    # 兼容 import 形态与 importlib 形态：只要 PySide6 排在 PyQt5 之前即可
    assert source.index("PySide6.QtCore") < source.index("PyQt5.QtCore")
