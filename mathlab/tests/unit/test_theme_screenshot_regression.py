"""三主题（light / dark / sepia）QSS 截图与像素差异回归测试。

验证 ``styles.qss`` + ``theme_tokens.py`` + ``theme_manager.set_theme()``
在真实 Qt 控件树上能够正常渲染，且三套主题的最终渲染像素存在显著差异。
"""

from __future__ import annotations

import pytest
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from mathlab.utils.theme_manager import get_current_theme, set_theme


def _build_sample_panel() -> QWidget:
    """构造覆盖常用 QSS 选择器的轻量代表性控件树。"""
    root = QWidget()
    root.setObjectName("themeRegressionRoot")
    root.resize(420, 260)

    layout = QVBoxLayout(root)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(8)

    tabs = QTabWidget()
    page = QWidget()
    page_layout = QVBoxLayout(page)

    title = QLabel("MathLab Theme Regression")
    title.setObjectName("section_label")
    page_layout.addWidget(title)

    row = QHBoxLayout()
    edit = QLineEdit("sin(x) + cos(x)")
    btn = QPushButton("Compute")
    row.addWidget(edit)
    row.addWidget(btn)
    page_layout.addLayout(row)

    controls = QHBoxLayout()
    cb = QCheckBox("Enable Grid")
    cb.setChecked(True)
    combo = QComboBox()
    combo.addItems(["Dark", "Light", "Sepia"])
    controls.addWidget(cb)
    controls.addWidget(combo)
    page_layout.addLayout(controls)

    bar = QProgressBar()
    bar.setValue(65)
    page_layout.addWidget(bar)

    tabs.addTab(page, "Canvas")
    tabs.addTab(QWidget(), "Console")
    layout.addWidget(tabs)
    return root


def _pixel_diff_ratio(img_a: QImage, img_b: QImage, step: int = 4) -> float:
    """抽样计算两张同尺寸 QImage 的像素差异比例（0.0 ~ 1.0）。"""
    assert img_a.size() == img_b.size()
    w, h = img_a.width(), img_a.height()
    total = 0
    diff = 0
    for y in range(0, h, step):
        for x in range(0, w, step):
            total += 1
            if img_a.pixel(x, y) != img_b.pixel(x, y):
                diff += 1
    return diff / max(1, total)


def _unique_pixel_count(img: QImage, step: int = 8) -> int:
    """抽样统计截图中的不同像素色值数量，防止全黑/全白死图。"""
    colors = set()
    for y in range(0, img.height(), step):
        for x in range(0, img.width(), step):
            colors.add(img.pixel(x, y))
    return len(colors)


@pytest.mark.qt
def test_three_themes_render_distinct_screenshots(qtbot):
    """light / dark / sepia 三主题渲染结果非空、非纯色且彼此像素差异显著。"""
    prev_theme = get_current_theme()
    panel = _build_sample_panel()
    qtbot.addWidget(panel)
    panel.show()
    qtbot.waitExposed(panel)

    images: dict[str, QImage] = {}
    try:
        for theme_name in ("light", "dark", "sepia"):
            set_theme(theme_name)
            qtbot.wait(20)
            pixmap = panel.grab()
            assert not pixmap.isNull(), f"{theme_name} 截图为空"
            img = pixmap.toImage()
            assert img.width() >= 400 and img.height() >= 240
            assert _unique_pixel_count(img) >= 5, f"{theme_name} 渲染疑似纯色死图"
            images[theme_name] = img
    finally:
        set_theme(prev_theme)

    for a, b in (("light", "dark"), ("light", "sepia"), ("dark", "sepia")):
        ratio = _pixel_diff_ratio(images[a], images[b])
        assert ratio > 0.15, f"主题 {a} 与 {b} 像素差异过小 ({ratio:.2%})，QSS 主题切换可能失效"
