# MathLab (Axiom Mathematics Panel) — AI 编码智能体协作指南

> 面向所有在本仓库工作的 AI 编码智能体（Codex / Claude / Cursor / Copilot / WorkBuddy …）。
> **动手前先读完本文件。** 本文件与 CI 配置冲突时，以 `.github/workflows/` 与根目录配置文件为准。

| 项目 | 值 |
| :--- | :--- |
| 名称 | MathLab / Axiom Mathematics Panel |
| 版本 | `3.8.0`（`mathlab/utils/version.py`） |
| 类型 | PySide6 (Qt for Python) 跨平台桌面应用 |
| Python | 3.10 – 3.12（CI 矩阵）；`mypy.ini` 固定 `python_version = 3.11` |
| 许可证 | CASAL v1.0（`LICENSE` 正文标题即 v1.0，2026-07-21；源可用，禁止 AI/ML 训练；见 §8） |
| 规模 | `mathlab/` 166 个 `.py` / 约 4.05 万行（不含 `resources/`）；其中 `ui/` 42 个模块 / 1.37 万行、`core/` 57 个 / 1.41 万行 |
| 测试 | 616 条用例（29 个 `test_*.py`）；日常快速回归跑 606 条（排除 `slow` / `e2e`） |

一句话定位：**在同一窗口内融合几何 DAG 引擎、符号/数值计算、内嵌 JupyterLab、AI 多智能体与插件生态的交互式数学工作台。**

---

## 1. 技术栈

| 类别 | 技术 | 版本（根 `requirements.txt`） | 用途 |
| :--- | :--- | :--- | :--- |
| GUI | PySide6 | `>=6.6.0`（`mathlab/requirements.txt` 为 `>=6.5.0`） | Qt for Python，含 WebEngine Addons |
| 符号计算 | SymPy | `>=1.12` | CAS 引擎（`core/cas_provider.py`） |
| 数值计算 | NumPy / SciPy | `>=1.26` / `>=1.11` | 数组、线性代数、优化 |
| 图论 | networkx | `>=3.1` | 几何 DAG、算法动画 |
| 代码补全 | jedi | `>=0.19` | 编辑器智能提示 |
| 进程监控 | psutil | `>=5.9` | 沙箱资源限制 |
| ML | scikit-learn | — | AI 拟合 / 聚类 |
| 绘图 | matplotlib / pyqtgraph | `>=3.8` / `>=0.13` | 图表与实时曲线 |
| LLM | openai | `>=1.0` | 多提供商（OpenAI 协议兼容）接入 |
| 配置/渲染 | PyYAML / markdown / Pygments | — | 提示词模板、Markdown、语法高亮 |
| Jupyter | jupyterlab / jupyter_client / ipykernel / jupyter_server | `>=4.0` 等 | 内嵌 JupyterLab 与内核沙箱 |
| .NET 桥接 | pythonnet | `>=3.0` | C# 加速内核（缺失自动降级） |
| 测试 | pytest / pytest-qt / pytest-cov | `>=7.4` / `>=4.4` / `>=4.1` | 分层测试 |

> `networkx` / `psutil` 为运行必需，三份清单（根 `requirements.txt`、`mathlab/requirements.txt`、`setup.py`）
> 必须保持同步；根清单此前缺这两项（§10 T-1，已修复）。

---

## 2. 目录结构（二级，标注职责）

```
Axiom Mathematics Panel/
├── mathlab/                        # 主包
│   ├── main.py                     # 入口：日志→异常钩子→QApplication→MainWindow
│   ├── ui/           (42)          # 界面层：窗口、面板、画布、样式
│   ├── core/         (57)          # 核心层：几何 DAG / CAS / AI / 沙箱 / 插件 / Jupyter
│   ├── utils/        (10)          # 工具层：logger / config / i18n / theme / theme_tokens / latex / markdown / version
│   ├── data/         (3)           # 数据层：project.py、file_manager.py
│   ├── plugins/      (5 内置)      # 每个插件 = 一个含 main.py 的目录
│   ├── config/                     # prompts.yaml（生效）；ai_providers.json、ai_tools_schema.py 当前无代码读取
│   ├── locale/                     # zh.json / en.json（i18n 唯一数据源）
│   ├── resources/                  # HTML / 图标 / monaco / web_src（前端产物）
│   ├── docs/         (10 篇)       # api.md、user_guide.md、function_explorer_guide.md …
│   ├── tests/                      # unit(24) / integration(2) / e2e(1) + 顶层 2
│   ├── scripts/                    # check_i18n.py / check_ui_style.py（CI 守卫）/ update_i18n.py
│   ├── settings.json               # 运行时配置（含 ai_api_key 字段，见 §8）
│   ├── build_spec.spec             # PyInstaller 完整版（含 JupyterLab 资源）
│   └── requirements.txt            # 打包用依赖清单
├── MathLab.CSharpEngine/           # .NET Standard 2.0 加速内核（可选）
├── installer/                      # Inno Setup Windows 安装包脚本（§3.6）
├── mathlab.spec                    # PyInstaller 主 spec（根目录，CI 使用）
├── requirements.txt                # 根依赖清单（**CI 使用**）
├── pyproject.toml                  # 仅含 pytest + coverage 配置
├── .flake8 / .pylintrc / .bandit / mypy.ini
├── .github/workflows/              # test.yml / code-quality.yml / release.yml / _build-setup.yml
└── AGENTS.md                       # 本文件
```

