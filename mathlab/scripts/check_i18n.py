"""i18n 覆盖检查（UI_SYSTEM_DESIGN.md §7.3，对应 A-09：字符串必须走 t() 与 locale）。

用法：
    python mathlab/scripts/check_i18n.py            # 默认检查，发现问题 exit 1
    python mathlab/scripts/check_i18n.py --report   # 输出 Markdown 明细

三条独立检查：
  I1 缺失 key：AST 扫描 ``mathlab/**/*.py`` 中 ``t("literal", ...)`` 的字面量
     key，与 ``mathlab/locale/*.json`` 求差集 —— 代码用到但 locale 缺失为 FAIL。
  I2 未使用 key（仅 WARN）：locale 中存在但代码未引用的 key（运行时拼接/
     update_i18n.py 生成的 key 可能误报，不作为失败条件）。
  I3 未本地化中文字面量（棘轮）：``mathlab/ui/**.py`` 里没走 ``t()`` 的中文常量。
     I1 只能发现"调了 t() 但 key 不存在"，发现不了"压根没调 t()"，
     这正是历史上 300+ 处裸中文漏网的原因。I3 用 THRESHOLD 只降不升的方式收口。

动态 key（f-string / 变量）无法静态解析，跳过扫描；可加入 ``--report`` 的
``dynamic`` 列表供人工核对。
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

# ── 路径（脚本位于 mathlab/scripts/，仓库根为其父目录的父目录） ──────────────
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = REPO_ROOT / "mathlab"
LOCALE_DIR = SRC_DIR / "locale"

# 只扫描业务代码目录；测试与脚本自身的字面量不计入
SCAN_DIRS: tuple[str, ...] = ("ui", "core", "utils", "widgets", "main.py")

# i18n 查找函数名（与 utils/i18n_manager.py 模块级 ``t`` 一致）
T_FUNC_NAMES: frozenset[str] = frozenset({"t"})

# 已知动态 key 的白名单（人工确认无法静态化的调用点，格式 "file.py:line"）
DYNAMIC_KEY_ALLOWLIST: frozenset[str] = frozenset()

# ── I3：未本地化中文字面量 ─────────────────────────────────────────────────
I3_SCAN_DIR = SRC_DIR / "ui"

# 棘轮阈值：等于当前实测值，任何新增裸中文都会让 CI 变红。
# 收敛方向是按面板批次把它压到 0（改小数字即可，不需要动逻辑）。
# 2026-10 实测 345 处，TOP: _mixin_commands.py(112) / ai_tools_panel.py(71)
# / function_explorer_panel.py(25) / _mixin_ai.py(21) / jupyter_panel.py(19)
I3_UNTRANSLATED_THRESHOLD = 345

_CJK_RE = re.compile(r"[一-鿿]")

# 日志调用的方法名：日志文案面向开发者，按 AGENTS.md §6 不需要本地化
_LOG_METHODS: frozenset[str] = frozenset(
    {"debug", "info", "warning", "warn", "error", "exception", "critical", "log", "fatal"}
)


def _iter_i3_files() -> list[Path]:
    return sorted(p for p in I3_SCAN_DIR.rglob("*.py") if "__pycache__" not in p.parts)


def _is_log_call(node: ast.Call) -> bool:
    """判断是否为 logger.xxx(...) / log.warning(...) 这类日志调用。"""
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr not in _LOG_METHODS:
        return False
    owner = func.value
    if isinstance(owner, ast.Name):
        return owner.id.lower() in {"logger", "log", "logging", "self"}
    return False


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """收集所有 docstring 常量节点的 id，I3 不计文档字符串。"""
    doc_nodes: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            if isinstance(body[0].value.value, str):
                doc_nodes.add(id(body[0].value))
    return doc_nodes


class _CjkVisitor(ast.NodeVisitor):
    """统计未走 t() 的中文字符串常量。

    排除三类噪声：docstring、日志调用参数、以及 ``t()`` 自身的参数。
    """

    def __init__(self, docstrings: set[int]) -> None:
        self.docstrings = docstrings
        self.hits: list[tuple[int, str]] = []

    def visit_Constant(self, node: ast.Constant) -> None:
        if id(node) in self.docstrings:
            return
        value = node.value
        if isinstance(value, str) and _CJK_RE.search(value):
            self.hits.append((node.lineno, value))

    def visit_Call(self, node: ast.Call) -> None:
        if _is_log_call(node):
            return  # 日志文案不计入，整棵子树跳过
        if isinstance(node.func, ast.Name) and node.func.id in T_FUNC_NAMES:
            return  # 已走 t() 的调用不计入
        self.generic_visit(node)


def check_untranslated_cjk() -> tuple[int, dict[str, list[tuple[int, str]]]]:
    """I3：返回 (总数, {相对文件: [(行号, 字面量), ...]})。"""
    total = 0
    per_file: dict[str, list[tuple[int, str]]] = {}
    for path in _iter_i3_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        visitor = _CjkVisitor(_docstring_nodes(tree))
        visitor.visit(tree)
        if visitor.hits:
            rel = str(path.relative_to(SRC_DIR))
            per_file[rel] = visitor.hits
            total += len(visitor.hits)
    return total, per_file


# ── 工具函数 ────────────────────────────────────────────────────────────────
def _iter_py_files() -> list[Path]:
    """收集需要扫描的 Python 文件（SCAN_DIRS 内的 .py，排除 __pycache__）。"""
    files: list[Path] = []
    for entry in SCAN_DIRS:
        target = SRC_DIR / entry
        if target.is_file():
            files.append(target)
        elif target.is_dir():
            files.extend(p for p in sorted(target.rglob("*.py")) if "__pycache__" not in p.parts)
    return files


def _extract_literal_keys(tree: ast.AST, file_path: Path) -> tuple[set[str], list[str]]:
    """AST 遍历，返回 (字面量 key 集合, 动态调用点列表 ["file:line"])。

    匹配形如 ``t("xxx")`` 的调用：函数名为 ``t`` 且第一个位置参数是字符串常量。
    """
    literal_keys: set[str] = set()
    dynamic_calls: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Name) or func.id not in T_FUNC_NAMES:
            continue
        if not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            literal_keys.add(first.value)
        else:
            marker = f"{file_path.name}:{node.lineno}"
            if marker not in DYNAMIC_KEY_ALLOWLIST:
                dynamic_calls.append(marker)
    return literal_keys, dynamic_calls


def _flatten_locale_keys(data: dict[str, object], prefix: str = "") -> set[str]:
    """把嵌套 locale JSON 展平为点分 key 集合。"""
    keys: set[str] = set()
    for key, value in data.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            keys |= _flatten_locale_keys(value, full_key)
        else:
            keys.add(full_key)
    return keys


def _load_locale_keys(lang: str) -> set[str]:
    """读取 ``locale/{lang}.json``，不存在时返回空集合。"""
    path = LOCALE_DIR / f"{lang}.json"
    if not path.exists():
        return set()
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return _flatten_locale_keys(data)


# ── 主检查 ──────────────────────────────────────────────────────────────────
def run_check(report: bool = False) -> int:
    """执行 I1/I2 检查，返回进程退出码（0 通过 / 1 失败）。"""
    code_keys: set[str] = set()
    dynamic_calls: list[str] = []
    for file_path in _iter_py_files():
        try:
            tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
        except SyntaxError as exc:
            print(f"[check_i18n] SyntaxError in {file_path}: {exc}", file=sys.stderr)
            return 1
        file_keys, file_dynamic = _extract_literal_keys(tree, file_path)
        code_keys |= file_keys
        dynamic_calls.extend(file_dynamic)

    zh_keys = _load_locale_keys("zh")
    en_keys = _load_locale_keys("en")

    # I1：代码引用但 locale 缺失（任一语言缺失即 FAIL）
    missing_zh = sorted(code_keys - zh_keys)
    missing_en = sorted(code_keys - en_keys)

    # I2：locale 存在但代码未引用（仅 WARN）
    unused_zh = sorted(zh_keys - code_keys)

    # I3：未走 t() 的中文字面量（棘轮，只许降不许升）
    cjk_total, cjk_files = check_untranslated_cjk()
    cjk_over = cjk_total > I3_UNTRANSLATED_THRESHOLD

    failed = bool(missing_zh or missing_en or cjk_over)

    if report:
        print("## i18n 检查报告\n")
        print(f"- 代码字面量 key 总数: **{len(code_keys)}**")
        print(f"- zh.json key 总数: {len(zh_keys)} / en.json key 总数: {len(en_keys)}")
        print(f"- 动态 key 调用点（人工核对）: {len(dynamic_calls)}")
        print(f"- I3 未本地化中文字面量: **{cjk_total}**（阈值 {I3_UNTRANSLATED_THRESHOLD}）\n")
        if cjk_files:
            print("### I3 明细（按命中数排序）\n")
            for rel, hits in sorted(cjk_files.items(), key=lambda kv: -len(kv[1])):
                print(f"- `{rel}`: {len(hits)}")
            print()
        if missing_zh:
            print("### I1 缺失（zh）\n")
            for key in missing_zh:
                print(f"- `{key}`")
            print()
        if missing_en:
            print("### I1 缺失（en）\n")
            for key in missing_en:
                print(f"- `{key}`")
            print()
        if unused_zh:
            print(f"### I2 未使用（zh，{len(unused_zh)} 条，仅警告）\n")
            for key in unused_zh:
                print(f"- `{key}`")
            print()
    else:
        print(f"[check_i18n] code keys={len(code_keys)} zh={len(zh_keys)} en={len(en_keys)}")
        print(f"[check_i18n] I3 未本地化中文字面量 {cjk_total} / 阈值 {I3_UNTRANSLATED_THRESHOLD}")
        if cjk_over:
            top = sorted(cjk_files.items(), key=lambda kv: -len(kv[1]))[:5]
            print(f"[check_i18n] FAIL I3 超阈值（新增裸中文文案，须走 t()）: {[(k, len(v)) for k, v in top]}")
        if missing_zh:
            print(f"[check_i18n] FAIL I1 missing in zh.json ({len(missing_zh)}):")
            for key in missing_zh:
                print(f"  - {key}")
        if missing_en:
            print(f"[check_i18n] FAIL I1 missing in en.json ({len(missing_en)}):")
            for key in missing_en:
                print(f"  - {key}")
        if dynamic_calls:
            print(f"[check_i18n] WARN dynamic key call sites ({len(dynamic_calls)}):")
            for marker in dynamic_calls:
                print(f"  - {marker}")
        if unused_zh:
            print(f"[check_i18n] WARN unused in zh.json: {len(unused_zh)} (run --report for detail)")
        if not failed:
            print("[check_i18n] OK")

    return 1 if failed else 0


def main() -> int:
    """CLI 入口。"""
    # Windows 控制台默认 GBK：本脚本输出中文，reconfigure 到 UTF-8 才不会
    # UnicodeEncodeError 直接崩掉（表现为一次与代码质量无关的"假失败"）。
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="i18n coverage check (A-09)")
    parser.add_argument("--report", action="store_true", help="输出 Markdown 明细")
    args = parser.parse_args()
    return run_check(report=args.report)


if __name__ == "__main__":
    sys.exit(main())
