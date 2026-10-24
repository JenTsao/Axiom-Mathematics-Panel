"""
Real-time Signal Processing Lab - 实时信号处理实验室
结合 C# FFT 极速引擎与 Echarts 动态渲染
"""

import json
import os

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from mathlab.core.async_workers import TaskManager

# 尝试导入我们的底层引擎
try:
    from mathlab.core.cs_fft_engine import CS_FFT_AVAILABLE, get_cs_fft

    HAS_FFT_ENGINE = CS_FFT_AVAILABLE
except ImportError:
    HAS_FFT_ENGINE = False


class SignalLabPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("⚡ 实时信号处理实验室 (C# FFT Accelerated)")
        self.setMinimumSize(900, 700)

        # 信号发生器参数
        self.sample_rate = 1000.0
        self.t = np.arange(0, 1.0, 1.0 / self.sample_rate)

        # 动画与时间流逝状态
        self.phase_shift = 0.0
        self.is_playing = True

        self._build_ui()
        self._init_echarts()

        # 核心：设置一个 33ms (约 30FPS) 的定时器，形成实时处理循环
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._on_frame_update)
        self.timer.start(33)

    def _build_ui(self):
        main_layout = QHBoxLayout(self)

        # --- 左侧：控制台 ---
        control_panel = QWidget()
        control_panel.setFixedWidth(280)
        control_layout = QVBoxLayout(control_panel)

        # 信号源 1 控制
        group1 = QGroupBox("🌊 信号源 1 (正弦波)")
        vbox1 = QVBoxLayout(group1)
        self.freq1_slider, self.freq1_label = self._create_slider(vbox1, "频率 (Hz)", 1, 100, 10)
        self.amp1_slider, self.amp1_label = self._create_slider(vbox1, "振幅", 0, 10, 5)
        control_layout.addWidget(group1)

        # 信号源 2 控制
        group2 = QGroupBox("🌊 信号源 2 (正弦波)")
        vbox2 = QVBoxLayout(group2)
        self.freq2_slider, self.freq2_label = self._create_slider(vbox2, "频率 (Hz)", 1, 250, 50)
        self.amp2_slider, self.amp2_label = self._create_slider(vbox2, "振幅", 0, 10, 2)
        control_layout.addWidget(group2)

        # 噪声干扰控制
        group3 = QGroupBox("🌩️ 高斯白噪声干扰")
        vbox3 = QVBoxLayout(group3)
        self.noise_slider, self.noise_label = self._create_slider(vbox3, "噪声强度", 0, 20, 0)
        control_layout.addWidget(group3)

        # 动态流水控制
        self.animate_checkbox = QCheckBox("开启时间流逝 (相位滚动)")
        self.animate_checkbox.setChecked(True)
        self.animate_checkbox.stateChanged.connect(self._toggle_animation)
        control_layout.addWidget(self.animate_checkbox)

        control_layout.addStretch()
        main_layout.addWidget(control_panel)

        # --- 右侧：Echarts 示波器 ---
        self.web_view = QWebEngineView()
        main_layout.addWidget(self.web_view, stretch=1)

    def _create_slider(self, parent_layout, name, min_val, max_val, default_val):
        row = QHBoxLayout()
        label = QLabel(f"{name}: {default_val}")
        row.addWidget(label)

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(min_val, max_val)
        slider.setValue(default_val)

        # 实时更新标签
        slider.valueChanged.connect(lambda v: label.setText(f"{name}: {v}"))

        parent_layout.addLayout(row)
        parent_layout.addWidget(slider)
        return slider, label

    def _toggle_animation(self, state):
        self.is_playing = state == Qt.CheckState.Checked.value

    def _init_echarts(self):
        """注入 Echarts 的 HTML 与 JS 骨架，配置双图表联动"""
        html_content = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
            <style>
                body, html { margin: 0; padding: 0; height: 100%; background-color: #0f172a; }
                #main { width: 100%; height: 100%; }
            </style>
        </head>
        <body>
            <div id="main"></div>
            <script>
                var chart = echarts.init(document.getElementById('main'), 'dark');
                var option = {
                    backgroundColor: 'transparent',
                    animation: false, // 关闭自带动画以提高实时渲染性能
                    tooltip: { trigger: 'axis' },
                    grid: [
                        { left: '8%', right: '5%', top: '5%', height: '40%' },   // 上方时域图
                        { left: '8%', right: '5%', bottom: '5%', height: '40%' } // 下方频域图
                    ],
                    xAxis: [
                        { gridIndex: 0, type: 'category', boundaryGap: false, show: false }, // 时域 X
                        { gridIndex: 1, type: 'category', name: '频率 (Hz)', max: 250 }      // 频域 X (限制显示到 250Hz)
                    ],
                    yAxis: [
                        { gridIndex: 0, type: 'value', min: -15, max: 15, name: '时域幅值' }, 
                        { gridIndex: 1, type: 'value', min: 0, max: 10, name: '频谱能量' }
                    ],
                    series: [
                        {
                            name: '时域波形',
                            type: 'line',
                            xAxisIndex: 0,
                            yAxisIndex: 0,
                            showSymbol: false,
                            itemStyle: { color: '#38bdf8' },
                            lineStyle: { width: 1.5 },
                            data: []
                        },
                        {
                            name: '频谱能量',
                            type: 'bar',
                            xAxisIndex: 1,
                            yAxisIndex: 1,
                            itemStyle: { color: '#f43f5e' },
                            barWidth: '60%',
                            data: []
                        }
                    ]
                };
                chart.setOption(option);

                // 提供给 Python 调用的更新接口
                function updateChart(timeData, freqData) {
                    chart.setOption({
                        series: [
                            { data: timeData },
                            { data: freqData }
                        ]
                    });
                }
                
                // 窗口自适应
                window.addEventListener('resize', function() { chart.resize(); });
            </script>
        </body>
        </html>
        """
        self.web_view.setHtml(html_content)

    def closeEvent(self, event):
        """[BUG修复] 面板关闭时，停止定时器以释放资源"""
        if hasattr(self, "timer"):
            self.timer.stop()
        super().closeEvent(event)

    def _on_frame_update(self):
        """每帧触发：收集 UI 参数 -> 极速合成信号 -> C# 极速 FFT -> 发送 JS"""
        if not HAS_FFT_ENGINE:
            return

        # 1. 获取滑块参数
        f1, a1 = self.freq1_slider.value(), self.amp1_slider.value()
        f2, a2 = self.freq2_slider.value(), self.amp2_slider.value()
        noise_level = self.noise_slider.value()

        # 2. 如果开启了动画，滚动相位，制造“波浪流逝”的视觉效果
        if self.is_playing:
            self.phase_shift += 0.05

        # [BUG修复] 将耗时的信号合成和 FFT 计算放到子线程中执行，避免阻塞主线程
        def compute_fft(current_phase):
            # 3. 在 Python 中合成包含噪声的信号
            signal = a1 * np.sin(2 * np.pi * f1 * self.t + current_phase) + a2 * np.sin(
                2 * np.pi * f2 * self.t + current_phase
            )

            if noise_level > 0:
                signal += (noise_level / 5.0) * np.random.randn(len(self.t))

            # 4. 呼叫 C# 引擎进行原地极速 FFT 分析
            engine = get_cs_fft()
            if engine is None:
                raise RuntimeError("C# FFT 引擎不可用（pythonnet / .NET 缺失）")
            freqs, magnitudes = engine.analyze_spectrum(signal, self.sample_rate)

            # 5. 组装给 Echarts 的数据包
            display_signal = signal[::3].tolist()

            valid_idx = freqs <= 250
            freq_display = magnitudes[valid_idx].tolist()
            return display_signal, freq_display

        def update_ui(result):
            display_signal, freq_display = result
            # 6. 将数据推送到 Chromium 内核
            js_code = f"updateChart({json.dumps(display_signal)}, {json.dumps(freq_display)});"
            self.web_view.page().runJavaScript(js_code)

        TaskManager().submit(
            fn=compute_fft,
            on_success=update_ui,
            group_id="signal_lab_fft",  # 利用组 ID 防止堆积处理
            current_phase=self.phase_shift,
        )