`ui/` 关键文件：`main_window.py`（组合 7 个 Mixin）、`_mixin_*.py`（7 个）、`canvas.py`（几何画布）、
`styles.qss`（主题样式表）、`console.py` / `math_console.py`、`notebook_panel.py` / `code_editor.py`。

---

## 3. 构建与运行命令

### 3.1 环境准备

```bash
python -m venv venv
# Windows: venv\Scripts\activate   macOS/Linux: source venv/bin/activate
pip install -r requirements.txt              # 与 CI 一致
pip install -e "./mathlab[full]"             # 可选：AI / neural / visualization extras
pip install pytest pytest-qt pytest-cov      # 测试（根 requirements 已含）
pip install black isort flake8 mypy pylint bandit   # 质量工具（CI 单独安装）
dotnet build MathLab.CSharpEngine/MathLab.CSharpEngine.csproj -c Release   # 可选：C# 内核
```

### 3.2 启动

```bash
python mathlab/main.py          # 开发模式标准入口
```

> ⚠️ `main.py` 只把 `mathlab/` 目录插入 `sys.path`，仓库根不在其中。
> 若报 `ModuleNotFoundError: No module named 'mathlab'`，先设置 `PYTHONPATH=.`
> （Windows PowerShell：`$env:PYTHONPATH="."`）或 `pip install -e ./mathlab`。
> `python -m mathlab` **不可用**——仓库中没有 `mathlab/__main__.py`。

### 3.3 测试

`pyproject.toml` 的 `addopts` 已固定 `-v --tb=short --strict-markers --junitxml --cov=mathlab --cov-branch …`，
命令行只需追加选择器：

```bash
pytest                                                  # 全量（testpaths=mathlab/tests）
pytest -m "not slow and not e2e"                        # 日常快速回归
pytest mathlab/tests/unit -m "not slow"                 # 单目录（CI 用法）
pytest mathlab/tests/integration -m "not slow"
pytest mathlab/tests/e2e                                # e2e（需 Qt 事件循环）
pytest mathlab/tests/unit/test_dag.py -k "test_add"     # 单文件 / 单用例
pytest --no-cov -q                                      # 关闭覆盖率加速
```

Linux 无显示环境：`xvfb-run --auto-servernum pytest …`（`conftest.py` 已设 `QT_QPA_PLATFORM=offscreen`）。

### 3.4 质量门（**与 CI 逐字一致**，见 `.github/workflows/code-quality.yml`）

```bash
black mathlab/ --check --line-length=120 --extend-exclude='mathlab/resources|mathlab/logs' --diff
isort mathlab/ --check-only --profile black --skip-glob='mathlab/resources/*' --skip-glob='mathlab/logs/*' --diff
flake8 mathlab/ --max-line-length=120 --extend-ignore=E203,W503,E501 \
       --exclude=mathlab/resources/,mathlab/logs/ --count --statistics --show-source
mypy mathlab/ --config-file mypy.ini
pylint mathlab/ --rcfile=.pylintrc --disable=R,C --fail-under=5.0 --output-format=parseable
bandit -r mathlab/ -x mathlab/resources,mathlab/logs -f json -o bandit-report.json -ll -c .bandit
```

自动修复（提交前）：

```bash
black mathlab/ --line-length=120 --extend-exclude='mathlab/resources|mathlab/logs'
isort mathlab/ --profile black --skip-glob='mathlab/resources/*' --skip-glob='mathlab/logs/*'
```

> **说明**：`black` / `isort` 的配置**已**写入 `pyproject.toml`（`[tool.black]` line-length=120、
> `[tool.isort]` profile=black），取值与上面 CI 的 CLI 参数逐字一致，因此裸跑 `black mathlab/` 也合规。
> 改动任一处必须两侧同步，否则本地与 CI 判定会分叉。
> 注意 `[tool.isort]` 刻意不设 `line_length`（CI 未传该参数，isort 仍按 profile 取 88），
> 不要"顺手"把它对齐成 120 —— 那会与 CI 产生配置优先级分歧。
> `.bandit` 已跳过 `B102 / B307 / B602 / B603`；新增 `# nosec` 需在注释中说明理由。

### 3.5 打包（PyInstaller，两份 spec 均为 ONEDIR）

