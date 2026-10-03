# MathLab UI/UX 体验诊断与增量改造 PRD

| 项 | 内容 |
|---|---|
| 文档版本 | v1.0 |
| 作者 | 许清楚（产品经理） |
| 日期 | 2026-02-20 |
| 适用版本 | MathLab (Axiom) v3.8.0 |
| 技术栈 | PySide6 (Qt6) 桌面应用 |
| 项目根 | `J:/PROJECT/Python project/Axiom Mathematics Panel` |
| 文档性质 | UI/UX 诊断 + 增量改造需求，不含总体重构方案 |

---

## 1. TL;DR

**一句话结论**：MathLab 的 UI 难受不是因为"没做主题"，而是因为**同时存在 3 套互相打架的样式系统**（`styles.qss` 深色 Fluent 流、`theme_manager` 内联调色板、`ui/` 层 173 处内联 `setStyleSheet` + 411 处硬编码色值），它们都没有单一真源，导致**主题切换基本失效、首屏信息架构错位、交互反馈缺失**——本次应通过"统一主题令牌 → 补全 QSS 控件体系 → 修 IA 与反馈"的增量路径解决，**不迁移框架、不动 core 层业务逻辑**。

| 严重度 | 数量 | 定义 |
|---|---|---|
| **P0（必修）** | **11** | 用户每天都会撞到、直接造成"这软件看着就糙"印象的功能性缺陷 |
| **P1（重要）** | **12** | 明显影响教学/学习效率，但可以容忍一个版本 |
| **P2（打磨）** | **2** | 观感细节与长期技术债 |
| **合计** | **25** | 全部附带真实代码证据（`文件:行号`） |

**最致命的 5 个问题**（详见第 3 节）：

1. **主题系统三重覆盖** → 切换主题后主窗口外观几乎不变，主题形同虚设
2. **偏好设置对话框完全写死浅色** → 深色主题下点开是一整屏刺眼的白
3. **几何画板永远纯白且零主题感知** → 深色外壳里嵌一块白板，视觉撕裂
4. **撤销/重做是有快捷键的假菜单** → 违背用户肌肉记忆
5. **无任何窗口状态持久化** → 每次重启窗口尺寸/Dock 布局全部复位

---

## 2. 用户画像与核心场景

### 2.1 用户画像

| 画像 | 特征 | 环境 |
|---|---|---|
| **A. 中学/高校数学教师** | 熟练 PPT + 几何画板/GeoGebra，追求"所见即所得"，对投影可读性极度敏感 | 教室投影仪 / 希沃大屏，亮度低、色偏、观看距离远 |
| **B. 学生（自主探究）** | 习惯 VS Code / JupyterLab 工作流，键盘优先，期望响应式界面 | 个人笔记本，可能是高分屏，长时间使用 |
| **C. 作者本人** | Android 原生背景，Material 3 / Jetpack Compose 熟练 | Windows 桌面，对"控件没对齐、圆角不统一、状态色缺失"零容忍 |

### 2.2 核心场景与 UI 诉求

| 场景 | 用户动作链 | UI 诉求（对应本 PRD 需求） |
|---|---|---|
| **S1 课堂演示**（教师，投影） | 打开软件 → 直接画圆/线段 → 讲解 → 拖动点追踪轨迹 → 必要时开 AI 讲解 | ①首屏必须落在**几何画板**而非 Notebook（R-08）<br>②画布与外壳配色一致、投影下对比度足够（R-04）<br>③画布 Toolkit 图标有 tooltip，误操作可**真撤销**（R-13）<br>④字号/控件尺寸在远距可读（无障碍-01） |
| **S2 自主探究**（学生，长时间） | Ctrl+K 唤起 Omni-Bar → 运行 Python → 在 Notebook 迭代 → 切多个面板对比 | ①窗口尺寸/Dock 布局**跨会话记忆**（R-16）<br>②快捷键符合桌面惯例、不抢 WebView 焦点（R-17）<br>③长任务有加载态，错误有 Toast（R-14）<br>④深色主题完整可用（主题-01~04） |
| **S3 备课/配置**（教师、低频） | Ctrl+, 打开偏好 → 改主题/语言 → 立即看效果 | ①偏好对话框跟随当前主题（R-03）<br>②主题切换后**全控件生效**且即时（验收 A-01）<br>③语言切换后无遗漏、无"原始 key 字符串"（R-20、R-22） |

**交叉结论**：三个场景叠加在一起，就是"**主题一致性 + 首屏 IA + 状态持久化 + 反馈闭环**"这四件事。其余均为打磨项。

---

## 3. UI/UX 问题清单

> 全部证据均已实际打开文件核对。行号基于仓库当前 `HEAD`。

### 3.1 P0 — 必修（11 条）

