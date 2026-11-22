from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QDockWidget,
    QGraphicsEllipseItem,
    QGraphicsLineItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from mathlab.core.signals import theme_signals
from mathlab.utils.i18n_manager import t
from mathlab.utils.theme_manager import get_current_theme
from mathlab.utils.theme_tokens import get_tokens


class AlgoVisPanel(QDockWidget):
    algorithm_selected = Signal(str, dict)
    step_requested = Signal()  # 新增专用信号，避免使用字符串 'step'

    def __init__(self, parent=None):
        super().__init__(t("algo_vis.title"), parent)
        self.setAllowedAreas(Qt.RightDockWidgetArea | Qt.BottomDockWidgetArea)

        self.widget = QWidget()
        self.layout = QVBoxLayout(self.widget)

        # Algorithm selector (display text + internal data key)
        self.algorithm_combo = QComboBox()
        self.algorithm_combo.addItem(t("algo_vis.bubble_sort"), "bubble_sort")
        self.algorithm_combo.addItem(t("algo_vis.quick_sort"), "quick_sort")
        self.algorithm_combo.addItem(t("algo_vis.binary_search"), "binary_search")
        self.algorithm_combo.addItem(t("algo_vis.bfs"), "bfs")
        self.algorithm_combo.addItem(t("algo_vis.dfs"), "dfs")
        self.algorithm_combo.addItem(t("algo_vis.dijkstra"), "dijkstra")
        self.algorithm_combo.addItem(t("algo_vis.convex_hull"), "convex_hull")
        self.algorithm_combo.addItem(t("algo_vis.k_means"), "kmeans")

        # Parameter row
        self.params_layout = QHBoxLayout()

        self.array_size_label = QLabel(t("algo_vis.array_size"))
        self.params_layout.addWidget(self.array_size_label)
        self.array_size_spin = QSpinBox()
        self.array_size_spin.setRange(5, 20)
        self.array_size_spin.setValue(8)
        self.params_layout.addWidget(self.array_size_spin)

        self.clusters_label = QLabel(t("algo_vis.clusters"))
        self.params_layout.addWidget(self.clusters_label)
        self.clusters_spin = QSpinBox()
        self.clusters_spin.setRange(2, 10)
        self.clusters_spin.setValue(3)
        self.params_layout.addWidget(self.clusters_spin)

        self.load_button = QPushButton(t("algo_vis.load_algorithm"))
        self.load_button.clicked.connect(self.on_load_algorithm)

        # Playback controls
        self.control_layout = QHBoxLayout()
        self.play_button = QPushButton(t("algo_vis.play"))
        self.pause_button = QPushButton(t("algo_vis.pause"))
        self.step_button = QPushButton(t("algo_vis.step"))
        self.reset_button = QPushButton(t("algo_vis.reset"))
        self.fast_forward_button = QPushButton(t("algo_vis.fast_forward"))

        self.control_layout.addWidget(self.play_button)
        self.control_layout.addWidget(self.pause_button)
        self.control_layout.addWidget(self.step_button)
        self.control_layout.addWidget(self.reset_button)
        self.control_layout.addWidget(self.fast_forward_button)

        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setRange(1, 10)
        self.speed_slider.setValue(5)

        self.status_label = QLabel(t("algo_vis.status_ready"))

        self.scene = QGraphicsScene()
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.Antialiasing)
        self.view.setMinimumHeight(200)
        self._apply_scene_theme(get_current_theme())
        theme_signals.theme_changed.connect(self._on_theme_changed)

        # Assemble layout
        self.layout.addWidget(self.algorithm_combo)
        self.layout.addLayout(self.params_layout)
        self.layout.addWidget(self.load_button)
        self.layout.addLayout(self.control_layout)
        self.animation_speed_label = QLabel(t("algo_vis.animation_speed"))
        self.layout.addWidget(self.animation_speed_label)
        self.layout.addWidget(self.speed_slider)
        self.layout.addWidget(self.status_label)
        self.layout.addWidget(self.view)

        self.setWidget(self.widget)

        # Timer
        # [BUG修复] 传入 self 作为 parent，绑定生命周期防止内存泄漏
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.on_timer)

        self.is_playing = False
        self.current_state = None

        # Signal connections
        self.play_button.clicked.connect(self.on_play)
        self.pause_button.clicked.connect(self.on_pause)
        self.step_button.clicked.connect(self.on_step)
        self.reset_button.clicked.connect(self.on_reset)
        self.fast_forward_button.clicked.connect(self.on_fast_forward)
        self.speed_slider.valueChanged.connect(self.on_speed_changed)

    # ------------------------------------------------------------------
    # i18n
    # ------------------------------------------------------------------
    def retranslate_ui(self):
        self.setWindowTitle(t("algo_vis.title"))

        # Algorithm combo items (order must match __init__)
        algo_keys = [
            "algo_vis.bubble_sort",
            "algo_vis.quick_sort",
            "algo_vis.binary_search",
            "algo_vis.bfs",
            "algo_vis.dfs",
            "algo_vis.dijkstra",
            "algo_vis.convex_hull",
            "algo_vis.k_means",
        ]
        for i, key in enumerate(algo_keys):
            self.algorithm_combo.setItemText(i, t(key))

        # Labels
        self.array_size_label.setText(t("algo_vis.array_size"))
        self.clusters_label.setText(t("algo_vis.clusters"))
        self.load_button.setText(t("algo_vis.load_algorithm"))

        # Control buttons
        self.play_button.setText(t("algo_vis.play"))
        self.pause_button.setText(t("algo_vis.pause"))
        self.step_button.setText(t("algo_vis.step"))
        self.reset_button.setText(t("algo_vis.reset"))
        self.fast_forward_button.setText(t("algo_vis.fast_forward"))

        # Speed label
        self.animation_speed_label.setText(t("algo_vis.animation_speed"))

    # ------------------------------------------------------------------
    # Slot handlers
    # ------------------------------------------------------------------
    def on_load_algorithm(self):
        # Use stored userData key instead of parsing display text
        algorithm_name = self.algorithm_combo.currentData()

        params = {}
        if algorithm_name in ["bubble_sort", "quick_sort"]:
            params["arr"] = list(range(self.array_size_spin.value(), 0, -1))
        elif algorithm_name == "kmeans":
            params["k"] = self.clusters_spin.value()

        self.algorithm_selected.emit(algorithm_name, params)
        self.status_label.setText(t("algo_vis.status_loaded"))

    def on_play(self):
        self.is_playing = True
        self.timer.start()

    def on_pause(self):
        self.is_playing = False
        self.timer.stop()

    def on_step(self):
        self.timer.stop()
        self.is_playing = False
        # 使用专用信号而非字符串 'step'，保持协议一致性
        self.step_requested.emit()

    def on_reset(self):
        self.on_pause()
        self.algorithm_selected.emit("reset", {})
        self.scene.clear()
        self.status_label.setText(t("algo_vis.status_ready"))

    def on_speed_changed(self, value):
        self.timer.setInterval(int(500 / value))

    def on_fast_forward(self):
        self.timer.setInterval(50)
        self.is_playing = True
        self.timer.start()

    def on_timer(self):
        # 使用专用信号而非字符串 'step'，保持协议一致性
        self.step_requested.emit()

    # ------------------------------------------------------------------
    # Visualization dispatcher
    # ------------------------------------------------------------------
    def update_visualization(self, state):
        if state is None:
            self.status_label.setText(t("algo_vis.status_complete"))
            self.on_pause()
            return

        self.current_state = state
        self.scene.clear()

        self.status_label.setText(t("algo_vis.status_prefix") + state.get("description", ""))

        state_type = state.get("type")

        if state_type == "sorting":
            self.draw_sorting(state)
        elif state_type == "search":
            self.draw_search(state)
        elif state_type == "graph":
            self.draw_graph(state)
        elif state_type == "shortest_path":
            self.draw_shortest_path(state)
        elif state_type == "convex_hull":
            self.draw_convex_hull(state)
        elif state_type == "clustering":
            self.draw_clustering(state)

    # ------------------------------------------------------------------
    # Theme helpers & Drawing helpers（三主题自适应，无硬编码色值）
    # ------------------------------------------------------------------
    def _tokens(self) -> dict[str, str]:
        return get_tokens(get_current_theme())

    def _apply_scene_theme(self, theme_name: str) -> None:
        tokens = get_tokens(theme_name)
        self.scene.setBackgroundBrush(QBrush(QColor(tokens["bg.canvas"])))

    def _on_theme_changed(self, theme_name: str) -> None:
        self._apply_scene_theme(theme_name)
        if self.current_state is not None:
            self.update_visualization(self.current_state)

    def draw_sorting(self, state):
        arr = state.get("array", [])
        comparing = state.get("comparing", [])
        swapping = state.get("swapping", [])
        sorted_indices = state.get("sorted", [])

        if not arr:
            return

        tokens = self._tokens()
        max_val = max(arr) if arr else 1
        bar_width = 40
        bar_spacing = 10
        start_x = 50
        start_y = 200

        for i, val in enumerate(arr):
            x = start_x + i * (bar_width + bar_spacing)
            height = (val / max_val) * 150

            color = QColor(tokens["obj.point"])

            if i in comparing:
                color = QColor(tokens["danger"])
            elif i in swapping:
                color = QColor(tokens["warning"])
            elif i in sorted_indices:
                color = QColor(tokens["success"])

            bar = QGraphicsRectItem(x, start_y - height, bar_width, height)
            bar.setBrush(QBrush(color))
            bar.setPen(QPen(QColor(tokens["border.strong"]), 1))
            self.scene.addItem(bar)

            label = QGraphicsTextItem(str(val))
            label.setDefaultTextColor(QColor(tokens["fg.primary"]))
            label.setPos(x + bar_width / 2 - 10, start_y + 5)
            self.scene.addItem(label)

    def draw_search(self, state):
        arr = state.get("array", [])
        target = state.get("target", 0)
        search_range = state.get("search_range", (-1, -1))
        mid = state.get("mid", -1)

        if not arr:
            return

        tokens = self._tokens()
        max_val = max(arr) if arr else 1
        bar_width = 30
        bar_spacing = 8
        start_x = 50
        start_y = 200

        for i, val in enumerate(arr):
            x = start_x + i * (bar_width + bar_spacing)
            height = (val / max_val) * 150

            color = QColor(tokens["border.subtle"])

            if search_range[0] <= i <= search_range[1]:
                color = QColor(tokens["obj.function"])
            if i == mid:
                color = QColor(tokens["accent.base"])
            if val == target:
                color = QColor(tokens["success"])

            bar = QGraphicsRectItem(x, start_y - height, bar_width, height)
            bar.setBrush(QBrush(color))
            self.scene.addItem(bar)

    def draw_graph(self, state):
        nodes = state.get("nodes", [])
        edges = state.get("edges", [])
        visited = state.get("visited", {})
        current = state.get("current", -1)

        tokens = self._tokens()
        node_positions = {}
        center_x = 300
        center_y = 150
        radius = 100

        for i, node in enumerate(nodes):
            x = center_x + radius * (1 if i < len(nodes) / 2 else -1) * (0.5 + 0.5 * (i % 3))
            y = center_y + radius * (i % 2 - 0.5) * 2
            node_positions[node] = (x, y)

            color = QColor(tokens["bg.elevated"])
            if visited.get(node, False):
                color = QColor(tokens["success"])
            if node == current:
                color = QColor(tokens["accent.base"])
                node_radius = 25
            else:
                node_radius = 20

            circle = QGraphicsEllipseItem(x - node_radius, y - node_radius, node_radius * 2, node_radius * 2)
            circle.setBrush(QBrush(color))
            circle.setPen(QPen(QColor(tokens["fg.primary"]), 2))
            self.scene.addItem(circle)

            label = QGraphicsTextItem(str(node))
            label.setDefaultTextColor(QColor(tokens["fg.primary"]))
            label.setPos(x - 5, y - 5)
            label.setFont(QFont("Arial", 12, QFont.Bold))
            self.scene.addItem(label)

        for edge in edges:
            x1, y1 = node_positions[edge[0]]
            x2, y2 = node_positions[edge[1]]

            color = QColor(tokens["border.strong"])
            if visited.get(edge[0], False) and visited.get(edge[1], False):
                color = QColor(tokens["success"])

            line = QGraphicsLineItem(x1, y1, x2, y2)
            line.setPen(QPen(color, 2))
            self.scene.addItem(line)

    def draw_shortest_path(self, state):
        nodes = state.get("nodes", [])
        edges = state.get("edges", [])
        distances = state.get("distances", {})
        visited = state.get("visited", {})
        current = state.get("current", -1)

        tokens = self._tokens()
        node_positions = {}
        center_x = 300
        center_y = 150
        radius = 100

        for i, node in enumerate(nodes):
            x = center_x + radius * (1 if i < len(nodes) / 2 else -1) * (0.5 + 0.5 * (i % 3))
            y = center_y + radius * (i % 2 - 0.5) * 2
            node_positions[node] = (x, y)

            color = QColor(tokens["bg.elevated"])
            if visited.get(node, False):
                color = QColor(tokens["success"])
            if node == current:
                color = QColor(tokens["accent.base"])

            circle = QGraphicsEllipseItem(x - 20, y - 20, 40, 40)
            circle.setBrush(QBrush(color))
            circle.setPen(QPen(QColor(tokens["fg.primary"]), 2))
            self.scene.addItem(circle)

            label = QGraphicsTextItem(str(node))
            label.setDefaultTextColor(QColor(tokens["fg.primary"]))
            label.setPos(x - 5, y - 5)
            self.scene.addItem(label)

            dist = distances.get(node, float("inf"))
            dist_label = QGraphicsTextItem(f"{dist:.1f}")
            dist_label.setDefaultTextColor(QColor(tokens["fg.secondary"]))
            dist_label.setPos(x - 10, y + 25)
            dist_label.setFont(QFont("Arial", 10))
            self.scene.addItem(dist_label)

        for edge in edges:
            x1, y1 = node_positions[edge[0]]
            x2, y2 = node_positions[edge[1]]
            weight = edge[2] if len(edge) > 2 else 1

            line = QGraphicsLineItem(x1, y1, x2, y2)
            line.setPen(QPen(QColor(tokens["border.strong"]), 2))
            self.scene.addItem(line)

            mid_x = (x1 + x2) / 2
            mid_y = (y1 + y2) / 2
            weight_label = QGraphicsTextItem(str(weight))
            weight_label.setDefaultTextColor(QColor(tokens["fg.secondary"]))
            weight_label.setPos(mid_x - 8, mid_y - 10)
            self.scene.addItem(weight_label)

    def draw_convex_hull(self, state):
        points = state.get("points", [])
        hull = state.get("hull", [])

        if not points:
            return

        tokens = self._tokens()
        min_x = min(p[0] for p in points)
        max_x = max(p[0] for p in points)
        min_y = min(p[1] for p in points)
        max_y = max(p[1] for p in points)

        scale = 400 / max(max_x - min_x, max_y - min_y, 1e-6)
        offset_x = 50 - min_x * scale
        offset_y = 200 - max_y * scale

        for point in points:
            x = point[0] * scale + offset_x
            y = -point[1] * scale + offset_y

            color = QColor(tokens["accent.base"]) if point in hull else QColor(tokens["obj.point"])

            circle = QGraphicsEllipseItem(x - 5, y - 5, 10, 10)
            circle.setBrush(QBrush(color))
            self.scene.addItem(circle)

        if len(hull) > 1:
            for i in range(len(hull)):
                p1 = hull[i]
                p2 = hull[(i + 1) % len(hull)]

                x1 = p1[0] * scale + offset_x
                y1 = -p1[1] * scale + offset_y
                x2 = p2[0] * scale + offset_x
                y2 = -p2[1] * scale + offset_y

                line = QGraphicsLineItem(x1, y1, x2, y2)
                line.setPen(QPen(QColor(tokens["obj.segment"]), 2))
                self.scene.addItem(line)

    def draw_clustering(self, state):
        points = state.get("points", [])
        centers = state.get("centers", [])
        clusters = state.get("clusters", [])

        if not points:
            return

        tokens = self._tokens()
        colors = [
            QColor(tokens["obj.point"]),
            QColor(tokens["obj.segment"]),
            QColor(tokens["obj.circle"]),
            QColor(tokens["obj.conic"]),
            QColor(tokens["obj.polygon"]),
            QColor(tokens["obj.locus"]),
        ]

        for i, cluster in enumerate(clusters):
            color = colors[i % len(colors)]
            for point in cluster:
                x = point[0] * 3 + 50
                y = 250 - point[1] * 3

                circle = QGraphicsEllipseItem(x - 4, y - 4, 8, 8)
                circle.setBrush(QBrush(color))
                self.scene.addItem(circle)

        for i, center in enumerate(centers):
            x = center[0] * 3 + 50
            y = 250 - center[1] * 3

            color = colors[i % len(colors)]
            circle = QGraphicsEllipseItem(x - 8, y - 8, 16, 16)
            circle.setBrush(QBrush(color))
            circle.setPen(QPen(QColor(tokens["fg.primary"]), 2))
            self.scene.addItem(circle)