```bash
pyinstaller mathlab.spec              # 根目录 spec（CI release.yml 使用）
pyinstaller mathlab.spec --clean      # 缓存未命中时
pyinstaller mathlab/build_spec.spec   # 完整版：额外收集 jupyterlab/notebook/ipykernel 数据
```

打包资源路径解析统一走 `mathlab/main.py::_find_resource()`（兼容 PyInstaller 5.x/6.x ONEDIR 与 ONEFILE），
**不要**在新代码里手写 `sys._MEIPASS` 拼接。

### 3.6 Windows 安装包（Inno Setup）

```bash
pyinstaller mathlab.spec                          # 先生成 dist/MathLab/
iscc /DAPP_VERSION=3.8.0 installer/MathLab.iss    # 产出 dist/MathLab-3.8.0-Windows-Setup.exe
```

- 版本号唯一真源是 `mathlab/utils/version.py`（CI 自动提取并传入 `APP_VERSION`；未传时占位 0.0.0，仅供语法验证）。
- 安装界面为中英双语：多语言自动出现「选择安装语言」页，随后是 CASAL 许可协议页；中文文案来自随仓库分发的 `installer/languages/ChineseSimplified.isl`（取自 jrsoftware/issrc，允许随脚本分发）。
- `installer/LICENSE.txt` 由根 `LICENSE`（Markdown）转出的纯文本，许可证变更时必须重新生成并逐条核对一致。
- 卸载时自动清理运行时产物（`logs/`、`crash.log`、`webcache/`、`autosave/`），新增运行时写盘目录需同步 `[UninstallDelete]`。

---

## 4. 架构约定（CRITICAL）

### 4.1 分层依赖方向

```
ui  ──▶  core  ──▶  utils
 │        │  ▲        ▲
 └────────┴──┴────────┘
data ──▶ utils        plugins ──▶ core.extension_api.MathLabAPI（不得直接 import ui）
```

| 层 | 允许导入 | **禁止** |
| :--- | :--- | :--- |
| `mathlab/ui/*` | `core`、`utils`、`data`、`resources` | 被 `core`/`utils` 反向导入 |
| `mathlab/core/*` | `utils`（局部 import 规避循环） | 导入 `mathlab.ui.*` |
| `mathlab/utils/*` | 标准库 + 第三方 | 导入 `core` / `ui`（`config_manager`、`i18n_manager` 用函数内延迟 import） |
| `mathlab/data/*` | `utils` | 导入 `ui` |
| `mathlab/plugins/*` | `core.extension_api`、`core.plugin_base`、`utils` | 直接访问 `MainWindow` 私有属性 |

新增跨层调用前先用 `grep` 确认方向，逆向依赖会在 `import-check` CI Job 与架构测试中暴露。

### 4.2 MainWindow Mixin 组合模式

```python
class MainWindow(UISetupMixin, MenusMixin, SignalsMixin, CommandsMixin,
                 AIMixin, FileIOMixin, DialogsMixin, QMainWindow):
```

| Mixin | 文件 | 职责 |
| :--- | :--- | :--- |
| `UISetupMixin` | `_mixin_ui_setup.py` | 中央 Tab、Dock 创建、面板显隐、样式加载 |
| `MenusMixin` | `_mixin_menus.py` | 菜单栏 / 工具栏 |
| `SignalsMixin` | `_mixin_signals.py` | 信号接线、几何事件响应 |
| `CommandsMixin` | `_mixin_commands.py` | 命令注册、命令面板 |
| `AIMixin` | `_mixin_ai.py` | AI 集成、异步 Worker |
| `FileIOMixin` | `_mixin_file_io.py` | 项目读写、导入导出 |
| `DialogsMixin` | `_mixin_dialogs.py` | 主题 / 语言 / 偏好设置 / About |

规则：

1. `QMainWindow` 必须排在 MRO 最后。
2. Mixin **不得定义 `__init__`**（由 `MainWindow.__init__` 统一初始化，避免 MRO 冲突）。
3. Mixin 只能读写 `self` 上已存在的属性；需要新状态时在 `MainWindow.__init__` 中声明并注释。
4. 新增方法名不得与其他 Mixin 冲突（Python 不做重载，后者静默覆盖前者）。
5. 新增 Mixin：文件命名 `_mixin_<域>.py`，类名 `<域>Mixin`，并在 `main_window.py` 的导入块与类基类中同步登记。

### 4.3 引擎唯一实例化点

所有核心引擎**只能**在 `MainWindow._init_engines()` 中创建：

```python
def _init_engines(self):
    self.geometry_engine = GeometryEngine()
    self.cas_provider    = CASProvider()
    self.geometry_engine.set_cas_provider(self.cas_provider)
    self.python_repl     = PythonREPL()
    self.ai_manager      = AIManager()
    self.algo_animator   = AlgoAnimator()
    self.project_manager = ProjectManager()
    self.sandbox_manager = SandboxManager()
```

