"""P2 回归：i18n 文案收口、死代码移除、面板显隐重构。

本轮目标是可维护性而非行为变更，因此断言集中在「不变式」上：
命令面板文案不得再出现裸中文、被引用的属性必须真实存在、
面板显隐的公开 API 与调用方式保持不变。

全部用源码 / AST 检查，不导入 Qt 模块，便于在无 PySide6 的环境下运行。
"""

import ast
import json
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CJK = re.compile(r"[一-鿿]")
# 词边界：避免把 float("inf") 里的 t( 误判为 t() 调用
_T_CALL = re.compile(r"(?<![A-Za-z0-9_])t\(\s*[\"']([a-z0-9_.]+)[\"']")
_LOG_FUNCS = {"debug", "info", "warning", "error", "critical", "exception", "log"}


def _read(rel):
    return (_REPO_ROOT / "mathlab" / rel).read_text(encoding="utf-8")


def _leaves(node, prefix=""):
    out = set()
    for key, value in node.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            out |= _leaves(value, path + ".")
        else:
            out.add(path)
    return out


def _locale_leaves(name):
    return _leaves(json.loads((_REPO_ROOT / "mathlab" / "locale" / name).read_text(encoding="utf-8")))


def _user_visible_strings(source):
    """返回模块内面向用户的字符串字面量（排除 docstring 与 logger 调用参数）。"""
    tree = ast.parse(source)
    doc_ids = {
        id(node.value) for node in ast.walk(tree) if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
    }
    log_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "attr", None) or getattr(func, "id", None)
            if name in _LOG_FUNCS:
                for arg in node.args:
                    log_roots.add(id(arg))
                for kw in node.keywords:
                    log_roots.add(id(kw.value))
    found = []

    class Visitor(ast.NodeVisitor):
        def visit_Constant(self, node):
            if id(node) not in doc_ids and id(node) not in log_roots and isinstance(node.value, str):
                found.append(node.value)

    Visitor().visit(tree)
    return found


# ── 命令面板文案收口 ────────────────────────────────────────────────────────


class TestCommandPaletteI18n:
    def test_no_bare_cjk_in_commands_mixin(self):
        bare = [s for s in _user_visible_strings(_read("ui/_mixin_commands.py")) if _CJK.search(s)]
        assert bare == [], f"命令面板仍有裸中文: {bare}"

    def test_all_command_keys_exist_in_locales(self):
        keys = set(_T_CALL.findall(_read("ui/_mixin_commands.py")))
        assert keys, "未解析到任何 t() 调用"
        zh, en = _locale_leaves("zh.json"), _locale_leaves("en.json")
        assert not sorted(keys - zh), f"zh.json 缺失 key: {sorted(keys - zh)}"
        assert not sorted(keys - en), f"en.json 缺失 key: {sorted(keys - en)}"

    def test_locale_stays_symmetric(self):
        zh, en = _locale_leaves("zh.json"), _locale_leaves("en.json")
        assert zh == en, f"双语 key 不对称: {sorted(zh ^ en)[:10]}"


# ── 死代码移除 ──────────────────────────────────────────────────────────────


class TestDeadCodeRemoved:
    def test_no_dangling_ai_panel_references(self):
        tree = ast.parse(_read("ui/_mixin_ai.py"))
        attrs = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and getattr(node.value, "id", None) == "self"
        }
        assert "ai_dock" not in attrs, "ai_dock 是从未创建的死属性"
        assert "ai_panel" not in attrs, "ai_panel 是从未创建的死属性"
        assert "ai_tools_panel" in attrs, "应改用真实的 ai_tools_panel"

    def test_no_eager_code_editor_on_main_window(self):
        source = _read("ui/main_window.py")
        assert "AutocompleteTextEdit" not in source, "main_window 不应再创建闲置 code_editor"
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if getattr(target, "attr", None) == "code_editor":
                        pytest.fail("MainWindow 仍在创建 self.code_editor")

    def test_toggle_api_shape_unchanged(self):
        tree = ast.parse(_read("ui/_mixin_ui_setup.py"))
        methods = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name.startswith("toggle_")
        }
        expected = {
            "toggle_algebra_panel",
            "toggle_properties_panel",
            "toggle_console",
            "toggle_algo_vis_panel",
            "toggle_ai_tools_panel",
            "toggle_function_explorer",
            "toggle_math_console",
            "toggle_notebook_panel",
        }
        assert expected <= methods, f"缺公开 API: {sorted(expected - methods)}"
        assert "_toggle_widget" in {
            node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
        }, "缺共享实现 _toggle_widget"

    def test_toggle_helper_raises_only_when_asked(self):
        source = _read("ui/_mixin_ui_setup.py")
        match = re.search(r"def _toggle_widget\(.*?\n(.*?)(?=\n    def )", source, re.S)
        assert match, "未找到 _toggle_widget 实现"
        body = match.group(1)
        assert "raise_()" in body
        assert "raise_first" in body
        # raise_ 必须被 raise_first 条件包住，不能无条件执行
        assert "if raise_first:" in body


# ── i18n 刷新完整性 ─────────────────────────────────────────────────────────


def test_retranslate_ui_covers_all_central_tabs():
    source = _read("ui/_mixin_dialogs.py")
    for key in ("main_window.mini_geogebra", "main_window.jupyter_workspace"):
        assert key in source, f"retranslate_ui 未刷新 {key}"
    for action in ("notebook_action", "function_explorer_action", "math_console_action"):
        assert f"self.{action}.setText" in source, f"retranslate_ui 未刷新 {action}"


def test_tab_titles_use_i18n():
    source = _read("ui/_mixin_ui_setup.py")
    assert 'Mini GeoGebra"' not in source, "Tab 标题仍硬编码"
    assert 'Jupyter 工作区"' not in source, "Jupyter Tab 标题仍硬编码"
