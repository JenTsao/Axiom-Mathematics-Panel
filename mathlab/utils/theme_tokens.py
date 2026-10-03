"""Design Token 单一真源（Single Source of Truth）。

纯数据模块：禁止 import 任何 Qt / mathlab 内部模块，保证可独立单测。
三主题（light / dark / sepia）的颜色 token 完全派生自
``mathlab/docs/UIUX_PRD.md`` §6.2 的 Design Token 表。

约定（见 UI_SYSTEM_DESIGN.md §10）：
- Token 命名 ``<group>.<role>`` 点分；语义色无前缀（success / warning / danger）。
- Python 侧取色：``from mathlab.utils.theme_tokens import get_tokens`` → ``get_tokens()["accent.base"]``。
- QSS 侧引用：``styles.qss`` 模板中以 ``${bg_base}`` 形式书写（点号替换为下划线），
  由 ``theme_manager.render_qss()`` 渲染。
- 禁止在 UI 代码中新增裸 HEX 字面量。
"""

from __future__ import annotations

# ── 主题颜色 Token（3 主题 × 全量键，键集必须一致） ─────────────────────────
THEME_TOKENS: dict[str, dict[str, str]] = {
    "dark": {
        # 背景（分层，ΔL ≥ 4）
        "bg.base": "#0F172A",
        "bg.surface": "#1E293B",
        "bg.elevated": "#263449",
        "bg.canvas": "#0B1220",
        "bg.inset": "#0B1220",
        "bg.hover": "rgba(255,255,255,0.06)",
        "bg.selected": "rgba(59,130,246,0.16)",
        # 边框
        "border.subtle": "#334155",
        "border.strong": "#475569",
        "border.focus": "#3B82F6",
        # 文字
        "fg.primary": "#F8FAFC",
        "fg.secondary": "#94A3B8",
        "fg.muted": "#64748B",
        "fg.onAccent": "#FFFFFF",
        # 强调色（唯一，蓝系 — D-1）
        "accent.base": "#3B82F6",
        "accent.hover": "#60A5FA",
        "accent.pressed": "#2563EB",
        # 语义色（绿降级为 success — D-1）
        "success": "#22C55E",
        "warning": "#EAB308",
        "danger": "#EF4444",
        # 画布
        "canvas.grid": "#334155",
        "canvas.axis": "#64748B",
        # 几何对象
        "obj.point": "#60A5FA",
        "obj.segment": "#A78BFA",
        "obj.circle": "#2DD4BF",
        "obj.polygon": "#C084FC",
        "obj.conic": "#F472B6",
        "obj.function": "#38BDF8",
        "obj.implicit": "#818CF8",
        "obj.locus": "#FB923C",
        "obj.selection": "#3B82F6",
    },
    "light": {
        "bg.base": "#FFFFFF",
        "bg.surface": "#F5F5F5",
        "bg.elevated": "#FFFFFF",
        "bg.canvas": "#FFFFFF",
        "bg.inset": "#EEF1F6",
        "bg.hover": "rgba(15,23,42,0.05)",
        "bg.selected": "rgba(0,74,198,0.10)",
        "border.subtle": "#D3E4FE",
        "border.strong": "#AFC7EE",
        "border.focus": "#004AC6",
        "fg.primary": "#0B1C30",
        "fg.secondary": "#4A5568",
        "fg.muted": "#737686",
        "fg.onAccent": "#FFFFFF",
        "accent.base": "#004AC6",
        "accent.hover": "#1663E0",
        "accent.pressed": "#003A9E",
        "success": "#15803D",
        "warning": "#A16207",
        "danger": "#B91C1C",
        "canvas.grid": "#D3E4FE",
        "canvas.axis": "#94A3B8",
        "obj.point": "#004AC6",
        "obj.segment": "#6D28D9",
        "obj.circle": "#0F766E",
        "obj.polygon": "#7E22CE",
        "obj.conic": "#BE185D",
        "obj.function": "#0369A1",
        "obj.implicit": "#4338CA",
        "obj.locus": "#C2410C",
        "obj.selection": "#004AC6",
    },
    "sepia": {
        "bg.base": "#F4ECD8",
        "bg.surface": "#E8DCC8",
        "bg.elevated": "#F0E7D6",
        "bg.canvas": "#FBF6EC",
        "bg.inset": "#DDD0B8",
        "bg.hover": "rgba(92,75,55,0.08)",
        "bg.selected": "rgba(139,90,43,0.14)",
        "border.subtle": "#C9B896",
        "border.strong": "#A89372",
        "border.focus": "#8B5A2B",
        "fg.primary": "#5C4B37",
        "fg.secondary": "#7A6647",
        "fg.muted": "#9A8568",
        "fg.onAccent": "#FFFFFF",
        "accent.base": "#8B5A2B",
        "accent.hover": "#A06B36",
        "accent.pressed": "#6F4722",
        "success": "#567D46",
        "warning": "#D4A017",
        "danger": "#B83B1E",
        "canvas.grid": "#C9B896",
        "canvas.axis": "#A89372",
        "obj.point": "#8B5A2B",
        "obj.segment": "#6B4423",
        "obj.circle": "#567D46",
        "obj.polygon": "#9B4DCA",
        "obj.conic": "#A8537A",
        "obj.function": "#3E7C8C",
        "obj.implicit": "#5C5AA8",
        "obj.locus": "#C0703C",
        "obj.selection": "#8B5A2B",
    },
}

