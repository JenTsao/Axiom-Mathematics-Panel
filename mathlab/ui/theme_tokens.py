"""PRD 命名垫片：``mathlab/ui/theme_tokens.py``。

规范位置是 ``mathlab/utils/theme_tokens.py``（因 ``theme_manager`` 位于 utils 层、
必须由它渲染 QSS，``utils → ui`` 导入违反 AGENTS.md §4.1 分层硬规则）。
本文件按 PRD §6.8 的文件命名提供再导出（合法方向 ui → utils）。

若希望单一位置，删除本文件即可（§11 O-1）。
"""

from mathlab.utils.theme_tokens import (  # noqa: F401
    CONTROL_MIN_H,
    FONT_FAMILY,
    FONT_TOKENS,
    MOTION_TOKENS,
    SHAPE_TOKENS,
    SPACE_TOKENS,
    THEME_TOKENS,
    flat_tokens,
    get_tokens,
    validate_theme_tokens,
)

__all__ = [
    "CONTROL_MIN_H",
    "FONT_FAMILY",
    "FONT_TOKENS",
    "MOTION_TOKENS",
    "SHAPE_TOKENS",
    "SPACE_TOKENS",
    "THEME_TOKENS",
    "flat_tokens",
    "get_tokens",
    "validate_theme_tokens",
]