禁止在面板 / Mixin / 插件中 `GeometryEngine()`、`CASProvider()` 二次实例化（历史上出现过“双重初始化”反模式）。
需要引用时通过 `self.<engine>` 或 `MathLabAPI`。

### 4.4 信号

* 跨模块事件信号集中在 **`mathlab/core/signals.py`**：`GeometrySignals`、`ConsoleSignals`、`AlgorithmSignals`、`AISignals`（均继承 `QObject`）。
* 面板内部私有信号可在自己的 `QObject` 子类中定义，但必须注释说明为何不进 `signals.py`。
* 接线统一在 `SignalsMixin.connect_signals()`，禁止在 `__init__` 里散落 `connect`。

### 4.5 插件系统

| 约定 | 内容 |
| :--- | :--- |
| 位置 | `mathlab/plugins/<plugin_id>/main.py`（`PluginManager` 只扫描该路径） |
| 基类 | `mathlab.core.plugin_base.MathLabPlugin`（ABC） |
| 类属性 | `name` / `version` / `author` / `description` |
| 构造 | **必须无参构造**——`PluginManager` 执行 `obj()` |
| 生命周期 | `on_activate(api: MathLabAPI)` → `on_deactivate()` |
| 清理 | `MathLabAPI` **没有** `unregister_command` 公开方法；命令与动态面板的注销由 `api.cleanup()` 完成，`PluginManager.unload_all()` 会依次调用 `on_deactivate()` 与 `cleanup()` |
| API 面 | `register_command` / `add_sidebar_panel` / `print_to_console` / `execute_script` / `cleanup` |

每个插件获得**独立**的 `MathLabAPI` 实例以隔离注册项；插件禁止直接 `import mathlab.ui.main_window`。

### 4.6 配置与设置

* `mathlab/utils/config_manager.py`：`get_config(key, default)` / `save_config(dict)` / `load_config(force_reload)`，数据文件 `mathlab/settings.json`（线程安全 + 缓存 + 深度合并默认值）。
* `mathlab/utils/theme_manager.py`：`load_settings()` / `save_settings()` 直接读写**同一个** `settings.json`。
* 新增配置项必须同时在 `config_manager._DEFAULT_CONFIG` 中给出默认值。

---

## 5. UI 开发专项约定（重点）

### 5.1 主题系统唯一真源（Single Source of Truth）

**权威来源是 `mathlab/utils/theme_tokens.py::THEME_TOKENS`**（`light` / `dark` / `sepia`，每主题 **31 个 token**，
由 `validate_theme_tokens()` 保证三套键集一致）。
`theme_manager.py::THEMES` 已降级为**派生的兼容视图**（`_derive_legacy_view()`，旧的 16 键形状），
只为不破坏既有调用而保留 —— 新代码不要再从 `THEMES` 取色。

链路现状（已收敛，非"重构方向"）：

* app 级 `setStyleSheet` 全仓**只有 1 处**：`theme_manager.py:193`；`main.py` 与 `_mixin_ui_setup.load_stylesheet()`
  的注入已删除，`load_stylesheet()` 本身连同 `qss.replace("#13131A", …)` 那套失效逻辑一起消失了。
* `styles.qss` 是**模板**（735 行、**0 个硬编码 HEX**、185 个 `${token}` 占位符），由 `render_qss()` 渲染一次后注入。
* `set_theme()` 的顺序：accent 覆写 → `QPalette` → 渲染 → 注入 → 持久化 → 发信号。

规则：

1. **应用级 `setStyleSheet` 只允许出现一次**，即 `theme_manager.set_theme()` 内。
2. 取色一律用 `get_theme_colors()` / `get_tokens()` / `get_current_theme()`；新增色值必须先加进
   `THEME_TOKENS` 的**三个主题**，再在 QSS 里引用，不允许只加单主题。
3. UI 代码中写 `#RRGGBB` 仍属违规，但**现状未清零**：Python 侧实测 103 处 `setStyleSheet(` / 263 处硬编码色值。
   这条由 `mathlab/scripts/check_ui_style.py` 以**棘轮阈值**（阈值 == 实测值，只许降不许升）拦新增，
   收敛时把 `THRESHOLDS` 的数字改小即可，不要放宽容差。
4. 控件级微调允许 `widget.setStyleSheet(...)`，但**必须**带 `#objectName` 或具体类选择器前缀，
   且不得覆盖主题色之外的布局属性。

### 5.2 QSS 编写规范

* **禁止裸 `QWidget { … }` 全局规则**（会级联污染所有子控件，含 WebEngine 容器）。
  当前 `styles.qss` 顶层是具名的 `QMainWindow, QDialog`，没有裸 `QWidget` —— 改回去就是引入回归。
