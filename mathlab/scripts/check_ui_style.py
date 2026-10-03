"""UI 内联样式防回潮检查（UI_SYSTEM_DESIGN.md §7.3，对应 A-03 / A-07）。

用法：
    python mathlab/scripts/check_ui_style.py            # 默认检查，超阈值 exit 1
    python mathlab/scripts/check_ui_style.py --report   # 输出 Markdown 明细

三条独立检查（阈值集中在 THRESHOLDS，随收敛批次调低）：
  S1 内联计数：``.setStyleSheet(`` 于 ``mathlab/ui/**.py``
  S2 HEX 计数：``#RRGGBB`` / ``rgba?(`` 于 ``mathlab/ui/**.py``
  S3 未连接 QAction：AST 扫描 QAction 赋值 → 同文件必须有
     ``.triggered.connect`` 或 ``setEnabled(False)``

阈值策略（R-3）：分三档推进 173/411（基线软阈值）→ 98/253（B1 完成）→
20/40（B3 完成）。当前处于 B1 完成档。
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

# ── 阈值（随批次调低；完成 B3 后改为 20 / 40 / 0） ─────────────────────────
THRESHOLDS: dict[str, int] = {
    # B1 完成档实测值（设计预估 98/253，实测 B1 后余量 103/264 — 余量全部
    # 位于 B2/B3 文件，见 --report 明细）。B2 完成后调至 64/181，B3 后 20/40。
    "inline": 103,  # 基线 173
    "hex": 264,  # 基线 411
    "unconnected_actions": 0,  # S3：未连接 QAction（A-07 目标 0）
}

# S1 白名单：动态色板 / 渲染器等必须内联的文件不计入
S1_WHITELIST_FILES: frozenset[str] = frozenset()

# S3 白名单：语义上无需直接 triggered.connect 的 action
# （tool actions 经 _connect_tool_actions 循环连接，文本匹配为误报）
S3_WHITELIST_ACTIONS: frozenset[str] = frozenset(
    {
        "tool_actions",
        "select_action",
        "point_action",
        "segment_action",
        "circle_action",
        "polygon_action",
        "pan_action",
    }
)

UI_DIR = Path(__file__).resolve().parents[1] / "ui"

HEX_RE = re.compile(r"#[0-9A-Fa-f]{3,8}\b")
RGBA_RE = re.compile(r"\brgba?\(", re.IGNORECASE)
INLINE_RE = re.compile(r"\.setStyleSheet\(")


def _iter_ui_python_files() -> list[Path]:
    return sorted(p for p in UI_DIR.rglob("*.py") if "resources" not in p.parts and "__pycache__" not in p.parts)


def check_s1_inline(files: list[Path]) -> tuple[int, dict[str, int]]:
    """S1：内联 setStyleSheet 计数。"""
    per_file: dict[str, int] = {}
    for path in files:
        rel = str(path.relative_to(UI_DIR))
        if rel in S1_WHITELIST_FILES:
            continue
        count = len(INLINE_RE.findall(path.read_text(encoding="utf-8")))
        if count:
            per_file[rel] = count
    return sum(per_file.values()), per_file


def check_s2_hex(files: list[Path]) -> tuple[int, dict[str, int]]:
    """S2：硬编码 HEX / rgba() 计数。"""
    per_file: dict[str, int] = {}
    for path in files:
        rel = str(path.relative_to(UI_DIR))
        text = path.read_text(encoding="utf-8")
        count = len(HEX_RE.findall(text)) + len(RGBA_RE.findall(text))
        if count:
            per_file[rel] = count
    return sum(per_file.values()), per_file


def check_s3_actions(files: list[Path]) -> tuple[int, dict[str, list[str]]]:
    """S3：AST 扫描未连接 QAction（同文件无 triggered.connect / setEnabled(False)）。"""
    issues: dict[str, list[str]] = {}
    total = 0
    for path in files:
        rel = str(path.relative_to(UI_DIR))
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue

        action_names: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if not (isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id == "QAction"):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                name = _target_name(target)
                if name:
                    action_names.add(name)

        if not action_names:
            continue

        source = path.read_text(encoding="utf-8")
        connected: set[str] = set()
        for name in action_names:
            if name in S3_WHITELIST_ACTIONS:
                connected.add(name)
                continue
            patterns = (
                f"{name}.triggered.connect",
                f"{name}.setEnabled(False)",
            )
            if any(p in source for p in patterns):
                connected.add(name)

        unconnected = sorted(action_names - connected)
        if unconnected:
            issues[rel] = unconnected
            total += len(unconnected)
    return total, issues


def _target_name(target: ast.expr) -> str | None:
    """提取赋值目标名：Name 或 Attribute（取末级属性名）。"""
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


def build_report(
    s1: int, s1_files: dict[str, int], s2: int, s2_files: dict[str, int], s3: int, s3_files: dict[str, list[str]]
) -> str:
    lines = ["# UI Style Guard Report", ""]
    lines.append(f"- S1 内联 setStyleSheet：**{s1}**（阈值 {THRESHOLDS['inline']}）")
    lines.append(f"- S2 硬编码 HEX/rgba：**{s2}**（阈值 {THRESHOLDS['hex']}）")
    lines.append(f"- S3 未连接 QAction：**{s3}**（阈值 {THRESHOLDS['unconnected_actions']}）")
    lines.append("")
    lines.append("## S1 内联明细")
    lines.extend(f"- `{k}`: {v}" for k, v in sorted(s1_files.items(), key=lambda kv: -kv[1]))
    lines.append("")
    lines.append("## S2 HEX 明细")
    lines.extend(f"- `{k}`: {v}" for k, v in sorted(s2_files.items(), key=lambda kv: -kv[1]))
    lines.append("")
    lines.append("## S3 未连接 QAction")
    lines.extend(f"- `{k}`: {', '.join(v)}" for k, v in sorted(s3_files.items()))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="UI 内联样式防回潮检查")
    parser.add_argument("--report", action="store_true", help="输出 Markdown 明细报告")
    args = parser.parse_args()

    files = _iter_ui_python_files()
    s1, s1_files = check_s1_inline(files)
    s2, s2_files = check_s2_hex(files)
    s3, s3_files = check_s3_actions(files)

    if args.report:
        print(build_report(s1, s1_files, s2, s2_files, s3, s3_files))
        return 0

    failures = []
    if s1 > THRESHOLDS["inline"]:
        failures.append(
            f"S1 内联样式 {s1} > 阈值 {THRESHOLDS['inline']}（TOP: {sorted(s1_files.items(), key=lambda kv: -kv[1])[:5]}）"
        )
    if s2 > THRESHOLDS["hex"]:
        failures.append(
            f"S2 硬编码色值 {s2} > 阈值 {THRESHOLDS['hex']}（TOP: {sorted(s2_files.items(), key=lambda kv: -kv[1])[:5]}）"
        )
    if s3 > THRESHOLDS["unconnected_actions"]:
        failures.append(f"S3 未连接 QAction {s3} > 阈值 {THRESHOLDS['unconnected_actions']}：{s3_files}")

    print(
        f"UI Style Guard: S1={s1}/{THRESHOLDS['inline']}  S2={s2}/{THRESHOLDS['hex']}  S3={s3}/{THRESHOLDS['unconnected_actions']}"
    )
    if failures:
        for failure in failures:
            print(f"❌ {failure}")
        return 1
    print("✅ UI 样式检查通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
