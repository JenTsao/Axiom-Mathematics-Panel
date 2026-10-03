"""Unit tests for mathlab.utils.theme_tokens (SSOT) — UI_SYSTEM_DESIGN.md T01/N8."""

import pytest

from mathlab.utils.theme_tokens import (
    CONTROL_MIN_H,
    FONT_TOKENS,
    MOTION_TOKENS,
    SHAPE_TOKENS,
    SPACE_TOKENS,
    THEME_TOKENS,
    flat_tokens,
    get_tokens,
    validate_theme_tokens,
)


class TestThemeTokens:
    """三主题 token 完整性（T01 验收）。"""

    @pytest.mark.unit
    def test_three_themes_exist(self):
        assert set(THEME_TOKENS.keys()) == {"light", "dark", "sepia"}

    @pytest.mark.unit
    def test_all_themes_share_identical_key_sets(self):
        problems = validate_theme_tokens()
        assert problems == []

    @pytest.mark.unit
    def test_no_empty_token_values(self):
        for theme_name, tokens in THEME_TOKENS.items():
            for key, value in tokens.items():
                assert value, f"{theme_name}.{key} has empty value"

    @pytest.mark.unit
    def test_dark_accent_is_blue_family(self):
        """D-1：强调色统一蓝系 #3B82F6。"""
        assert THEME_TOKENS["dark"]["accent.base"] == "#3B82F6"

    @pytest.mark.unit
    def test_light_accent_unchanged(self):
        """§1.3：light 主题 accent=#004AC6 不变。"""
        assert THEME_TOKENS["light"]["accent.base"] == "#004AC6"

    @pytest.mark.unit
    def test_sepia_accent_unchanged(self):
        assert THEME_TOKENS["sepia"]["accent.base"] == "#8B5A2B"

    @pytest.mark.unit
    def test_get_tokens_fallback(self):
        assert get_tokens("dark") is THEME_TOKENS["dark"]
        assert get_tokens("nonexistent") is THEME_TOKENS["dark"]

    @pytest.mark.unit
    def test_flat_tokens_replaces_dots(self):
        flat = flat_tokens(THEME_TOKENS["dark"])
        assert "bg_base" in flat
        assert "bg.base" not in flat
        assert flat["bg_base"] == THEME_TOKENS["dark"]["bg.base"]

    @pytest.mark.unit
    def test_constant_token_tables(self):
        assert SHAPE_TOKENS["radius.sm"] == 6
        assert SPACE_TOKENS["space.2"] == 8
        assert CONTROL_MIN_H["input"] == 32
        assert FONT_TOKENS["size.base"] == 13
        assert MOTION_TOKENS["base"] == 200
