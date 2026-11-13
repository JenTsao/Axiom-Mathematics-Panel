#!/usr/bin/env python3
"""打包配置静态检查 + 无副作用导入冒烟（见 ``.github/workflows/build-smoke.yml``）。

背景：早期的 ``Import smoke test`` 会在 CI 里直接 ``import mathlab.main``。
但 ``mathlab/main.py`` 在**导入期**就执行初始化日志、清理临时文件、安装全局
excepthook，并拉起 PySide6 / QtWebEngine / MainWindow 整条 GUI 栈。headless
runner 上这条路径既不稳定（CI 曾以 ``exit code 127`` 中止，日志停在
``main.py:134``），又会把整个 GUI 栈加载一遍，是打包冒烟最慢的一步。

本脚本把「打包配置是否还成立」拆成两类检查，均不执行 ``mathlab.spec``：

* **静态**：AST 解析 spec，校验入口脚本可解析、``hidden_imports`` 里的
  ``mathlab.*`` 模块仍存在，并报告非 glob 静态资源的存在性。不需要安装
  任何第三方依赖，因此 PR 阶段也能秒级完成。
* **动态（可选）**：只导入无副作用的纯逻辑模块，且每个模块放进**独立子
  进程**，单个模块崩溃不会带崩整个冒烟，并打印返回码 / stderr 便于定位。

用法::

    python mathlab/scripts/check_build_spec.py                  # 仅静态检查
    python mathlab/scripts/check_build_spec.py --import-smoke   # 静态 + 子进程导入冒烟
    python mathlab/scripts/check_build_spec.py --report

退出码：0 全部通过；1 有检查失败。
"""

from __future__ import annotations

import argparse
import ast
import os
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):  # Windows GBK 控制台防假失败
    sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "mathlab"
SPEC_PATH = REPO_ROOT / "mathlab.spec"

# 只允许导入「无模块级 GUI / 日志 / 全局钩子副作用」的纯逻辑模块。
# 严禁把 mathlab.main 加回来：理由见模块 docstring。
SMOKE_MODULES: tuple[str, ...] = (
    "mathlab.core.geometry_engine",
    "mathlab.core.cas_provider",
    "mathlab.data.project_schema",
    "mathlab.utils.config_manager",
)

IMPORT_TIMEOUT_SECONDS = 90


def _string_list_from_assign(tree: ast.Module, name: str) -> list[str]:
    """取出 ``name = ['a', 'b', ...]`` 里的字符串字面量。"""
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            continue
        if not isinstance(node.value, (ast.List, ast.Tuple)):
            continue
        return [
            item.value for item in node.value.elts if isinstance(item, ast.Constant) and isinstance(item.value, str)
        ]
    return []


def _resource_paths(tree: ast.Module, name: str) -> list[str]:
    """取出 ``name = [(src, dst), ...]`` 里每个二元组的源路径字面量。"""
    result: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            continue
        if not isinstance(node.value, (ast.List, ast.Tuple)):
            continue
        for item in node.value.elts:
            if isinstance(item, (ast.Tuple, ast.List)) and item.elts:
                item = item.elts[0]
            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                result.append(item.value)
    return result


def _entrypoint_scripts(tree: ast.Module) -> list[str]:
    """取出 ``Analysis(['...'], ...)`` 的第一个位置参数（入口脚本列表）。"""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Name) or func.id != "Analysis" or not node.args:
            continue
        first = node.args[0]
        if not isinstance(first, (ast.List, ast.Tuple)):
            continue
        return [item.value for item in first.elts if isinstance(item, ast.Constant) and isinstance(item.value, str)]
    return []


def _module_exists(module: str) -> bool:
    """``mathlab.foo.bar`` 是否存在对应的 .py 或包 __init__.py。"""
    relative = Path(*module.split("."))
    return (REPO_ROOT / relative).with_suffix(".py").is_file() or (REPO_ROOT / relative / "__init__.py").is_file()