| ID | 严重度 | 分类 | 现状描述 | 证据（文件:行号） | 用户感知痛点 | 建议方向 |
|---|---|---|---|---|---|---|
| **UI-01** | P0 | 视觉一致性 | **样式三重覆盖**：①`main.py` 在 app 级载入 `styles.qss`；②`set_theme()` 用内联 QSS **整体替换** app 级样式表；③`load_stylesheet()` 又在 MainWindow **窗口级**再设一次。Qt 规则：**窗口级样式表优先级高于 app 级，且向下继承到所有子控件**。三者叠加后 MainWindow 子树永远被第 ③ 套（深色 `styles.qss`）统治，`set_theme()` 只能影响主窗口之外的独立窗口 | `mathlab/main.py:202-204`<br>`mathlab/utils/theme_manager.py:126-192`<br>`mathlab/ui/_mixin_ui_setup.py:199`<br>`mathlab/ui/main_window.py:103,117` | "我在偏好里切成浅色，主界面一点没变；但弹出来的独立窗口变白了" —— 典型"软件失灵"观感 | 收敛为**单一入口**：`theme_manager` 作为唯一真源，产出完整 QSS（含 token），其余两处改为调用它；删除 `load_stylesheet()` 的窗口级注入 |
| **UI-02** | P0 | 视觉一致性 | `load_stylesheet()` 用字符串 `replace` 把 11 个旧色值换成主题色，但**其中 10 个色值在当前 `styles.qss` 里根本不存在**，是全然的死代码；唯一命中的 `#FFFFFF`（`QPushButton:pressed` 的文字色）还被**错配成 `console_fg`**，语义完全错误 | `mathlab/ui/_mixin_ui_setup.py:187-197`<br>对照 `mathlab/ui/styles.qss`（全文仅 1 处命中，在 `:62`） | 主题切换对所有非 Dark 主题几乎无效果；即便生效也是错的 | 废弃 `replace` 方案，改为**令牌化模板渲染**（见第 6 节 design token） |
| **UI-03** | P0 | 视觉一致性 | **偏好设置对话框完全硬编码浅色**：17 处 `background: white`，另有大量 `#0b1c30` / `#c3c6d7` 内联样式；全文**无任何 `get_theme_colors()` 调用**（仅 `:120` 用 `get_current_theme()` 取默认值） | `mathlab/ui/preferences_dialog.py:321,354,360,374,385,416,426,452`（共 17 处）<br>`grep get_theme_colors preferences_dialog.py` → 无命中 | 深色主题下点开设置，**瞬间一片刺眼纯白**，这是最容易被一眼抓住的破绽 | 对话框所有控件改用 QSS class 选择器 + token，删除全部内联 `setStyleSheet` |
| **UI-04** | P0 | 视觉一致性 | **几何画板永远纯白、完全零主题感知**：背景刷死为 `#ffffff`；画布对象色写死浅色调色板（`QColor(0,120,215)` / `#004ac6` / `#4b41e1` / `#006058` / `#9333ea`，恰好是 `THEMES["light"]` 的值）；网格与主轴画笔为 `#d3e4fe` / `#737686`，且被 `@lru_cache(maxsize=1)` 缓存**永不失效**；全文 0 处 theme 引用 | `mathlab/ui/canvas.py:292`（白背景）<br>`canvas.py:728-799, 830-839, 870-928`（对象色）<br>`canvas.py:58-67`（缓存画笔）<br>`grep -n "theme" canvas.py` → **无命中** | 深色外壳里嵌一块白板 + 淡蓝网格，界面像"两个软件拼起来"；投影时白板与暗色面板亮度反差刺眼 | 抽出 `CanvasTheme` 对象，由 `theme_manager` 下发；`lru_cache` 增加 theme key 或改为失效重生成 |
| **UI-05** | P0 | 视觉一致性 | **QSS 控件覆盖严重不全**：107 行的 `styles.qss` 只定义了 **13 个控件类**（`QMainWindow/QDialog/QWidget/QDockWidget/QLineEdit/QPlainTextEdit/QTextBrowser/QSpinBox/QComboBox/QPushButton/QTabWidget/QTabBar/QScrollBar`）。代码中广泛使用但**完全无样式**的控件： | `mathlab/ui/styles.qss`（全文 108 行）<br>统计：`QGroupBox`(4 文件)、`QSlider`(7)、`QScrollArea`(9)、`QTextEdit`(4)、`QDoubleSpinBox`(3)、`QCheckBox`(3)、`QListWidget`(2，命令面板在用)、`QSplitter`、`QRadioButton`、`QToolTip`、`QProgressBar`、`QStatusBar`、`QToolBar`、`QTreeWidget` | Slider/GroupBox/CheckBox/下拉列表全用 Qt 原生默认渲染，**在深色背景上突兀发白**，是"没做完"的核心观感来源 | 建立分层 QSS：base → widget → component → utility，逐类补齐并附验收截图清单 |
| **UI-06** | P0 | 视觉一致性 | **全局污染选择器**：`QMainWindow, QDialog, QWidget { background-color: #0F172A; color: #F8FAFC; }`。`QWidget` 是几乎所有控件的基类，此规则会**递归命中整棵子树**，覆盖掉任何按类型细化的背景设置，也是 UI-03/UI-04 内联样式必须到处硬扛的根因 | `mathlab/ui/styles.qss:6-9` | 开发者只能靠"每个控件再加一行内联样式"来对抗全局规则 → 样式彻底失控 | 用 `QWidget#xxx` / 具体类型选择器替代裸 `QWidget`；仅保留 `#central_root` 级别的容器背景 |
| **UI-07** | P0 | 视觉一致性（技术债） | **样式碎片化到无法治理**：`ui/` 层共 **173 处内联 `setStyleSheet`**、**411 处硬编码 HEX 色值**，分布于 20 个文件；`styles.qss` 却只有 107 行。二者比例严重失衡，"全局样式表"名存实亡 | 统计：`preferences_dialog.py` 55 处 / `ai_tools_panel.py` 19 / `properties_panel.py` 16 / `command_bar.py` 11 / `console.py` 1 …<br>硬编码色：`preferences_dialog.py` 90 / `ai_tools_panel.py` 31 / `algo_vis_panel.py` 30 / `canvas.py` 29 / `notebook_panel.py` 28 | 任何配色调整都要改 20 个文件；改一处漏三处，界面永远"半新半旧" | 建立 design token（第 6 节）+ 统一 QSS 文件；内联样式按模块分批清零（P0 先清 `preferences_dialog` / `canvas` / `properties_panel`） |
| **UI-08** | P0 | 信息架构 | **中央区首个 Tab 是 Notebook 而不是几何画板**。打开软件——一个"交互式数学平台"——落在的不是画布，而是一个代码笔记本；几何画板排在第 2 个 Tab | `mathlab/ui/_mixin_ui_setup.py:59`（`addTab(self.notebook, ...)`）<br>`_mixin_ui_setup.py:60`（画板在第 2） | 教师 S1 场景："我打开就是想画图"，结果第一眼是空白 Notebook，得先切一次 Tab | 默认 Tab 序改为 **画板 → Notebook → Mini GeoGebra → Jupyter**；Notebook 改为按需/记忆上次选择 |
| **UI-13** | P0 | 交互反馈 / 可用性 | **撤销/重做是"假菜单"**：编辑菜单提供 `撤销 Ctrl+Z` / `重做 Ctrl+Y` 两个带标准快捷键的条目，但 `triggered` 只绑定了一个 lambda，向控制台 Dock 打印"功能尚未实现" | `mathlab/ui/_mixin_menus.py:65-67`（快捷键）<br>`_mixin_menus.py:175-188`（桩实现） | 用户误删一个圆后**本能按 Ctrl+Z**，毫无反应，只能重画；且提示藏在可能已隐藏的控制台里，等于没有反馈 | 二选一：①本期实现 `CommandManager` 撤销栈（已有 `Command`/`CommandManager` 基础设施，见 `main_window.py:80`）；②暂未实现则**移除菜单项与快捷键**，避免给出错误承诺（推荐 ①，但需确认工作量） |
| **UI-16** | P0 | 可用性 | **零窗口状态持久化**：全仓库 **0 处** `QSettings` / `saveGeometry` / `restoreGeometry` / `saveState` / `restoreState`；窗口位置尺寸写死 `setGeometry(100,100,1200,800)`；Dock 拖拽/显隐/分割比例、最后停留的 Tab、列宽**全部退出即丢** | `mathlab/ui/main_window.py:71`（硬编码 geometry）<br>`grep -rn "QSettings\|saveState\|saveGeometry" mathlab/` → **无命中**<br>偏好对话框同样写死：`preferences_dialog.py:104-105` | 每次重启都要重新摆一遍面板；对 S2 高频学生用户是持续性折磨，也是最"不专业"的信号 | 引入 `QSettings`（组织名 MathLab）：`closeEvent` 存 geometry+state，`__init__` 恢复；首次启动给默认布局；提供"恢复默认布局"入口 |
| **UI-20** | P0 | 国际化 | **21 个 i18n key 缺失 → 界面直接显示原始 key 字符串**。`t()` 在查不到时静默返回 key 本身，导致 UI 上真的出现 `preferences.snapping`、`preferences.scheme_system` 这类原始 key | `mathlab/utils/i18n_manager.py:154-162`（`return key`）<br>缺失清单含：`preferences.snapping / snap_grid / snap_points / snap_off / scheme_dark / scheme_light / scheme_system / color_scheme / factory_reset / reset_confirm / hardware_acceleration / snapping / autosave_* / fast / slow`，`math_console.workspace / vars`，`algebra_panel.new_name`，`properties_panel.thickness` 等 21 个<br>引用点：`preferences_dialog.py:445,499,633,965`、`math_console.py:422`、`algebra_panel.py:375`、`properties_panel.py:240` | 英文/中文界面上直接蹦出 `preferences.factory_reset` 这种开发内部字符串，是**最露怯**的一类问题 | 补齐 locale 文件；同时给 `t()` 增加**缺失键收集与调试告警**（Debug 构建抛醒目标记），并在 CI 加"扫描 `t()` 字面量 vs locale 覆盖率"检查 |

### 3.2 P1 — 重要（12 条）