* **禁止** `QDockWidget > QWidget` 这类会命中 dock 内部任意子控件的选择器。
* 选择器必须覆盖完整控件集，至少包含：
  `QMenuBar` `QMenu` `QMenu::item` `QToolBar` `QStatusBar` `QDockWidget` `QDockWidget::title`
  `QTabWidget::pane` `QTabBar::tab` `QTreeWidget` `QListWidget` `QTableWidget` `QSplitter` `QSplitter::handle`
  `QGroupBox` `QCheckBox` `QRadioButton` `QToolTip` `QProgressBar` `QScrollBar`（含 `::handle` / `::add-line` / `::sub-line`）
  `QPushButton`（`:hover` / `:pressed` / `:disabled`）`QLineEdit` `QPlainTextEdit` `QTextBrowser`
  `QComboBox` `QComboBox QAbstractItemView` `QSpinBox` `QLabel`。
* **三主题必须同时可用**：修改 QSS 后必须在 `light` / `dark` / `sepia` 三套下逐一验证（`set_theme()` 会同时刷新 `QPalette`）。
* 新增色值 → 先加到 `THEME_TOKENS`（三主题各一份），再在 QSS 中用 `${token}` 引用；不允许只加单主题。
* `styles.qss` 的加载链路只有 `theme_manager.set_theme()` 一处，**不要**再新增第二处 app 级或窗口级注入（§10 T-2 已闭环，别把它改回来）。

### 5.3 面板 / Dock 规范

| 项 | 约定 | 现状与例外 |
| :--- | :--- | :--- |
| 标题 | 必须 `t("<namespace>.title")`；**禁止** `.upper()` 强制大写（中文无大小写语义，且破坏英文可读性） | Dock 标题已清理；面板内部区块标题仍有 `.upper()`（如 `algebra_panel.py:267,343`），属既有视觉风格，新增时不要再加 |
| objectName | 每个 `QDockWidget` 必须 `setObjectName(...)`——几何/状态持久化的主键 | 现存 7 个静态 dock 用的是**驼峰**（`dockAlgebra` / `dockProperties` / `dockConsole` / `dockMathConsole` / `dockFunctionExplorer` / `dockAlgoVis` / `dockAITools`），而动态面板是 `dock_dynamic_<name>`（`_mixin_ui_setup.py:263`）。两套并存；`session_state` 已按现名持久化，**改名会导致用户已存的布局失效**，如需统一要连带做键迁移 |
| 显隐持久化 | 用 `QSettings("MathLab", "MainWindow")` 保存 `geometry()`、`saveState()` 与各 dock `visible`；在 `closeEvent` 写入、`__init__` 末尾恢复 | ✅ 已实现于 `ui/session_state.py`（含 `SCHEMA_VERSION` 防脏数据）；`main_window.py` 已无硬编码 `setGeometry` |
| 默认可见性 | 核心面板（代数 / 属性 / 控制台）默认可见 | 现状只有**函数探索器** `hide()`（`_mixin_ui_setup.py:152`）；算法可视化与 AI 工具**默认可见且即时构造**。首屏冷启动落在**几何画板**（Tab 序：画板 → Notebook → Mini GeoGebra → Jupyter） |
| 动态面板 | `UISetupMixin.add_dynamic_panel()`（供 `MathLabAPI.add_sidebar_panel` 调用），同样需要本地化标题与 objectName | — |

### 5.4 主线程规则

* 所有 `QWidget` 创建、属性修改、布局变更**必须在主线程**。
* 后台线程回主线程，二选一：

  ```python
  QMetaObject.invokeMethod(widget, "load_workspace", Qt.ConnectionType.QueuedConnection)
  QTimer.singleShot(0, lambda: widget.setText(text))
  ```

* CPU/IO 密集任务用 `QRunnable` + `QThreadPool.globalInstance()`（参考 `mathlab/core/async_workers.py`），
  结果通过信号回传；**不要**在 `threading.Thread` 中触碰任何 Qt 对象。
* `threading.Thread` 仅允许用于 JupyterLab 启动等一次性后台任务，且必须 `daemon=True` 并命名。
* 关闭流程：`MainWindow.closeEvent` 中 `QThreadPool.globalInstance().waitForDone(2000)`，新增长任务需纳入该等待。

### 5.5 延迟初始化

首屏不得被重型初始化阻塞。`MainWindow.__init__` 末尾统一派发：

```python
QTimer.singleShot(0, self._deferred_init)   # AI 集成 / ECharts 绑定 / REPL 命名空间 / 插件加载
```

新增的耗时初始化（>50ms）一律挂到 `_deferred_init()`，并用 `try/except + logger.error(..., exc_info=True)` 包裹，
失败不得阻断主窗口。

---

## 6. 代码风格与质量门

