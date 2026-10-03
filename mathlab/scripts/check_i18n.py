"""i18n 覆盖检查（UI_SYSTEM_DESIGN.md §7.3，对应 A-09：字符串必须走 t() 与 locale）。

用法：
    python mathlab/scripts/check_i18n.py            # 默认检查，发现问题 exit 1
    python mathlab/scripts/check_i18n.py --report   # 输出 Markdown 明细

两条独立检查：
  I1 缺失 key：AST 扫描 ``mathlab/**/*.py`` 中 ``t("literal", ...)`` 的字面量
     key，与 ``mathlab/locale/*.json`` 求差集 —— 代码用到但 locale 缺失为 FAIL。
  I2 未使用 key（仅 WARN）：locale 中存在但代码未引用的 key（运行时拼接/
     update_i18n.py 生成的 key 可能误报，不作为失败条件）。

动态 key（f-string / 变量）无法静态解析，跳过扫描；可加入 ``--report`` 的
``dynamic`` 列表供人工核对。
"""

from __future__ import annotations

import argparse
import ast
import json
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

    failed = bool(missing_zh or missing_en)

    if report:
        print("## i18n 检查报告\n")
        print(f"- 代码字面量 key 总数: **{len(code_keys)}**")
        print(f"- zh.json key 总数: {len(zh_keys)} / en.json key 总数: {len(en_keys)}")
        print(f"- 动态 key 调用点（人工核对）: {len(dynamic_calls)}\n")
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
    parser = argparse.ArgumentParser(description="i18n coverage check (A-09)")
    parser.add_argument("--report", action="store_true", help="输出 Markdown 明细")
    args = parser.parse_args()
    return run_check(report=args.report)


if __name__ == "__main__":
    sys.exit(main())