| ID | 严重度 | 分类 | 现状描述 | 证据（文件:行号） | 用户感知痛点 | 建议方向 |
|---|---|---|---|---|---|---|
| **UI-09** | P1 | 信息架构 | 三个核心能力面板**默认隐藏**：函数探索器、算法可视化、AI 工具全部 `hide()`。用户不知道这些存在于 View 菜单里，长期只用到左右两侧的代数/属性面板 | `_mixin_ui_setup.py:146`（函数探索器 `hide()`）<br>`_mixin_ui_setup.py:151`（算法可视化 `hide()`）<br>`_mixin_ui_setup.py:156`（AI 工具 `hide()`） | 花钱做的功能用户找不到；首次会话发现不了 AI 能力 | 首启（无持久化状态时）采用"教学友好默认布局"：AI 工具面板以折叠 Tab 形式**可见**但非焦点；算法可视化并入 Right Dock Tab 组（已 `tabify`，`:158`）并默认可见 |
| **UI-10** | P1 | 视觉一致性 / 国际化 | Dock 标题被强制 `.upper()` 大写。中文标题无效（无大小写），英文标题全大写导致词形识别变差；若 i18n key 缺失还会把 `PANEL.TITLE` 这种原始 key 大写砸给用户 | `_mixin_ui_setup.py:123,127,131,145,150,155`<br>`_mixin_dialogs.py:207-214`<br>插件面板同样：`_mixin_ui_setup.py:282` | 英文界面标题像系统报错；且 `.upper()` 在中文场景是无效代码 | 取消 `.upper()`，改用 QSS 中的 `font-weight` / `letter-spacing` 表达层级；若确有设计诉求，仅对**纯 ASCII 标题**做 small-caps |
| **UI-11** | P1 | 可用性 | **"教程"是死菜单项**：`tutorial_action` 被创建并加入帮助菜单，但全仓库**从未 `triggered.connect`**，点击毫无反应 | `_mixin_menus.py:151`（创建）<br>`_mixin_menus.py:153`（加入菜单）<br>`grep -rn "tutorial_action" mathlab/` → 仅 3 处，无 connect | 用户点了没反应，判定"软件坏了" | 未实现即移除；或先挂一个引导占位（首启向导，见 UI-09） |
| **UI-12** | P1 | 信息架构 | **主题入口双轨并存**：`视图 > 主题` 走旧的简易 `show_theme_dialog`（只有 3 个选项的下拉框），而 `Ctrl+,` / `视图 > 偏好设置` 走 975 行的全新 `PreferencesDialog`。两套 UI 视觉语言完全不同，且 `_toggle_theme` 只在 dark↔light 间二元切换，Sepia 永远碰不到 | `_mixin_menus.py:205`（`theme_action → show_theme_dialog`）<br>`_mixin_menus.py:207`（`preferences_action → show_preferences_dialog`）<br>`_mixin_dialogs.py:36-39`（`_toggle_theme` 二元） | 用户在两个入口得到不一致的结果；浅色/棕褐主题难以触达 | 统一到 `PreferencesDialog`；`视图 > 主题` 改为打开偏好并定位到"外观"页；`_toggle_theme` 改为三主题循环或直接删除 |
| **UI-14** | P1 | 交互反馈 | **反馈机制严重不足**：全项目**无 Toast / 通知中心组件**；异步结果只能靠 `statusBar().showMessage()`（且大量调用未设超时，长期驻留）；模态 `QMessageBox` 有 30 处，打断心流；**加载态仅 Jupyter 面板一个 `_LoadingCard`**，其余（AI 推理、函数拟合、聚类、LaTeX 渲染）统统没有 loading / 空 / 错误三态 | `mathlab/ui/_mixin_ai.py:396,407,410,413,426,441,458,465,483`（statusBar）<br>`grep -rn "class Toast\|def toast" mathlab/ui/` → 无<br>`mathlab/ui/jupyter_panel.py:56`（唯一 `_LoadingCard`） | 点下去没反应 → 不确定有没有执行 → 重复点击；错误只有 state bar 一闪而过 | 新增轻量 `ToastService`（非模态、右下角堆叠、3s 淡出）+ `LoadingState` 组件；为 AI 四大任务补 loading/empty/error 三态 |
| **UI-15** | P1 | 视觉一致性 | **主题切换后画布不刷新**：网格/主轴画笔被 `@lru_cache(maxsize=1)` 缓存且无任何失效机制；所有已渲染的几何对象保留创建时的硬编码颜色；`devicePixelRatio` 变化也无响应 | `canvas.py:58-62`（`_get_grid_pen` 缓存）<br>`canvas.py:65-67`（`_get_origin_pen`）<br>`canvas.py:728-799`（对象色写死） | 切换主题后面板变了、画布还是旧配色，必须重启才一致 | 主题变更信号 → 画布 `on_theme_changed()`：清 cache、重建画笔、遍历 `object_map` 重刷笔刷，并 `scene().invalidate()` |
| **UI-17** | P1 | 可用性 / 国际化 | **快捷键体系混乱**：①`Ctrl+P`（通用惯例=打印）与 `Ctrl+Shift+P` **都**绑到命令面板；②`Ctrl+K`（Omni-Bar）与命令面板职责重叠且语义不明；③`QShortcut(QKeySequence, self)` **默认 `WindowShortcut` 上下文**，焦点在嵌入的 JupyterLab / Monaco 等 WebEngine 控件里时仍会被主窗口抢走；④删除是 `Delete` 而无 macOS `Cmd+Backspace` 映射；⑤无 Mac 的 `Ctrl→Cmd` 统一映射 | `_mixin_ui_setup.py:164`（Ctrl+Shift+P）<br>`_mixin_ui_setup.py:168`（Ctrl+P）<br>`main_window.py:132`（Ctrl+K）<br>`_mixin_menus.py:65-67,103,120` | 在 Jupyter 里想打印/操作却被弹出命令面板；双入口让用户记不住到底按哪个 | 建立集中式 `ShortcutRegistry`（含冲突检测 + 上下文优先级）：`Ctrl+P` 改绑打印/导出或释放；WebEngine 焦点时禁用 WindowShortcut；引入 `KeySequence` 跨平台归一 helper |
| **UI-18** | P1 | 可用性 / 无障碍 | **纯图标工具栏零 tooltip**：工具栏 `ToolButtonIconOnly` 且 iconSize 仅 20×20，6 个工具 action（选择/点/线段/圆/多边形/平移）**无一设置 `setToolTip`**；仅语言与设置两个按钮有 tooltip | `_mixin_menus.py:226-227`（IconOnly + 20px）<br>`_mixin_menus.py:248-255`（6 个 action）<br>`grep -n "setToolTip" _mixin_menus.py` → 仅 `:281,:304` | 新用户面对 6 个图标全靠猜；投影演示时无法快速定位工具 | 为每个 tool action 设置 `setToolTip`（含快捷键提示）与 `setAccessibleName`；工具栏提供"图标+文字"可选项 |
| **UI-19** | P1 | 视觉一致性 | **工具栏按钮硬编码浅色内联样式**：语言按钮背景 `#f8f9ff`、文字 `#434655`、hover 边框 `#004ac6`；设置按钮 hover `#e5eeff`。这些都与主题无关，深色主题下永远是一小块"浅色贴片" | `_mixin_menus.py:284-299`（lang_btn）<br>`_mixin_menus.py:306-315`（settings_btn） | 深色工具栏上两个突兀的浅色按钮，细节失控 | 改为 `QPushButton#toolbar_action` 选择器 + token；hover/pressed 走统一 `Interactable` 基类样式 |
| **UI-21** | P1 | 国际化 | **大量硬编码中文文案**，完全绕过 i18n，英文界面下突现中文 | `_mixin_menus.py:100`（`"数学控制台 (Octave)"`）<br>`_mixin_menus.py:139`（`"⚡ 信号处理实验室 (FFT)"`）<br>`_mixin_menus.py:140`（`"🚀 极致深渊：GPU 分形探索器"`）<br>`_mixin_ui_setup.py:82`（`"🌌 Jupyter 工作区"`）<br>`ai_tools_panel.py:635,724,745,1015,1019,1023,1026,1033`<br>`function_explorer_panel.py:353,363`<br>`code_editor.py:264,307,316`<br>`complex_explorer.py:13`<br>`jupyter_panel.py:106,111` | 中英混杂像半成品；"极致深渊"这类命名也不符合工具软件的信息密度原则 | 全部收敛到 locale；emoji 作为状态装饰可接受，但**不进菜单正式名称**；统一术语表（功能命名规范化） |
| **UI-22** | P1 | 国际化 | **语言切换重绘覆盖不全**：`retranslate_ui()` 只刷新 `Tab 0 / Tab 1` 两个固定下标，第 3、4 个 Tab（`Mini GeoGebra`、`🌌 Jupyter 工作区`）是硬编码字符串**永不刷新**；`CommandPalette` / `OmniBar` / 画布内标签也不在重绘链上 | `_mixin_dialogs.py:146-148`（仅 Tab 0/1）<br>`_mixin_ui_setup.py:62,82`（硬编码 Tab 标题）<br>`_mixin_dialogs.py:150-226`（肉眼可见的遗漏） | 切换语言后界面半中半英，得像残缺的本地化 | 改为遍历 `central_tabs` 全量刷新；Tabs 与具名面板统一注册 `retranslate_ui` 契约（建议引入 `ITranslatable` 协议并 register 到中心列表） |
| **UI-23** | P1 | 性能 | **启动路径阻塞**：`MainWindow.__init__` 在首帧之前**同步**执行重型初始化——`_init_engines()` 同时构造 `GeometryEngine / CASProvider / PythonREPL / AIManager / AlgoAnimator / ProjectManager / SandboxManager` 并导入重量级依赖；IPC Server 启动；`AutoSaver.check_and_recover()`；**`OmniBar(self)` 在 `__init__` 里直接实例化一个 `QWebEngineView`**（等于同步起一套 Chromium）。仅 AI/ECharts/插件被推迟 | `main_window.py:77`（`_init_engines()`）<br>`main_window.py:89-91`（IPC server start）<br>`main_window.py:120-121`（AutoSaver）<br>`main_window.py:129`（`OmniBar` = QWebEngineView）<br>`main_window.py:138`（`_deferred_init`）<br>`main_window.py:168`（`AutocompleteTextEdit` 同步实例化）<br>`mathlab/core/cas_provider.py:18,35`（sympy 延迟导入未完全延后） | 冷启动黑屏/白屏时间不可控，`__init__` 里任何一处慢（如 sympy/AI 依赖）用户都只看到"没反应"；且打包版依赖 `pyi_splash`，开发模式彻底无反馈 | 两阶段启动：①最小窗口 + `QSplashScreen`/内置加载卡（含阶段文案）先显示；②OmniBar 的 WebEngine 延迟到首次 `summon` 再实例化；③引擎全部走 lazy property；④在 `_deferred_init` 分段 `(0ms/50ms/100ms)` 派发，避免单帧长任务 |

