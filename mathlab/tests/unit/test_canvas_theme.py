"""Unit tests for mathlab.ui.canvas_theme — resolve_canvas_palette 矩阵（T03 验收）。"""

import pytest

from mathlab.ui.canvas_theme import TYPE_TO_KIND, CanvasPalette, resolve_canvas_palette
from mathlab.utils.theme_tokens import THEME_TOKENS

ALL_THEMES = ("light", "dark", "sepia")


class TestCanvasPalette:
    @pytest.mark.unit
    def test_returns_frozen_dataclass(self):
        pal = resolve_canvas_palette("dark")
        assert isinstance(pal, CanvasPalette)
        with pytest.raises(Exception):
            pal.paper = "#FFF"

    @pytest.mark.unit
    @pytest.mark.parametrize("theme", ALL_THEMES)
    def test_paper_follows_theme(self, theme):
        pal = resolve_canvas_palette(theme, white_paper=False)
        assert pal.paper == THEME_TOKENS[theme]["bg.canvas"]

    @pytest.mark.unit
    @pytest.mark.parametrize("theme", ALL_THEMES)
    def test_white_paper_forces_white_background(self, theme):
        """D-2：白纸开关下 paper 固定 #FFFFFF，网格取 light 主题浅灰。"""
        pal = resolve_canvas_palette(theme, white_paper=True)
        assert pal.paper == "#FFFFFF"
        assert pal.grid == THEME_TOKENS["light"]["canvas.grid"]
        assert pal.axis == THEME_TOKENS["light"]["canvas.axis"]

    @pytest.mark.unit
    @pytest.mark.parametrize("theme", ALL_THEMES)
    def test_object_colors_follow_current_theme_even_in_white_paper(self, theme):
        """白纸模式下对象色保持当前主题（曲线在白纸上可读）。"""
        normal = resolve_canvas_palette(theme, white_paper=False)
        white = resolve_canvas_palette(theme, white_paper=True)
        assert normal.point == white.point
        assert normal.function == white.function

    @pytest.mark.unit
    @pytest.mark.parametrize("theme", ALL_THEMES)
    def test_all_object_kinds_populated(self, theme):
        pal = resolve_canvas_palette(theme)
        for field in ("point", "segment", "circle", "polygon", "conic", "function", "implicit", "locus", "selection"):
            value = getattr(pal, field)
            assert value and value.startswith("#"), f"{theme}.{field} invalid"

    @pytest.mark.unit
    def test_draft_is_accent_with_alpha(self):
        """draft = accent.base + alpha（#AARRGGBB 形式，alpha 固定 0x64）。"""
        pal = resolve_canvas_palette("dark")
        assert pal.draft.startswith("#")
        assert len(pal.draft) == 9  # #AARRGGBB
        assert pal.draft[1:3] == "64"
        assert pal.draft[3:] == THEME_TOKENS["dark"]["accent.base"][1:]

    @pytest.mark.unit
    def test_unknown_theme_falls_back_to_dark(self):
        pal = resolve_canvas_palette("nonexistent")
        assert pal.theme == "dark"
        assert pal.paper == THEME_TOKENS["dark"]["bg.canvas"]

    @pytest.mark.unit
    def test_type_to_kind_mapping_complete(self):
        """画布支持的 12 种几何类型全部有 kind 映射。"""
        expected = {
            "Point",
            "Segment",
            "Circle",
            "Polygon",
            "Ellipse",
            "Hyperbola",
            "Parabola",
            "ConicSection",
            "FunctionPlot",
            "PolarPlot",
            "ImplicitPlot",
            "Locus",
        }
        assert set(TYPE_TO_KIND.keys()) == expected