# ── 非 token 常量（形状/间距/字号/动效），QSS 与 Python 共用 ────────────────
SHAPE_TOKENS: dict[str, int] = {
    "radius.xs": 4,
    "radius.sm": 6,
    "radius.md": 8,
    "radius.lg": 12,
    "radius.xl": 12,
    "radius.full": 9999,
}

SPACE_TOKENS: dict[str, int] = {
    "space.1": 4,
    "space.2": 8,
    "space.3": 12,
    "space.4": 16,
    "space.6": 24,
    "space.8": 32,
}

CONTROL_MIN_H: dict[str, int] = {
    "input": 32,
    "input_default": 36,
    "button": 32,
    "primary": 40,
    "toolbar": 28,
}

FONT_TOKENS: dict[str, int] = {
    "size.xs": 11,
    "size.sm": 12,
    "size.base": 13,
    "size.md": 14,
    "size.lg": 16,
    "size.xl": 20,
}

FONT_FAMILY: dict[str, str] = {
    "ui": "Segoe UI",
    "mono": "Consolas",
    "ui.mac_fallback": "PingFang SC",
}

MOTION_TOKENS: dict[str, int] = {
    "fast": 120,
    "base": 200,
    "slow": 300,
    "emphasis": 600,
}

# QSS 模板中允许出现的占位符前缀校验用：所有主题键的扁平化命名（点 → 下划线）
_FLAT_TOKEN_KEYS: frozenset[str] = frozenset(key.replace(".", "_") for key in THEME_TOKENS["dark"])


def get_tokens(theme_name: str | None = None) -> dict[str, str]:
    """获取指定主题的 token 字典（默认当前缓存主题 → dark）。

    Args:
        theme_name: 主题键（light / dark / sepia）；None 时由调用方决定默认。

    Returns:
        该主题的完整 token 字典；未知主题名回落到 dark。
    """
    if theme_name is None or theme_name not in THEME_TOKENS:
        return THEME_TOKENS["dark"]
    return THEME_TOKENS[theme_name]


def flat_tokens(tokens: dict[str, str]) -> dict[str, str]:
    """将点分 token 键扁平化为 QSS 模板占位符键（``bg.base`` → ``bg_base``）。"""
    return {key.replace(".", "_"): value for key, value in tokens.items()}


def validate_theme_tokens() -> list[str]:
    """校验三主题 token 键集一致性，返回问题列表（空列表 = 通过）。"""
    problems: list[str] = []
    reference = set(THEME_TOKENS["dark"])
    for name, tokens in THEME_TOKENS.items():
        keys = set(tokens)
        if keys != reference:
            missing = reference - keys
            extra = keys - reference
            if missing:
                problems.append(f"theme '{name}' missing keys: {sorted(missing)}")
            if extra:
                problems.append(f"theme '{name}' extra keys: {sorted(extra)}")
    return problems