### 3.3 P2 — 打磨（2 条）

| ID | 严重度 | 分类 | 现状描述 | 证据（文件:行号） | 用户感知痛点 | 建议方向 |
|---|---|---|---|---|---|---|
| **UI-24** | P2 | 视觉一致性 | **画布显式关闭抗锯齿**：`setOptimizationFlag(QGraphicsView.DontAdjustForAntialiasing, True)`。对一个以绘制曲线（圆、椭圆、双曲线、抛物线、函数图像）为核心的产品，这是直接牺牲核心视觉资产 | `canvas.py:289` | 曲线边缘可见锯齿，投影放大后尤其明显，观感"廉价" | 默认开启 `Antialiasing` + `SmoothPixmapTransform`；提供"性能优先"开关给低端机（已在偏好中预留 graphics 页） |
| **UI-25** | P2 | 视觉一致性 | **语义色与图标滥用**：发送按钮被永久染红 `#E74C3C`（红色在 UI 语义中=停止/危险）；讲解气泡卡死白底（`rgba(255,255,255,.95)` + `#333` 文字）不跟随主题；emoji 被当作正式 UI 图标使用（`⏹ 停止生成`、`✍️ 生成中...`、`🌌`、`⚡`、`🚀`）；Notebook 直接照搬 VS Code 深色调色板（`#252526`/`#1e1e1e`/`#cccccc`）虽处深色 Mode 尚可，但浅色主题下永远黑着 | `ai_tools_panel.py:636`（红色发送按钮）<br>`ai_tools_panel.py:189-206`（写死 `#1e1e1e`）、`:258,:277,:311,:923,:927`<br>`floating_bubble.py:18-27`（白底气泡）<br>`notebook_panel.py:43,49,56,72,84,103,116,204,233,236`<br>`properties_panel.py:57,143,191,257,296,324,368-390`<br>`function_explorer_panel.py:70,155,164,202,226,273,279,304`<br>`math_console.py:115,171-174` | 红色按钮让用户犹豫"这是不是危险操作"；各处子系统各用一套调色板（VS Code 风 / Material 风 / Tailwind 风），整体不成一个东西 | 建立语义色契约（primary/success/warning/danger/neutral 各自唯一用途）；emoji 限用于状态行；逐步把各子系统调色板迁移到统一 token（分批进行，避免一次性大改） |

---

## 4. 改造目标与验收标准

### 4.1 量化目标

| 编号 | 目标 | 基线（当前） | 目标值 | 验证方法 |
|---|---|---|---|---|
| **A-01** | 主题切换控件生效覆盖率 | ~30%（`styles.qss` 仅覆盖 13 类；画布/偏好/AI/Notebook 全部游离） | **100%** 界面控件随主题变化 | 附录式对照清单：对 13 类基础控件 + 12 类补充控件 + 5 个自定义面板，逐一切换 3 主题截图 diff，要求无"未变色"残留 |
| **A-02** | 主题配置入口数量 | 3 个互相覆盖的入口（`main.py` / `theme_manager` / `load_stylesheet`） | **1 个** | 静态检查：`grep -rn "app.setStyleSheet\|self.setStyleSheet(" mathlab/` 在 `ui/` 层结果为 0（除 token 渲染器），且 `set_theme()` 是唯一写入点 |
| **A-03** | 内联样式 / 硬编码色值 | 173 处 / 411 处 | **≤ 20 处 / ≤ 40 处**（仅允许极个别动态图表场景），且 `preferences_dialog.py` / `canvas.py` / `properties_panel.py` 归零 | 脚本统计 `grep -c setStyleSheet` + HEX 正则，纳入 CI 卡口（超阈值 fail） |
| **A-04** | 冷启动首屏可见时间 | 实测需补：黑色/空白窗口，依赖 `pyi_splash`（打包才有） | **≤ 2.0s**（Windows 桌面，SSD，第 2 次启动）出现可交互画布 | `QApplication` 启动到 `MainWindow.showEvent` 打点；用 `time.perf_counter()` 分段埋点（engine / om_bar / deferred），输出启动耗时诊断到日志 |
| **A-05** | 窗口状态持久化 | 无 | 100% 恢复：几何位置 + Dock 布局 + 显隐 + 分割比例 + 末选 Tab | 手工：拖动 dock → 重启 → 布局一致；提供"恢复默认布局"按钮 |
| **A-06** | i18n key 覆盖率 | 330/351（缺 21） | **100%**，`t()` 不再向 UI 泄漏原始 key | CI 脚本：AST 扫描所有 `t("literal")` → 与 `locale/*.json` 求差，差集非空则 fail；运行时 Debug 构建对缺失 key 返回 `⟨key⟩` 醒目包裹以便在截图 review 中发现 |
| **A-07** | 虚构/失效交互数量 | 2（撤销/重做、教程） | **0** | 遍历所有 `QAction`，静态检查每个都有 `triggered` 连接（或显式标注为 intentional-disabled 并 `setEnabled(False)`） |
| **A-08** | 长任务反馈覆盖 | 仅 Jupyter 有加载态 | AI 推理 / 函数拟合 / 聚类 / 字形识别 / LaTeX 渲染 **5 类长任务 100% 具备 loading + error 态** | 手工触发 + 断网模拟，验证 Toast 出现且文案本地化 |
| **A-09** | 快捷键冲突数 | 3（Ctrl+P 双绑、Ctrl+K 语义重叠、WebEngine 焦点抢占） | **0** | 建立 `ShortcutRegistry` 自检，冲突在启动时 log error；嵌入 WebEngine 获得焦点时 WindowShortcut 自动失效（手工在 Jupyter Tab 内按 Ctrl+P 验证不再弹出命令面板） |
| **A-10** | 无障碍基础项 | 6 个工具按钮 0 tooltip | 工具栏与主要按钮 **100% 有 `setToolTip` + `setAccessibleName`** | 遍历 `toolbar.actions()` 断言非空 tooltip |

### 4.2 回归验证方式

1. **主题矩阵截图**：`{dark, light, sepia} × {MainWindow, Preferences, Canvas, AI面板, Notebook, MathConsole}` = 18 张，人工比对每版 PR
2. **CI 静态卡口**：A-03（样式散落计数）、A-06（i18n 覆盖）、A-07（未连接 Action）三条脚本化
3. **会话恢复测试**：列入手工回归 checklist（需求 R-16）
4. **启动埋点**：`logger.info` 输出分段耗时，作为 A-04 数据源

---

## 5. 需求池

### 5.1 P0 — 本次必须完成（14 条）

