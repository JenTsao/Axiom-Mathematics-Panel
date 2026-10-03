"""画布主题调色板（纯数据，零 Qt 依赖，可单测 — UI_SYSTEM_DESIGN.md §3.1）。

``CanvasPalette`` 是 GeometryCanvas 所有取色的唯一入口：
- 背景 / 网格 / 主轴：跟随主题（D-2）。
- 白纸模式（偏好「白纸」开关）：paper 固定 #FFFFFF，grid/axis 取 light 主题
  的浅灰，对象色保持当前主题（保证曲线在白纸上可读）。
"""

from __future__ import annotations

from dataclasses import dataclass

from mathlab.utils.theme_tokens import THEME_TOKENS

# 白纸模式固定纸面色（D-2）
WHITE_PAPER_COLOR = "#FFFFFF"

# 几何类型 → CanvasPalette 字段名（供画布统一取色 / 全量重刷）
TYPE_TO_KIND: dict[str, str] = {
    "Point": "point",
    "Segment": "segment",
    "Circle": "circle",
    "Polygon": "polygon",
    "Ellipse": "conic",
    "Hyperbola": "conic",
    "Parabola": "conic",
    "ConicSection": "conic",
    "FunctionPlot": "function",
    "PolarPlot": "function",
    "ImplicitPlot": "implicit",
    "Locus": "locus",
}


@dataclass(frozen=True)
class CanvasPalette:
    """画布专用调色板（不可变快照，主题切换时整体替换）。"""

    theme: str
    paper: str  # bg.canvas 或白纸模式下的 #FFFFFF
    grid: str  # canvas.grid
    axis: str  # canvas.axis
    point: str
    segment: str
    circle: str
    polygon: str
    conic: str
    function: str
    implicit: str
    locus: str
    selection: str  # 替代写死的 QColor(0,120,215)
    draft: str  # 草稿态：accent.base + alpha（#AARRGGBB）
    label: str  # MathGraphicsItem 降级文本色 → fg.primary


def resolve_canvas_palette(theme_name: str, white_paper: bool = False) -> CanvasPalette:
    """解析画布调色板。

    Args:
        theme_name: 主题键（light / dark / sepia）；未知回落 dark。
        white_paper: 白纸模式（D-2）— paper 固定 #FFFFFF，网格/主轴取 light 主题
            浅灰，对象色保持当前主题。

    Returns:
        该主题（× 白纸开关）下的 CanvasPalette。
    """
    tokens = THEME_TOKENS.get(theme_name, THEME_TOKENS["dark"])
    resolved_theme = theme_name if theme_name in THEME_TOKENS else "dark"
    if white_paper:
        paper = WHITE_PAPER_COLOR
        grid = THEME_TOKENS["light"]["canvas.grid"]
        axis = THEME_TOKENS["light"]["canvas.axis"]
    else:
        paper = tokens["bg.canvas"]
        grid = tokens["canvas.grid"]
        axis = tokens["canvas.axis"]

    accent = tokens["accent.base"]
    # 草稿态：accent.base + 40% alpha（#AARRGGBB；0x64 ≈ 100/255，对齐历史 QColor(x,120,215,100)）
    draft = f"#64{accent[1:]}"

    return CanvasPalette(
        theme=resolved_theme,
        paper=paper,
        grid=grid,
        axis=axis,
        point=tokens["obj.point"],
        segment=tokens["obj.segment"],
        circle=tokens["obj.circle"],
        polygon=tokens["obj.polygon"],
        conic=tokens["obj.conic"],
        function=tokens["obj.function"],
        implicit=tokens["obj.implicit"],
        locus=tokens["obj.locus"],
        selection=tokens["obj.selection"],
        draft=draft,
        label=tokens["fg.primary"],
    )