| 项 | 约定 |
| :--- | :--- |
| 行宽 | **120**（black / flake8 / pylint 三处一致） |
| 格式化 | `black` + `isort(profile=black)`，参数见 §3.4 |
| 导入 | 绝对导入（`from mathlab.core.x import Y`）；`mathlab/ui` 内部同层可用相对导入（`from .canvas import …`） |
| 类型注解 | 公共函数签名必须注解；`mypy.ini` 中 `disallow_untyped_defs=false`，但对 `mathlab.ui.*` / `mathlab.utils.*` / `mathlab.plugins.*` 已 `ignore_errors=true`——**不要**借机放弃注解 |
| 日志 | 一律 `from mathlab.utils.logger import get_logger` → `logger = get_logger(__name__)`；**禁止** `print()`（打包 `console=False` 时不可见）、禁止模块级 `logging.basicConfig`。异常用 `logger.error("...: %s", e, exc_info=True)` |
| i18n | 一律 `from mathlab.utils.i18n_manager import t` → `t("namespace.key")`；**禁止硬编码中文/英文文案**。key 为点分路径，未命中时返回 key 本身 |
| i18n 新增 | 新增 UI 面板/菜单必须**同时**在 `mathlab/locale/zh.json` 与 `en.json` 增加同名命名空间（`indent=2`、`ensure_ascii=False`）。当前 `zh.json` 与 `en.json` 各 **402 叶键、完全对称**（旧缺口 T-6 已修） |
| 命名 | 模块/函数 `snake_case`，类 `PascalCase`，常量 `UPPER_CASE`，Qt 私有槽 `_on_xxx` |
| 文档字符串 | 公共类与方法写中文 docstring（Google 风格，`Args/Returns`）；`C0114/15/16` 已在 `.pylintrc` 关闭，不强制 |
| 提交 | Conventional Commits：`feat(ui): …` / `fix(core): …` / `docs:` / `style:` / `refactor:` / `test:` / `chore:` |

---

## 7. 测试约定

| 层 | 目录 | 标记 | 说明 |
| :--- | :--- | :--- | :--- |
| 单元 | `mathlab/tests/unit/` | `unit` | 快速、无外部依赖 |
| 集成 | `mathlab/tests/integration/` | `integration` | 多组件协作 |
| 端到端 | `mathlab/tests/e2e/` | `e2e`（隐含 `qt`） | 需 Qt 事件循环 |
| 慢测 | 任意 | `slow` | CI 用 `-m "not slow"` 排除 |
| Qt | 任意 | `qt` | 需要事件循环，用 pytest-qt 的 `qtbot` |

约定：

* `--strict-markers` 已开启，**未注册的标记会直接报错**，只能用上表 5 个。
* 公共 fixture（`engine` / `dag` / `cas` …）定义在 `mathlab/tests/conftest.py`，各层 `conftest.py` 继承。
* **UI 改动必须补测试**：新增/修改面板、Dock、主题、样式时，至少补一个 `@pytest.mark.qt` 用例，
  关键交互链路补 `@pytest.mark.e2e`。
* UI 测试规范：`qtbot.addWidget(w)` 管理生命周期；断言前用 `qtbot.waitUntil(..., timeout=5000)`；
  禁止 `time.sleep`；禁止在测试中构造第二个 `QApplication`。
* 覆盖率源为 `mathlab`，`resources/` 与 `tests/` 已 omit；`# pragma: no cover` 仅用于真正不可测分支。

---

## 8. 安全与合规（CASAL v1.0）

1. **许可证**：CASAL v1.0（见 `LICENSE`，标题为 “Custom Advanced Source-Available License v1.0 (CASAL v1.0)”，
   正文标注发布于 2026-07-21）。文档与徽章此前写作 “v4.0” 属口径不一致，已统一回 `LICENSE` 的 v1.0；
   若确要升级许可证规格，应改 `LICENSE` 本身并重新生成 `installer/LICENSE.txt`，而不是只改文档。
   **明确禁止将本仓库源码用于 AI/ML 训练**。智能体生成的代码必须保留既有版权头，不得删除/替换许可证声明。
   ⚠️ 现状：`ui/` `core/` `data/` `plugins/` `tests/` 的源码文件**都没有**版权头，
   “保留既有版权头”目前无从对应；新增文件若要加声明请整批统一，别只给新文件加。
2. **沙箱**：`mathlab/core/sandbox_security.py::CodeSecurityScanner` 基于 AST 白/黑名单
   （`BANNED_MODULES` / `BANNED_FUNCTIONS` / `BANNED_ATTRIBUTES`）。
   **任何改动都不得放宽该白名单**，不得新增 `eval` / `exec` / `__import__` / `os` / `subprocess` 等豁免。
   放宽前必须走安全评审并同步更新 `mathlab/docs/sandbox_security_refactor.md`。
3. **敏感信息**：`mathlab/settings.json` 含 `ai_api_key` 字段且被 Git 跟踪——**提交前确认其为空字符串**。
   禁止把 API Key、令牌、个人路径写入代码、文档或测试夹具。
   注意：跑测试会把运行期默认键（如 `enable_undo`）写进这个文件，提交前用 `git diff mathlab/settings.json` 检查，别把无关变更一起提交。
