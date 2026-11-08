#!/usr/bin/env python3
"""仓库结构守卫（CI 守卫，见 ``.github/workflows/repo-guardrails.yml``）。

检查四类「不该继续恶化」的结构性问题：

* **G1 超大文件**：>800 行的 ``.py`` 文件数量（AGENTS.md §9.6 / T-20）。
* **G2 规模与复杂度上限**：单文件行数、单函数圈复杂度。
* **G3 版本与许可证一致**：``version.py`` / ``LICENSE`` / ``installer/LICENSE.txt`` / ``AGENTS.md``。
* **G4 locale 双语叶键对称**（硬性要求，非棘轮）。

G1/G2 采用**棘轮阈值**：阈值等于当前实测值，只许降、不许升——新增一个
超大文件或让某文件继续膨胀就会让 CI 变红，但把文件拆小是允许的。
这与 ``check_ui_style.py`` / ``check_i18n.py`` 的棘轮模式一致。

用法::

    python mathlab/scripts/check_repo_guardrails.py
    python mathlab/scripts/check_repo_guardrails.py --report

退出码：0 全部通过；1 有阈值被突破或一致性失败。
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):  # Windows GBK 控制台防假失败
    sys.stdout.reconfigure(encoding="utf-8")

SRC_DIR = Path(__file__).resolve().parents[1]  # mathlab/
REPO_ROOT = SRC_DIR.parent

# ── 棘轮阈值（只降不升）──────────────────────────────────────────────────────
# 数值取自当前实测，收敛时把数字改小即可，**不要**放宽容差。
THRESHOLDS = {
    # G1：>800 行的 .py 文件数（含 tests/，因为 tests 同样影响维护成本）
    "oversized_files": 5,
    # G2：单文件行数上限、单函数圈复杂度上限（全仓最坏值，见 T-21）
    "max_file_lines": 1541,
    "max_function_complexity": 41,
}

LARGE_FILE_LINES = 800


def _iter_py_files():
    for path in sorted(SRC_DIR.rglob("*.py")):
        if "resources" in path.parts or "__pycache__" in path.parts:
            continue
        yield path


def _line_count(path: Path) -> int:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            return sum(1 for _ in handle)
    except OSError:
        return 0


def _function_complexities(path: Path):
    """返回该文件内各函数的圈复杂度估算值 ``[(name, cx)]``。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, OSError):
        return []
    result = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        branches = sum(
            1
            for child in ast.walk(node)
            if isinstance(child, (ast.If, ast.For, ast.While, ast.ExceptHandler, ast.With, ast.BoolOp, ast.IfExp))
        )
        result.append((node.name, branches + 1))
    return result


def check_oversized_files():
    """G1 + G2：超大文件数量、单文件行数、单函数复杂度。"""
    failures = []
    reports = []

    oversized = []
    worst_lines = (0, None)
    worst_cx = (0, None, None)

    for path in _iter_py_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        lines = _line_count(path)
        if lines > worst_lines[0]:
            worst_lines = (lines, rel)
        if lines > LARGE_FILE_LINES:
            oversized.append((rel, lines))
        for name, cx in _function_complexities(path):
            if cx > worst_cx[0]:
                worst_cx = (cx, rel, name)

    reports.append(f"超大文件（>{LARGE_FILE_LINES} 行）: {len(oversized)} / 阈值 {THRESHOLDS['oversized_files']}")
    for rel, lines in oversized:
        reports.append(f"  - {rel}: {lines} 行")
    reports.append(f"单文件最大行数: {worst_lines[0]} / 阈值 {THRESHOLDS['max_file_lines']} ({worst_lines[1]})")
    reports.append(
        f"单函数最大圈复杂度: {worst_cx[0]} / 阈值 {THRESHOLDS['max_function_complexity']} "
        f"({worst_cx[1]}::{worst_cx[2]})"
    )

    if len(oversized) > THRESHOLDS["oversized_files"]:
        failures.append(
            f"G1 超大文件数量 {len(oversized)} 超过阈值 {THRESHOLDS['oversized_files']}，" "请拆分文件而不是继续膨胀"
        )
    if worst_lines[0] > THRESHOLDS["max_file_lines"]:
        failures.append(f"G2 {worst_lines[1]} 达到 {worst_lines[0]} 行，超过阈值 {THRESHOLDS['max_file_lines']}")
    if worst_cx[0] > THRESHOLDS["max_function_complexity"]:
        failures.append(
            f"G2 {worst_cx[1]}::{worst_cx[2]} 圈复杂度 {worst_cx[0]} 超过阈值 "
            f"{THRESHOLDS['max_function_complexity']}"
        )
    return failures, reports