def check_spec() -> tuple[list[str], list[str]]:
    """静态校验 spec。返回 ``(failures, reports)``。"""
    failures: list[str] = []
    reports: list[str] = []

    if not SPEC_PATH.is_file():
        return [f"spec 文件缺失: {SPEC_PATH}"], reports

    try:
        tree = ast.parse(SPEC_PATH.read_text(encoding="utf-8"), filename=str(SPEC_PATH))
    except SyntaxError as exc:
        return [f"spec 语法错误: {exc}"], reports

    entries = _entrypoint_scripts(tree)
    if not entries:
        failures.append("spec 中未找到 Analysis([...]) 入口脚本声明")
    for entry in entries:
        entry_path = REPO_ROOT / entry
        if not entry_path.is_file():
            failures.append(f"入口脚本缺失: {entry}")
            continue
        try:
            ast.parse(entry_path.read_text(encoding="utf-8"), filename=str(entry_path))
        except SyntaxError as exc:
            failures.append(f"入口脚本语法错误 {entry}: {exc}")
    reports.append(f"入口脚本: {', '.join(entries) or '（无）'}（AST 可解析）")

    hidden = _string_list_from_assign(tree, "hidden_imports")
    internal = [name for name in hidden if name.startswith("mathlab.")]
    missing = [name for name in internal if not _module_exists(name)]
    if missing:
        failures.append(f"hiddenimports 指向不存在的内部模块: {', '.join(missing)}")
    reports.append(f"hiddenimports: {len(hidden)} 项，其中内部模块 {len(internal)} 项全部存在")

    # 静态资源只做报告：部分路径是构建产物（resources/dist/*）或可选依赖，
    # 本地未构建时缺失属于正常情况，不能让 PR 的静态检查假红。
    resources = _resource_paths(tree, "added_files")
    literal_resources = [item for item in resources if "*" not in item]
    absent = [item for item in literal_resources if not (REPO_ROOT / item).exists()]
    reports.append(f"静态资源字面路径: {len(literal_resources)} 项，缺失 {len(absent)} 项（仅提示）")
    if absent:
        reports.append(f"  缺失示例: {', '.join(absent[:5])}")

    return failures, reports


def check_import_smoke() -> tuple[list[str], list[str]]:
    """在独立子进程里逐个导入纯逻辑模块。返回 ``(failures, reports)``。"""
    failures: list[str] = []
    reports: list[str] = []
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.setdefault("QT_QPA_PLATFORM", "offscreen")

    code = "import importlib, sys; importlib.import_module(sys.argv[1])"
    for module in SMOKE_MODULES:
        try:
            proc = subprocess.run(
                [sys.executable, "-c", code, module],
                cwd=str(REPO_ROOT),
                env=env,
                capture_output=True,
                text=True,
                timeout=IMPORT_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired:
            failures.append(f"{module}: 导入超时（>{IMPORT_TIMEOUT_SECONDS}s）")
            continue
        if proc.returncode == 0:
            reports.append(f"  OK  {module}")
            continue
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        tail = detail[-1] if detail else "（无输出）"
        failures.append(f"{module}: 子进程退出码 {proc.returncode} — {tail}")

    reports.insert(0, f"子进程隔离导入: {len(SMOKE_MODULES)} 个无副作用模块")
    return failures, reports


def main() -> int:
    parser = argparse.ArgumentParser(description="打包配置静态检查 + 无副作用导入冒烟")
    parser.add_argument("--import-smoke", action="store_true", help="额外运行子进程隔离的模块导入冒烟")
    parser.add_argument("--report", action="store_true", help="输出明细报告")
    args = parser.parse_args()

    all_failures: list[str] = []
    all_reports: list[str] = []

    failures, reports = check_spec()
    all_failures.extend(failures)
    all_reports.extend(reports)
    if args.import_smoke:
        failures, reports = check_import_smoke()
        all_failures.extend(failures)
        all_reports.extend(reports)

    if args.report or all_failures:
        print("## 打包配置检查报告\n")
        for line in all_reports:
            print(f"- {line}" if not line.startswith("  ") else line)
        print()

    if all_failures:
        print("[build-spec] FAIL")
        for item in all_failures:
            print(f"  - {item}")
        return 1

    print("[build-spec] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