4. **bandit**：`-ll` 仅拦截中高危；新增 `# nosec` 必须注释理由。
   `# nosec` 必须写在**被报告的那一行**上（行尾），放上一行不生效。
5. **表达式解析只能走 `mathlab/core/expression_guard.py`**。
   不要对不受信的表达式字符串调用 `sympy.sympify()` / `parse_expr()`：
   sympy 在 `global_dict=None` 时会主动把 `builtins` 注入求值命名空间，
   `"__import__('os').getpid()"` 与 `x.__class__` 都会被真的解析出来（`.mathlab` 工程文件里的
   `expression` 字段就走这条路，构成"打开即 RCE"）。用 `safe_parse_expr` / `safe_sympify`。
   另：`parse_expr` 会**回写**传入的 `global_dict`（塞进 `__builtins__`），
   所以受限命名空间必须每次返回新字典，不能 `lru_cache` 一个可变 dict。
6. **沙箱有父子两道扫描**：父进程 `SandboxProcess.run_code()` 先用
   `sandbox_security.is_code_safe` 拦，子进程 `sandbox_script.py` 内再留一份同规则副本
   （子进程不保证能 `import mathlab`，所以规则是刻意重复的）。
   改任一侧都要同步另一侧，只放宽一边等于没拦。
7. 依赖漏洞检查：`safety check --file=requirements.txt`（CI Job）。

---

## 9. 智能体行为准则

1. **先读后改**：修改任何文件前先完整读取；跨层改动先 `grep` 调用方。禁止凭猜测编辑。
2. **最小变更**：只改完成任务必需的代码；不顺手重构、不调整无关格式、不批量改引号/导入顺序。
3. **每轮结束自检**（必做）：
   a. 导入完整性 —— 新增/改动的模块能被 `import`；
   b. `black --check` + `isort --check-only` + `flake8`（§3.4 参数）；
   c. `pytest -m "not slow and not e2e"` 通过；
   d. 涉及 UI 时补跑 `pytest mathlab/tests/e2e`；
   e. 质量门必须跑 §3.4 的**逐字命令**，别用 `--select=F,E9` 之类窄化子集自我安慰 ——
      W605（docstring 里的反引号转义）就是这样本地全绿、到 CI 才变红的。
4. **不修改构建产物与临时文件**：`dist/` `build/` `*.egg-info` `venv/` `.coverage` `test-results/`
   `mathlab.log` `crash.log` `bandit-report.json` `.mypy_cache/` `.pytest_cache/` `scratch/` `mathlab/autosave/`
   `mathlab/webcache/` `mathlab/logs/` `mathlab/dist/` `mathlab/resources/dist/`。
5. **不改配置基线**：`.flake8` `.pylintrc` `.bandit` `mypy.ini` `pyproject.toml` 的变更需显式说明理由；
   为绕过报错而放宽配置属于违规。
6. **不要重写大文件**：>800 行的文件用 `Edit` 做定点修改，避免整文件 `Write` 造成无关 diff。
7. **不确定就问**：需求、色值、i18n 文案、依赖方向有任何不明确，先向用户/主理人确认，不要臆造。
8. **文档同步**：新增面板/命令/配置项时，同步更新 `mathlab/locale/*.json` 与 `mathlab/docs/` 中对应文档。

---

## 10. 已知技术债（动手前必读，避免踩坑）