def _read_first_line(path: Path) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            return handle.readline().strip()
    except OSError:
        return ""


def check_version_and_license():
    """G3：版本号与许可证声明在四处保持一致。"""
    failures = []
    reports = []

    version_py = (SRC_DIR / "utils" / "version.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', version_py)
    app_version = match.group(1) if match else None
    reports.append(f"version.py: {app_version}")

    license_head = _read_first_line(REPO_ROOT / "LICENSE")
    installer_head = _read_first_line(REPO_ROOT / "installer" / "LICENSE.txt")
    reports.append(f"LICENSE 首行: {license_head[:70]}")
    reports.append(f"installer/LICENSE.txt 首行: {installer_head[:70]}")

    # 许可证规格版本（如 v1.0）必须四处一致
    spec_versions = {}
    for label, text in (("LICENSE", license_head), ("installer/LICENSE.txt", installer_head)):
        found = re.search(r"v(\d+\.\d+)", text)
        spec_versions[label] = found.group(0) if found else None
        reports.append(f"{label} 许可证规格: {spec_versions[label]}")

    agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    agent_lic = re.search(r"许可证\s*\|\s*`?CASAL\s+(v[\d.]+)", agents)
    reports.append(f"AGENTS.md 声明: CASAL {agent_lic.group(1) if agent_lic else '<未找到>'}")
    spec_versions["AGENTS.md"] = agent_lic.group(1) if agent_lic else None

    distinct = {v for v in spec_versions.values() if v}
    if len(distinct) > 1:
        failures.append(f"G3 许可证规格版本不一致: {spec_versions}")

    agent_ver = re.search(r"版本\s*\|\s*`([\d.]+)`", agents)
    if agent_ver and app_version and agent_ver.group(1) != app_version:
        failures.append(f"G3 AGENTS.md 版本 {agent_ver.group(1)} != version.py {app_version}")
    elif agent_ver:
        reports.append(f"AGENTS.md 版本: {agent_ver.group(1)}（与 version.py 一致）")

    return failures, reports


def _leaves(node, prefix=""):
    out = set()
    for key, value in node.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            out |= _leaves(value, path + ".")
        else:
            out.add(path)
    return out


def check_locale_symmetry():
    """G4：zh.json 与 en.json 的叶键必须完全一致。"""
    failures = []
    reports = []
    zh = json.loads((SRC_DIR / "locale" / "zh.json").read_text(encoding="utf-8"))
    en = json.loads((SRC_DIR / "locale" / "en.json").read_text(encoding="utf-8"))
    zh_keys, en_keys = _leaves(zh), _leaves(en)
    reports.append(f"locale 叶键: zh={len(zh_keys)} / en={len(en_keys)}")
    if zh_keys != en_keys:
        diff = sorted(zh_keys ^ en_keys)
        failures.append(f"G4 双语 key 不对称（前 10 个）: {diff[:10]}")
    return failures, reports


def main() -> int:
    parser = argparse.ArgumentParser(description="仓库结构守卫（超大文件棘轮 / 版本一致 / locale 对称）")
    parser.add_argument("--report", action="store_true", help="输出明细报告")
    args = parser.parse_args()

    all_failures = []
    all_reports = []
    for checker in (check_oversized_files, check_version_and_license, check_locale_symmetry):
        failures, reports = checker()
        all_failures.extend(failures)
        all_reports.extend(reports)

    if args.report or all_failures:
        print("## 仓库结构守卫报告\n")
        for line in all_reports:
            print(f"- {line}" if not line.startswith("  ") else line)
        print()

    if all_failures:
        print("[repo-guardrails] FAIL")
        for item in all_failures:
            print(f"  - {item}")
        return 1

    print("[repo-guardrails] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