| 需求ID | 优先级 | 需求描述 | 涉及文件 | 验收标准 | 工作量 |
|---|---|---|---|---|---|
| **R-01** | P0 | **统一主题入口**：确立 `theme_manager` 为唯一真源，`main.py` 与 `load_stylesheet()` 不再各自 `setStyleSheet`；`set_theme()` 输出**完整**（含全部控件配色的）QSS 而非迷你片段 | `mathlab/main.py:202-204`<br>`mathlab/utils/theme_manager.py:98-195`<br>`mathlab/ui/_mixin_ui_setup.py:176-201` | A-02：`grep` 验证仅剩 1 个写入点；A-01 三主题切换全控件生效 | 中 |
| **R-02** | P0 | **令牌化 QSS 渲染**：废弃 `replace` 字符串替换（含那 10 条死代码 + 1 条错误替换），改为基于第 6 节 token 的模板渲染 / 三套静态 QSS | `mathlab/ui/_mixin_ui_setup.py:187-197`<br>`mathlab/ui/styles.qss` | 删除全部 `replace`；浅色/棕褐主题下新增 **0 处**"仍是深色"残留 | 中 |
| **R-03** | P0 | **偏好对话框主题化**：清除 17 处 `background: white` 及全部内联样式，改用 QSS class + token | `mathlab/ui/preferences_dialog.py`（55 处内联 / 90 处硬编码色） | 深色主题下打开偏好，**无白色区块**；文件内 `setStyleSheet` 计数 ≤ 3 | 中 |
| **R-04** | P0 | **画布主题适配**：抽 `CanvasTheme`，由 `theme_manager` 下发；背景 / 网格 / 主轴 / 8 类几何对象色全部令牌化；`@lru_cache` 画笔支持主题失效 | `mathlab/ui/canvas.py:58-67, 292, 728-799, 830-839, 870-928` | 三主题下画布背景与外壳一致；切换主题画布立即重绘（无需重启）；文件 `grep theme` ≥ 3 处命中 | 大 |
| **R-05** | P0 | **QSS 控件体系补全**：补齐 `QGroupBox / QSlider / QScrollArea / QTextEdit / QDoubleSpinBox / QCheckBox / QRadioButton / QListWidget / QTreeWidget / QSplitter / QToolTip / QProgressBar / QStatusBar / QToolBar` 及深色/浅色滚动条 | `mathlab/ui/styles.qss`（107 行 → 预计 500+ 行，分层组织） | A-01 清单 100% 覆盖；上述控件在三主题下均无 Qt 原生默认外观 | 中 |
| **R-06** | P0 | **清除全局 `QWidget` 污染选择器**：改为具体类型 / `objectName` 选择器 | `mathlab/ui/styles.qss:6-9` | 删除裸 `QWidget { background-color }`；修复后无控件背景异常 | 小 |
| **R-07** | P0 | **建立 design token 单一定义**：按第 6 节落地 token 表（色板/圆角/间距/字号/阴影/动效），`theme_manager` 输出给 QSS、Python 画布代码、以及后续 all Panel 共用 | 新增 `mathlab/ui/theme_tokens.py`<br>`mathlab/utils/theme_manager.py` | 三份消费者（QSS 文本 / Python 绘制 / 常量）均从同一来源取值 | 中 |
| **R-08** | P0 | **默认 Tab 序调整**：画板置于首位；Notebook 次之 | `mathlab/ui/_mixin_ui_setup.py:59-62` | 冷启动落在几何画板；若存在持久化状态则尊重用户上次选择 | 小 |
| **R-09** | P0 | **窗口几何与布局持久化**：`QSettings` 存取 `saveGeometry()` / `saveState()`；移除硬编码 `setGeometry`；提供"恢复默认布局" | `mathlab/ui/main_window.py:71, 238-276`<br>`mathlab/ui/_mixin_dialogs.py`（新增入口） | A-05：拖动布局后重启完全还原 | 中 |
| **R-10** | P0 | **撤销/重做落地**：基于现有 `CommandManager`（`main_window.py:80`）补齐 undo/redo 栈，替换仅打印日志的桩实现 | `mathlab/ui/_mixin_menus.py:175-188`<br>`mathlab/core/command_manager.py` | Ctrl+Z 可撤销最近一次图形操作，并弹出 Toast 反馈 | 大 |
| **R-11** | P0 | **i18n key 补齐**：补 21 个缺失 key 至 `en.json` / `zh.json` | `mathlab/locale/en.json`<br>`mathlab/locale/zh.json` | A-06 覆盖率 100%；界面不再出现原始 key | 小 |
| **R-12** | P0 | **i18n 缺失防御**：`t()` 缺失时 Debug 构建返回醒目包裹值；新增 CI 覆盖率检查脚本 | `mathlab/utils/i18n_manager.py:138-177`<br>新增 `mathlab/scripts/check_i18n.py` | CI 在缺失时 fail；开发者能立刻发现 | 小 |
| **R-13** | P0 | **清理未连接 Action**：`tutorial_action` 要么实现要么移除；建立"A-07 未连接 Action"CI 检查 | `mathlab/ui/_mixin_menus.py:151,153`<br>新增脚本 | 不存在点了没反应的菜单项 | 小 |
| **R-14** | P0 | **移除 Dock 标题 `.upper()`**：改用字重/字间距表达层级 | `mathlab/ui/_mixin_ui_setup.py:123,127,131,145,150,155,282`<br>`_mixin_dialogs.py:207-214` | 英文标题恢复正常大小写；中文标题显示不变差 | 小 |

### 5.2 P1 — 重要（10 条）

| 需求ID | 优先级 | 需求描述 | 涉及文件 | 验收标准 | 工作量 |
|---|---|---|---|---|---|
| **R-15** | P1 | **首启教学友好默认布局**：AI 工具面板以 Tab 形式默认可见（非焦点）；536 行的算法可视化并入右侧 Tab 组可见 | `mathlab/ui/_mixin_ui_setup.py:146,151,156,158` | 冷启动可见 4 个核心面板；View 菜单勾选态与实际一致 | 小 |
| **R-16** | P1 | **Toast 通知服务 + 加载态组件**：新增 `ToastService`（非模态、堆叠、自动淡出，可本地化）；为 5 类长任务补 loading / empty / error 三态 | 新增 `mathlab/ui/toast.py`<br>`mathlab/ui/_mixin_ai.py:396-483`<br>`mathlab/ui/ai_tools_panel.py` | A-08；Toast 文案走 i18n；3s 后自动消失且可手动关闭 | 中 |
| **R-17** | P1 | **主题变更信号 → 画布刷新**：`theme_manager` 发信号，`GeometryCanvas` 订阅后清画笔缓存、重建所有 item 笔刷、`invalidate` 重绘 | `mathlab/utils/theme_manager.py`<br>`mathlab/ui/canvas.py:58-67` | 切换主题后画布**即时**跟随，无需重启 | 中 |
| **R-18** | P1 | **快捷键体系统一**：建立 `ShortcutRegistry`（集中登记 + 启动冲突检测）；`Ctrl+P` 让出给标准语义（改绑导出/打印或释放）；WebEngine 获得焦点时暂停 WindowShortcut；统一macOS `Cmd` 映射 | `mathlab/ui/_mixin_ui_setup.py:164-169`<br>`mathlab/ui/main_window.py:132`<br>`mathlab/ui/_mixin_menus.py:43-46,65-67,103,120` | A-09：0 冲突；Jupyter Tab 内 Ctrl+P 不再劫持 | 中 |
| **R-19** | P1 | **工具栏 tooltip 与无障碍**：6 个工具 action 补齐 `setToolTip`（含快捷键）+ `setAccessibleName`；工具栏支持"图标+文字"模式 | `mathlab/ui/_mixin_menus.py:226-255` | A-10：100% 覆盖 | 小 |
| **R-20** | P1 | **工具栏按钮样式令牌化**：lang_btn / settings_btn 内联样式清除 | `mathlab/ui/_mixin_menus.py:284-299,306-315` | 深色主题下工具栏无浅色贴片 | 小 |
| **R-21** | P1 | **统一主题入口**：`视图 > 主题` 改为打开 Preferences 并定位"外观"页；删除旧的 `show_theme_dialog` 与二元 `_toggle_theme` | `mathlab/ui/_mixin_menus.py:205`<br>`mathlab/ui/_mixin_dialogs.py:36-39,71-101` | 主题配置仅 1 个入口；Sepia 可达 | 小 |
| **R-22** | P1 | **硬编码中文文案收敛 i18n**：12+ 处（菜单、AI 状态、按钮、窗口标题）接入 locale | `_mixin_menus.py:100,139,140`<br>`_mixin_ui_setup.py:82`<br>`ai_tools_panel.py:635,724,745,1015-1033`<br>`function_explorer_panel.py:353,363`<br>`code_editor.py:264,307,316`<br>`complex_explorer.py:13`<br>`jupyter_panel.py:106,111` | 英文界面下 0 处中文残留 | 中 |
| **R-23** | P1 | **语言切换重绘全量覆盖**：遍历 `central_tabs` 全 Tab 刷新；引入 `ITranslatable` 契约并集中注册，覆盖 CommandPalette/OmniBar/各面板 | `mathlab/ui/_mixin_dialogs.py:143-226`<br>`_mixin_ui_setup.py:62,82` | 切换语言后无遗留原文 | 中 |
| **R-24** | P1 | **启动性能优化（两阶段）**：`QSplashScreen`/加载卡先行；`OmniBar` 的 WebEngine 延迟到首次调用；引擎改 lazy 加载；`_deferred_init` 分段派发 | `mathlab/ui/main_window.py:68-152`<br>`mathlab/ui/omni_bar.py:75-108` | A-04：首屏 ≤ 2s；日志输出分段耗时 | 中 |

