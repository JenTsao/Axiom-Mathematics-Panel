"""Unit tests for mathlab.utils.theme_manager.

THEMES 现为由 token 派生的兼容视图（UI_SYSTEM_DESIGN.md §1.7）。
T01 改造后断言对齐新的 token 色值。
"""

import pytest

from mathlab.utils.theme_manager import THEMES, get_theme_colors


class TestThemeManager:
    """Tests for the theme manager module."""

    @pytest.mark.unit
    def test_themes_exist(self):
        assert "light" in THEMES
        assert "dark" in THEMES
        assert "sepia" in THEMES

    @pytest.mark.unit
    def test_theme_has_required_keys(self):
        for theme_id, theme in THEMES.items():
            assert "name" in theme
            assert "background" in theme
            assert "foreground" in theme
            assert "accent" in theme

    @pytest.mark.unit
    def test_get_theme_colors(self):
        colors = get_theme_colors("light")
        assert colors["name"] == "Light"
        assert colors["background"] == "#FFFFFF"

    @pytest.mark.unit
    def test_get_theme_colors_default(self):
        colors = get_theme_colors()
        assert colors is not None

    @pytest.mark.unit
    def test_dark_theme_colors(self):
        colors = get_theme_colors("dark")
        # D-1 改造后：dark 背景切换到 Slate 色板（bg.base = #0F172A）
        assert colors["background"] == "#0F172A"
        assert colors["foreground"] == "#F8FAFC"

    @pytest.mark.unit
    def test_sepia_theme_colors(self):
        colors = get_theme_colors("sepia")
        assert colors["background"] == "#F4ECD8"