| ID | 位置 | 问题 | 处理建议 |
| :--- | :--- | :--- | :--- |
| T-1 | 根 `requirements.txt` | ✅ 已修复：`networkx>=3.1`、`psutil>=5.9` 已补入根清单。此前 CI 按根清单安装，导致 `core/algo_animator.py` 的 networkx 分支在 CI 恒不生效（6 个图算法用例静默 skip）、沙箱内存监控一直走降级 | 新增根依赖时仍需同步 `mathlab/requirements.txt` 与 `setup.py` 三份清单 |
| T-2 | 主题加载链路 | ✅ 已闭环：app 级注入只剩 `theme_manager.py:193` 一处，`load_stylesheet()` 及其 `replace()` 逻辑已删除，`styles.qss` 改为 `${token}` 模板 + `render_qss()` 渲染一次。以下为原始记录：三处互相覆盖：① `main.py` 读 `styles.qss` → `app.setStyleSheet`；② `theme_manager.set_theme()` 内联 QSS → `app.setStyleSheet`（整体覆盖 ①）；③ `_mixin_ui_setup.load_stylesheet()` → `self.setStyleSheet(qss)`（窗口级，优先级最高）。且 ③ 中的 `qss.replace("#13131A", …)` 等旧色值在当前 `styles.qss`（Slate 色板 `#0F172A` / `#1E293B` / `#334155` / `#475569` / `#22C55E`）中**已不存在**，替换静默失效 | 按 §5.1 收敛为“模板 + 一次渲染 + 一次 `app.setStyleSheet`”；删除 `load_stylesheet()` 的 replace 逻辑 |
| T-3 | `mathlab/ui/styles.qss`（现 735 行） | ✅ 已修：无裸 `QWidget` 规则，§5.2 要求的控件集已全覆盖，0 个硬编码 HEX（185 个 `${token}`）。以下为原始记录：① 裸 `QWidget` 全局背景规则污染子控件；② 缺少 `QMenuBar` / `QMenu` / `QToolBar` / `QStatusBar` / `QTreeWidget` / `QListWidget` / `QSplitter` / `QGroupBox` / `QCheckBox` / `QRadioButton` / `QToolTip` / `QProgressBar` 等控件样式 | 按 §5.2 补全并改为具名选择器 |
| T-4 | `main_window.py` | ✅ 已修：`QSettings` 落地于 `ui/session_state.py`（geometry/saveState/dock visible + `SCHEMA_VERSION`），硬编码 `setGeometry` 改为按屏幕可用区居中。以下为原始记录：`self.setGeometry(100, 100, 1200, 800)` 硬编码，全仓库 `QSettings` 使用数为 **0** | 改用 `QSettings` 持久化 `geometry()` + `saveState()`（§5.3） |
| T-5 | `_mixin_ui_setup.setup_docks()` | ⚠️ 部分修复：Tab 序已改为画板优先；dock 标题的 `.upper()` 已清（`math_console.retranslate_ui` 那处漏网刚补掉），但面板内部区块标题仍大写（`algebra_panel.py:267,343` 等）；objectName 采用驼峰而非 `dock_<name>`；算法可视化 / AI 工具改为默认可见（与旧约定相反，详见 §5.3）。以下为原始记录：Dock 标题被 `.upper()` 强制大写；函数探索器 / 算法可视化 / AI 工具默认 `hide()` 且状态未持久化；中央 `QTabWidget` 首标签是 Notebook 而非几何画板 | 按 §5.3 处理 |
| T-6 | `mathlab/locale/en.json` | ✅ 已修：双语各 402 叶键、完全对称。以下为原始记录：比 `zh.json` 少 `math_console.vars`、`math_console.workspace` 两个键 | 新增 key 必须双语同步（§6） |
| T-7 | `mathlab/scripts/update_i18n.py` | 内部硬编码 `j:/PROJECT/...` 绝对路径 | 不要直接运行；改为手动编辑 JSON 或先修复脚本路径 |
| T-8 | `README.md` | ✅ 已修：Mixin 数、`python -m mathlab`、工程文件扩展名（`.mathlab` 而非 `.mlproj`）、许可证版本、以及“WebSocket 协作 / 云端同步 / 资源库 / 10 家模型接入”等未实现项均已按事实改写，README 顶部新增「📌 当前状态」表区分“可用 / 代码就绪未接线 / 不存在” | 文档继续按源码事实校验后再写 |

---

## 11. 关键文件速查表

| 我想… | 去看 |
| :--- | :--- |
| 改主题 / 配色 | `mathlab/utils/theme_tokens.py`（`THEME_TOKENS`，真源）+ `theme_manager.py`（`set_theme`、`get_theme_colors`；`THEMES` 只是派生兼容视图） |
| 改全局样式 | `mathlab/ui/styles.qss` + `theme_manager.set_theme()` |
| 加面板 / Dock | `mathlab/ui/_mixin_ui_setup.py`（`setup_docks`、`add_dynamic_panel`） |
| 加菜单 / 工具栏 | `mathlab/ui/_mixin_menus.py` |
| 接线信号 | `mathlab/ui/_mixin_signals.py`、`mathlab/core/signals.py` |
| 加命令 | `mathlab/ui/_mixin_commands.py`、`mathlab/core/command_manager.py` |
| 加引擎 / 改引擎 | `main_window.py::_init_engines()`、`mathlab/core/` |
| 写插件 | `mathlab/core/plugin_base.py`、`core/extension_api.py`、`plugins/<id>/main.py` |
| 加文案 | `mathlab/locale/zh.json` + `en.json`（双语同步） |
| 加配置项 | `mathlab/utils/config_manager.py::_DEFAULT_CONFIG` |
| 改沙箱 | `mathlab/core/sandbox_security.py`（**不得放宽**）+ `core/sandbox_script.py`（子进程同规则副本，改一处必须同步） |
| 解析表达式字符串 | `mathlab/core/expression_guard.py`（`safe_parse_expr` / `safe_sympify`，**禁止**直接用 sympy 的 `sympify`/`parse_expr`） |
| 加异步任务 | `mathlab/core/async_workers.py`（`QRunnable` + `QThreadPool`） |
| 排查启动崩溃 | `mathlab/crash.log`、`mathlab/mathlab.log`、`main.py::_write_crash_log` |
| 查 API | `mathlab/docs/api.md`、`docs/user_guide.md` |