### 5.3 P2 — 打磨（4 条）

| 需求ID | 优先级 | 需求描述 | 涉及文件 | 验收标准 | 工作量 |
|---|---|---|---|---|---|
| **R-25** | P2 | **画布启用抗锯齿**：移除 `DontAdjustForAntialiasing`，改由偏好中的"图形质量"开关控制 | `canvas.py:289` | 默认曲线平滑；低端机可降级 | 小 |
| **R-26** | P2 | **语义色治理**：发送按钮不再使用危险红；emoji 移出正式菜单名；统一命名规范 | `ai_tools_panel.py:636`<br>`_mixin_menus.py:139,140` | Review 通过：无"红色=普通操作"、菜单名无装饰性 emoji | 小 |
| **R-27** | P2 | **子系统调色板迁移（第一批）**：Notebook / 悬浮气泡 / 属性面板 / 函数探索器 / MathConsole 迁 token | `notebook_panel.py:43,49,56,72,84,103,116,204,233,236`<br>`floating_bubble.py:18-27`<br>`properties_panel.py:57,143,191,257,296,324,368-390`<br>`function_explorer_panel.py:70,155,164,202,226,273,279,304`<br>`math_console.py:115,171-174` | A-03：`ui/` 层硬编码色 ≤ 40；三主题下无子系统保留自家调色板 | 大 |
| **R-28** | P2 | **无障碍基线**：关键操作支持键盘遍历；主要控件 `accessibleName`；对比度 ≥ WCAG AA（4.5:1）校验脚本 | 全 `mathlab/ui/` | 对比度检查脚本通过；Tab 遍历可完成核心流程 | 中 |

> **工作量统计**：P0 **14 条**（小 6 / 中 6 / 大 2）；P1 **10 条**（小 4 / 中 6 / 大 0）；P2 **4 条**（小 2 / 中 1 / 大 1）；**合计 28 条**（小 12 / 中 13 / 大 3）。
>
> 建议迭代节奏：P0 一个完整迭代完成 → P1 下一个迭代 → P2 持续清理。
>
> P0 中唯一的两个"大"项：**R-04**（画布主题化，涉及画布全部绘制路径）与 **R-10**（真撤销栈，需动 `core/command_manager.py` 并等待 Q6 拍板）。

---

## 6. UI 设计规范基线（Design Token）

> 以下取值**可直接照做**。所有颜色以 **sRGB HEX** 给出。圆角/间距单位 px，动效单位 ms。

### 6.1 色彩原理

三条约束：

1. **分层背景**：`bg.base`（应用底）→ `bg.surface`（面板/卡片）→ `bg.elevated`（浮层：菜单/命令面板/Tooltip）→ `bg.canvas`（绘图纸面）。层级之间必须有可感知但不刺眼的明度差（建议 ΔL ≥ 4）。
2. **强调色单一**：全应用只允许**一个** `accent`。当前代码里存在绿 `#22C55E`（styles.qss）、蓝 `#3B82F6`/`#004AC6`（theme_manager）、紫 `#8B5CF6`（secondary）并行，全部收敛到蓝系；绿**降级为纯语义** `success`（不得用作默认按钮 hover）。
3. **语义色不可挪作他用**：`danger` 只用于破坏性操作，禁止像现在这样把发送按钮染红（`ai_tools_panel.py:636`）。

### 6.2 颜色 Token

| Token | Dark（默认） | Light | Sepia | 用途说明 |
|---|---|---|---|---|
| `bg.base` | `#0F172A` | `#FFFFFF` | `#F4ECD8` | 应用最底层背景 |
| `bg.surface` | `#1E293B` | `#F5F5F5` | `#E8DCC8` | 面板 / Dock / 卡片 |
| `bg.elevated` | `#263449` | `#FFFFFF` | `#F0E7D6` | 浮层（菜单、命令面板、Tooltip、对话框） |
| `bg.canvas` | `#0B1220` | `#FFFFFF` | `#FBF6EC` | 几何画板纸面（见开放问题 5） |
| `bg.inset` | `#0B1220` | `#EEF1F6` | `#DDD0B8` | 输入框、只读日志区凹陷背景 |
| `bg.hover` | `rgba(255,255,255,0.06)` | `rgba(15,23,42,0.05)` | `rgba(92,75,55,0.08)` | 行/项 hover 叠加 |
| `bg.selected` | `rgba(59,130,246,0.16)` | `rgba(0,74,198,0.10)` | `rgba(139,90,43,0.14)` | 选中态背景 |
| `border.subtle` | `#334155` | `#D3E4FE` | `#C9B896` | 分隔线、卡片描边 |
| `border.strong` | `#475569` | `#AFC7EE` | `#A89372` | 输入框默认描边、focus 前状态 |
| `border.focus` | `#3B82F6` | `#004AC6` | `#8B5A2B` | Focus 环（= accent） |
| `fg.primary` | `#F8FAFC` | `#0B1C30` | `#5C4B37` | 正文 / 主标题 |
| `fg.secondary` | `#94A3B8` | `#4A5568` | `#7A6647` | 次级说明、单位、时间戳 |
| `fg.muted` | `#64748B` | `#737686` | `#9A8568` | 占位符、禁用文字（**对比度需 ≥ 4.5:1**） |
| `fg.onAccent` | `#FFFFFF` | `#FFFFFF` | `#FFFFFF` | 强调色容器上的文字 |
| `accent.base` | `#3B82F6` | `#004AC6` | `#8B5A2B` | **唯一强调色**：按钮主色、focus、选中指示 |
| `accent.hover` | `#60A5FA` | `#1663E0` | `#A06B36` | hover 态 |
| `accent.pressed` | `#2563EB` | `#003A9E` | `#6F4722` | pressed 态 |
| `success` | `#22C55E` | `#15803D` | `#567D46` | 成功 Toast / 正向校验 |
| `warning` | `#EAB308` | `#A16207` | `#D4A017` | 警告 |
| `danger` | `#EF4444` | `#B91C1C` | `#B83B1E` | **仅**破坏性操作与错误 |
| `canvas.grid` | `#334155` | `#D3E4FE` | `#C9B896` | 画布网格线（0.5px，DashLine） |
| `canvas.axis` | `#64748B` | `#94A3B8` | `#A89372` | 主轴（1px） |

**几何对象配色**（替代 `canvas.py:830-839` 现有散乱取值，按语义分组且保证三主题下与背景 ΔL 足够）：

| 对象 | Dark | Light | Sepia |
|---|---|---|---|
| `obj.point` | `#60A5FA` | `#004AC6` | `#8B5A2B` |
| `obj.segment` | `#A78BFA` | `#6D28D9` | `#6B4423` |
| `obj.circle` | `#2DD4BF` | `#0F766E` | `#567D46` |
| `obj.polygon` | `#C084FC` | `#7E22CE` | `#9B4DCA` |
| `obj.conic` | `#F472B6` | `#BE185D` | `#A8537A` |
| `obj.function` | `#38BDF8` | `#0369A1` | `#3E7C8C` |
| `obj.implicit` | `#818CF8` | `#4338CA` | `#5C5AA8` |
| `obj.locus` | `#FB923C` | `#C2410C` | `#C0703C` |
| `obj.selection` | `#3B82F6` | `#004AC6` | `#8B5A2B` | （替代写死的 `QColor(0,120,215)`，`:728-799`） |

### 6.3 形状 Token

| Token | 值 | 适用 |
|---|---|---|
| `radius.xs` | `4px` | 标签、徽标、小图标按钮 |
| `radius.sm` | `6px` | 输入框、下拉、普通按钮 |
| `radius.md` | `8px` | Tab 面板内区域、卡片主体 |
| `radius.lg` | `12px` | Dock 面板外框（沿用现有 `styles.qss:19-29`） |
| `radius.xl` | `16px` | 浮层（命令面板已用 10px，建议对齐到 12px） |
| `radius.full` | `9999px` | 圆形徽标 / 状态点 |

> 统一原则：**同一层级容器圆角必须一致**。当前 `styles.qss` Dock 用 12px、Tab pane 用 8px、按钮 6px，而命令面板用 10px（`:53`）/ 空提示区用不同值——需全部对齐到上表。

### 6.4 间距 Token（4px 基准网格）

| Token | 值 | 适用 |
|---|---|---|
| `space.1` | `4px` | 图标与文字间隙 |
| `space.2` | `8px` | 紧凑行间距、按钮内边距纵向 |
| `space.3` | `12px` | 表单项纵向间距、Dock 标题 padding |
| `space.4` | `16px` | 卡片内边距、面板内边距 |
| `space.6` | `24px` | 分区之间 |
| `space.8` | `32px` | 页面级留白（偏好对话框已用 32px，`:459-461`，保留） |

**控件最小高度**（当前偏好对话框用 `min-height: 32px`：`:321` 等，建议统一）：

| 控件 | 高度 |
|---|---|
| 输入框 / 下拉 / SpinBox | `32px`（紧凑） / `36px`（默认） |
| 普通按钮 | `32px` |
| 主操作按钮 | `40px` |
| 工具栏按钮 | `28px`（现有 `lang_btn` 已用 28，`:283`） |

> 教学投影场景（S1）建议提供**"演示模式"**上调一档至 40/48px，作为 P2 增强。

### 6.5 字号 Token

| Token | 值 | 适用 |
|---|---|---|
| `font.family.ui` | `"Microsoft YaHei UI", "Segoe UI", "PingFang SC", "Noto Sans CJK SC", sans-serif` | 主字体（**现有 `main.py:185-189` 缺 Mac 的 PingFang SC 回退，需补**） |
| `font.family.mono` | `"Cascadia Mono", "Consolas", "JetBrains Mono", "Menlo", monospace` | 控制台/代码（**现有 `console.py:58,62` 裸写 `Consolas` 无回退，需替换**） |
| `font.size.xs` | `11px` | 徽标、单位、辅助说明 |
| `font.size.sm` | `12px` | 次级信息、Dock 标题元数据 |
| `font.size.base` | `13px` | 正文、表单标签 |
| `font.size.md` | `14px` | 面板标题（现有 `styles.qss:22` 用 14px，保留） |
| `font.size.lg` | `16px` | Tab 标题强化 / 对话框标题 |
| `font.size.xl` | `20px` | 空状态主标题、加载提示 |
| `font.weight.regular` | `400` | 正文 |
| `font.weight.medium` | `500` | 表单标签、按钮 |
| `font.weight.semibold` | `600` | 面板标题、选中 Tab（现有 `:15,:82` 已用 600） |

> **禁止**用 `.upper()` + `letter-spacing` 充当层级手段（见 UI-10）；层级靠字重 + 颜色 token 表达。

### 6.6 阴影 Token

| Token | 值（offset-x offset-y blur color） | 适用 |
|---|---|---|
| `shadow.sm` | `0 1px 2px rgba(0,0,0,0.28)` | 输入框内凹边界、小卡片 |
| `shadow.md` | `0 4px 12px rgba(0,0,0,0.32)` | 下拉弹出、Tooltip |
| `shadow.lg` | `0 8px 32px rgba(0,0,0,0.45)` | 浮层（命令面板已用 blur 32 / offset 8 — `command_bar.py:124-126`，建议对齐到此值并令牌化） |

> 浅色/棕褐主题下 alpha 调整为 `0.10 / 0.14 / 0.20`，避免灰脏。

### 6.7 动效 Token

| Token | 值 | 缓动 | 适用 |
|---|---|---|---|
| `motion.fast` | `120ms` | `OutCubic` | 颜色 / hover / focus 过渡 |
| `motion.base` | `200ms` | `OutCubic` | 面板展开收起、Toast 滑入 |
| `motion.slow` | `300ms` | `OutBack`（保留现有 Q 弹手感 — `floating_bubble.py:77`） | 气泡弹出、卡片进入 |
| `motion.emphasis` | `600ms` | `InOutQuad`（保留 AI 光标现有手感 — `ai_cursor.py:33`） | AI 光标移动等叙事性动画 |
| `motion.disabled` | 尊重 `prefers-reduced-motion` / 系统"减弱动画"设置 | — | 全局可关闭（需接入 `ConfigManager`） |

> **统一 ripple-less 原则**：Qt QSS 不支持水波纹，统一用 `背景色过渡 + pressed 下沉 1px` 表达按压反馈（现有 `:60-64` 的 pressed 变绿是错误语义，应改为 `accent.pressed`）。

### 6.8 实施建议

建议以 Python 常量字典形式落地于 `mathlab/ui/theme_tokens.py`，并由 `theme_manager` 渲染为 QSS 文本：

```
THEME_TOKENS: dict[str, dict[str, str]] = {
    "dark":  {"bg.base": "#0F172A", ...},
    "light": {...},
    "sepia": {...},
}
```

三份消费者共用：①渲染成 `styles.qss` 文本；②`canvas.py` 画笔直接 `QColor(tokens["canvas.grid"])`；③后续所有面板常量引用。**禁止**再新增任何内联 HEX（纳入 CI 卡口 A-03）。

---

## 7. 本次范围与不做的事

### 7.1 做（In Scope）

- `mathlab/ui/` 与 `mathlab/utils/theme_manager.py` 的**样式层重构**（fold-in 到 token）
- `styles.qss` 扩展为分层、完整、令牌驱动的样式体系
- MainWindow 的**窗口状态持久化**、默认布局、Tab 序调整
- 几何画布 `canvas.py` 的**配色令牌化**（不触碰几何算法与对象模型）
- i18n 资源补齐与重绘链路修正
- 新增 `ToastService` / `LoadingState` / `ShortcutRegistry` / `theme_tokens.py` 四个轻量基础设施
- 启动路径的**延迟化改动**（不动引擎内部实现）

### 7.2 不做（Out of Scope）

| 不做的事 | 原因 |
|---|---|
| **不迁移 UI 框架**（不换 PyQt、不引入 QML/Qt Quick、不大规模重写） | 增量收益最高；PySide6 + QSS 足以解决全部问题，重写风险远大于收益 |
| **不改动 `mathlab/core/` 的业务逻辑**（几何引擎、CAS、沙箱、AI agent、Notebook 内核） | 本次是 UI/UX 专项；除 R-10（撤销栈）需与 `CommandManager` 协同外，核心算法零改动 |
| **不动 IPC / Jupyter 集成的通信协议与渲染机制** | WebEngine 嵌入按现状保留，仅处理快捷键上下文冲突 |
| **不做"跟随系统主题"自动切换**（`preferences.scheme_system` 即使补齐文案也暂不实现） | 需要跨平台 OS 监听 + 切换时重刷全链路，代价较大；列入 P2 待议（见开放问题 3） |
| **不引入第三方 QSS 组件库**（如 `qt-material` / `pyqt-material` / Fluent Python） | 与 Qt6 QSS 存在兼容与体积风险，且会引入第二套 token 源，与"单一真源"目标冲突（除非用户明确要求，见开放问题 3） |
| **不做完整 Design System 文档站 / Storybook** | 以本 PRD 第 6 节 + `theme_tokens.py` 作为 SSOT 即可，够用且易维护 |
| **不做 UI 自动化测试全量覆盖** | 本次只做 CI 静态卡口（样式散落计数、i18n 覆盖、未连接 Action）+ 主题矩阵人工截图评审；e2e UI 测试列为后续议题 |
| **不重新设计产品功能与信息架构的深层结构**（不新增/移除功能模块） | 本次只调整**可见性默认与入口组织**，功能清单不变 |

---

## 8. 待确认问题

> 以下需项目作者拍板，答案会影响工作量与交付节奏。

| # | 问题 | 备选 | 影响 | 我的建议 |
|---|---|---|---|---|
| **Q1** | **强调色取蓝还是绿？** 当前代码里绿 `#22C55E`（styles.qss 用作选中/hover/pressed）与蓝 `#3B82F6`/`#004AC6`（theme_manager）并行 | A. 统一**蓝系**（`#3B82F6` dark / `#004AC6` light）<br>B. 统一**绿系**<br>C. 保持现状双色 | 影响 R-01/R-05/R-07 全部色值与全部截图评审基准 | **建议 A（蓝系）**：贴合数学/教育工具专业感，且与现有 light 主题值 `#004AC6` 连续，改动面最小；绿降级为 `success` 语义色更符合用户直觉 |
| **Q2** | **深色主题下画板保持深色还是给"白纸"选项？** | A. 画布跟随主题（深色=深画布）<br>B. 画布恒白（打印友好）<br>C. 跟随主题，但偏好里提供"画布独立配色"开关 | 影响 R-04 工作量与教师投影体验 | **建议 C**：默认跟随主题保证一致性，同时暴露开关给习惯白板、需要导出后打印/制图的教师。偏好中已有 `canvas_bg` 设置项（`:373`），可自然扩展 |
| **Q3** | **是否引入第三方 QSS 组件库？**（如 qt-material / Fluent Design 实现） | A. 不引入，自建 token（本 PRD 方案）<br>B. 引入并作为 token 源之一 | 决定是否需要第三方依赖与许可证审查 | **建议 A**：本项目已有 3 套样式打架的教训，再引入一个外部样式源会让"单一真源"目标更难达成；且第三方库普遍只覆盖基础控件，画布/Notebook 这类自定义组件仍需自建 |
| **Q4** | **是否保留 Sepia（棕褐色）主题？** | A. 保留（本 PRD 已给三套 token）<br>B. 去除，仅保留 Dark + Light | 影响维护成本与 QSS 体量 | **建议保留**：成本主要是新增一组 token 字典 + 一份渲染产物，边际成本很低；且长时间阅读/备课场景护眼诉求真实存在（Sepia 已有 `THEMES["sepia"]` 定义，`:67-84`） |
| **Q5** | **是否保留 Light（浅色）主题？** | A. 保留<br>B. 本期暂不做，仅保 Dark + Sepia | 影响 R-05 工作量约 1/3，以及 i18n/截图矩阵规模 | **建议保留**：教室投影环境普遍**亮底下用深色、暗底下用浅色**，两者需求真实并存；且当前 `settings.json` 记录 `"theme": "light"`，说明实际运行中已有用户处于浅色 |
| **Q6** | **Undo/Redo 本次是否必须实现？**（R-10 是唯一"大"工作量的 P0） | A. 本次实现真撤销栈<br>B. 本次移除假的菜单项与快捷键，下版再实现<br>C. 保留假菜单项（不推荐） | P0 工作量的主要变量；涉及 `core/command_manager.py` 与图形操作命令化改造 | **建议 A，但若工期紧张可接受 B**：给用户错误承诺比不给功能更伤体验；B 至少消除"点了没反应"的挫败，且工作量降到"小" |
| **Q7** | **验收基线：是否要求 macOS / Linux 同时达标？** | A. 仅 Windows<br>B. Windows + macOS<br>C. 三平台 | 影响字体回退（`.AppleSystemUIFont` / PingFang）、快捷键 Cmd 映射（R-18）、打包验证工作量 | **建议 B**：`main.py:185-189` 已写 Mac 分支但字体回退缺 PingFang，值得顺手修齐；Linux 用户占比低可延后。同时建议把 `Ctrl→Cmd` 归一 helper 做进去，成本很低 |
| **Q8** | **是否接受"引入 LLDB 式启动日志埋点"（`main_window` 分段耗时 `logger.info`）？** | A. 接受，常驻<br>B. 仅在 Debug 构建开启 | 影响 A-04 目标能否持续观测 | **建议 B**：生产环境保持安静，Debug/verbose 下输出，避免污染用户日志（项目已有 `logger` 分级体系） |

---

## 附录 A：证据索引（供工程师快速定位）

| 证据类别 | 位置 |
|---|---|
| app 级 QSS 注入 ① | `mathlab/main.py:202-204` |
| app 级 QSS 注入 ②（覆盖 ①） | `mathlab/utils/theme_manager.py:126-192` |
| 窗口级 QSS 注入 ③（优先级最高） | `mathlab/ui/_mixin_ui_setup.py:199` |
| 调用顺序（决定谁赢） | `mathlab/ui/main_window.py:103` → `:117` |
| 死代码 replace（11 处，仅 1 处命中且语义错误） | `mathlab/ui/_mixin_ui_setup.py:187-197` vs `styles.qss:62` |
| 全局污染选择器 | `mathlab/ui/styles.qss:6-9` |
| QSS 覆盖控件类清单（仅 13） | `mathlab/ui/styles.qss`（全文 108 行） |
| 画布白底 / 无主题感知 / 缓存画笔 | `mathlab/ui/canvas.py:292` / 全文件 `grep theme` 无命中 / `:58-67` |
| 偏好对话 hardcode 白色（17 处） | `mathlab/ui/preferences_dialog.py:321,354,360,374,385,416,426,452` … |
| 假撤销/重做 | `mathlab/ui/_mixin_menus.py:65-67`（键） + `:175-188`（桩） |
| 死菜单项 | `mathlab/ui/_mixin_menus.py:151,153`（无 connect） |
| 双主题入口 | `mathlab/ui/_mixin_menus.py:205` vs `:207`；`_mixin_dialogs.py:36-39` |
| 快捷键三绑定 | `_mixin_ui_setup.py:164`（Ctrl+Shift+P）、`:168`（Ctrl+P）、`main_window.py:132`（Ctrl+K） |
| 窗口状态零持久化 | `mathlab/ui/main_window.py:71`；全仓库 `grep QSettings` 无命中 |
| i18n 缺失 21 key + 静默回退返回 key | `mathlab/utils/i18n_manager.py:154-162`；缺失明细见 §3.1 UI-20 |
| i18n 重绘覆盖不全 | `mathlab/ui/_mixin_dialogs.py:146-148` vs `_mixin_ui_setup.py:62,82` |
| Dock 标题大写 | `_mixin_ui_setup.py:123,127,131,145,150,155,282`；`_mixin_dialogs.py:207-214` |
| 面板默认隐藏 | `_mixin_ui_setup.py:146,151,156` |
| 首个 Tab 是 Notebook | `_mixin_ui_setup.py:59`（Notebook） vs `:60`（画布） |
| 工具栏零 tooltip | `_mixin_menus.py:226-227`（IconOnly） + `grep setToolTip` 仅 `:281,:304` |
| 工具栏按钮硬编码浅色 | `_mixin_menus.py:284-299`（lang） / `:306-315`（settings） |
| 无 Toast；唯一加载组件 | `mathlab/ui/jupyter_panel.py:56`（`_LoadingCard`） |
| 启动同步阻塞点 | `main_window.py:77, 89-91, 120-121, 129, 138, 168` |
| 关闭抗锯齿 | `mathlab/ui/canvas.py:289` |
| 发送按钮语义错误（红） | `mathlab/ui/ai_tools_panel.py:636` |
| 样式散落统计脚本结果 | 内联 `setStyleSheet` **173** 处；硬编码 HEX **411** 处（分布于 20 个文件） |

---

## 附录 B：术语

| 术语 | 说明 |
|---|---|
| **Token（设计令牌）** | 颜色/尺寸/动效的具名变量，作为样式的单一真源 |
| **IA（信息架构）** | 界面元素的组织、层级与可达路径 |
| **加载三态** | loading（进行中）/ empty（无数据）/ error（失败）三种必交付观状态 |
| **WindowShortcut** | `QShortcut` 默认上下文，焦点在窗口任意子控件时均会触发；是 WebEngine 快捷键冲突根因 |
