<p align="center">
  <img src="https://img.shields.io/badge/license-CASAL%20v4.0-blue.svg" alt="License">
  <img src="https://img.shields.io/badge/python-3.10+-brightgreen.svg" alt="Python">
  <img src="https://img.shields.io/badge/PySide6-6.5+-red.svg" alt="PySide6">
  <img src="https://img.shields.io/badge/version-3.8.0-orange.svg" alt="Version">
  <img src="https://img.shields.io/badge/tests-419%20passed-brightgreen.svg" alt="Tests">
  <img src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg" alt="Platform">
</p>

<div align="center">

# 🧮 MathLab (Axiom)

**下一代多智能体交互式数学教育与科研平台**

*从 MOOC 到 MAIC，打造 AI 驱动的智能教学新范式*

</div>

***

## 📋 目录

- [🌟 核心亮点](#-核心亮点)
- [✨ 功能特性](#-功能特性)
- [🏗️ 系统架构](#-系统架构)
- [🎓 自适应学习系统](#-自适应学习系统)
- [📚 教学法引导引擎](#-教学法引导引擎)
- [🔄 结构化通信协议](#-结构化通信协议)
- [🚀 快速开始](#-快速开始)
- [🧪 测试](#-测试)
- [🛠️ 开发指南](#-开发指南)
- [📁 项目结构](#-项目结构)
- [🔧 技术栈](#-技术栈)
- [🧩 插件系统](#-插件系统)
- [📡 API 接口](#-api-接口)
- [📦 构建与发布](#-构建与发布)
- [📝 路线图](#-路线图)
- [🤝 贡献指南](#-贡献指南)
- [📄 许可证](#-许可证)
- [📬 联系方式](#-联系方式)

***

## 🌟 核心亮点

MathLab 3.8 完成了六大核心维度的跃迁，打造了"自动驾驶级别"的 AI 教学基建：

| 阶段          | 能力        | 亮点                                      |
| :---------- | :-------- | :-------------------------------------- |
| **Phase 1** | 视觉安全掌控    | 状态栏实时监控、影子状态追踪、安全沙盒隔离                   |
| **Phase 2** | 多智能体分工    | Swarm 架构、Transfer Protocol 智能路由、自我反思纠错  |
| **Phase 3** | JIT 上下文组装 | 按需加载、Token 费用优化、Lost in Middle 问题解决     |
| **Phase 4** | 思执分离双轨制   | 教研组长规划 + 授课讲师讲解，沉浸式苏格拉底教学               |
| **Phase 5** | 自适应学习引擎   | Bloom/ZPD/UDL 认知建模，个性化教学体验              |
| **Phase 6** | 结构化通信协议   | AgentMessage 标准格式、MessageBus 消息总线、多模式通信 |

***

## ✨ 功能特性

| 类别                | 特性            | 说明                                         |
| :---------------- | :------------ | :----------------------------------------- |
| 🤖 **L3 多智能体**    | Swarm 协作架构    | 意图识别、自动路由、自我反思与纠错重试                        |
| 📐 **专业几何画板**     | DAG 依赖引擎      | 支持圆锥曲线、约束求解与轨迹追踪                           |
| 🧊 **3D 渲染引擎**    | Three.js 可视化  | 曲面、向量场、等值面、GPU 分形                          |
| 🧮 **CAS 符号计算**   | SymPy 封装      | 方程求解、微积分、极限、因式分解                           |
| 📓 **交互笔记本**      | Cell 笔记本      | Markdown / 代码 / 公式 / 画板混排                  |
| 🧠 **AI 多智能体系统**  | 11 家大模型接入     | OpenAI / DeepSeek / Claude / Gemini / 通义千问 |
| 🔌 **Jupyter 集成** | 内嵌 JupyterLab | Python 与 Qt 双向变量同步                         |
| ⚡ **C# 加速内核**     | pythonnet 桥接  | 几何采样 / FFT / 复数 / 数值积分加速                   |
| 🛡️ **安全沙箱**      | subprocess 隔离 | 超时与内存限制保护                                  |
| 🧩 **插件系统**       | 可扩展 API       | 内置 3D Viewer、ECharts、矩阵工具、微积分工具、动画演示     |
| 🎓 **自适应学习**      | 认知建模          | Bloom/ZPD/UDL 个性化教学                        |
| 📚 **教学法引擎**      | 三维度评估         | 教学质量可控、教育原则约束                              |
| 🔄 **结构化通信**      | 标准协议          | Agent 间可靠消息传递                              |

***

## 🏗️ 系统架构

### 五层架构体系

```
┌────────────────────────────────────────────────────────────────────────┐
│                       用户界面层 (UI Layer)                            │
│ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐   │
│ │2D 画板 │ │3D 画板 │ │笔记本  │ │命令面板│ │Agent UI│ │Jupyter │   │
│ └────────┘ └────────┘ └────────┘ └────────┘ └────────┘ └────────┘   │
├────────────────────────────────────────────────────────────────────────┤
│                      业务逻辑层 (Core Layer)                           │
│ ┌────────────────────────────────────────────────────────────────┐    │
│ │ 几何引擎 (DAG)   CAS 数学总线   动画引擎   多智能体路由管理    │    │
│ │ 自适应学习引擎   教学法引擎     消息总线    Agent 通信协议     │    │
│ └────────────────────────────────────────────────────────────────┘    │
├────────────────────────────────────────────────────────────────────────┤
│                      扩展与数据引擎 (Data & VM Layer)                  │
│ ┌────────────────────────────────────────────────────────────────┐    │
│ │ Plugin VM        NumEngine      WebEngine Sandbox              │    │
│ └────────────────────────────────────────────────────────────────┘    │
├────────────────────────────────────────────────────────────────────────┤
│                      安全隔离层 (Sandbox Layer)                        │
│ ┌────────────────────────────────────────────────────────────────┐    │
│ │  Python REPL (subprocess)  │  WebEngine Sandbox  │  Plugin VM │    │
│ └────────────────────────────────────────────────────────────────┘    │
├────────────────────────────────────────────────────────────────────────┤
│                      数据与协作层 (Data Layer)                         │
│ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐                 │
│ │ 项目文件 │ │ 资源库   │ │ WebSocket│ │ 云端同步 │                 │
│ │ (.mlproj)│ │(教学资源)│ │ 协作引擎 │ │(可选)    │                 │
│ └──────────┘ └──────────┘ └──────────┘ └──────────┘                 │
└────────────────────────────────────────────────────────────────────────┘
```

### 核心引擎详解

#### GeometryEngine（几何引擎）

基于有向无环图（DAG）的依赖管理，支持几何对象的创建、更新和约束求解。

**支持的几何对象：**

- **基础对象**：点（Point）、线段（Segment）、直线（Line）、圆（Circle）
- **圆锥曲线**：椭圆（Ellipse）、双曲线（Hyperbola）、抛物线（Parabola）、一般圆锥曲线（ConicSection）
- **函数图像**：显式函数（FunctionPlot）、隐函数（ImplicitPlot）、极坐标函数（PolarPlot）
- **高级对象**：多边形（Polygon）、轨迹（Locus）

#### CASProvider（符号计算引擎）

封装 SymPy 提供表达式化简、方程求解、微积分运算等功能。

#### Agent Registry & Tools（多智能体系统）

内建丰富的专家团队和数十种原子操作 Tool 调用：

| 专家 ID      | 名称   | 图标 | 专属工具                                                   |
| :--------- | :--- | :- | :----------------------------------------------------- |
| `general`  | 全科助教 | 🟢 | Transfer Protocol                                      |
| `geometry` | 几何专家 | 📐 | execute\_geometry\_draw, highlight\_geometry\_elements |
| `quiz`     | 出题考官 | 📝 | quiz\_generator                                        |
| `planner`  | 教研组长 | 🧠 | submit\_teaching\_plan                                 |

#### Notebook（交互笔记本）

SageMath 风格的 Cell 笔记本，支持 Markdown 和代码单元格的混合编排。

***

## 🎓 自适应学习系统

基于论文《From MOOC to MAIC》设计的自适应学习引擎，实现个性化教学体验。

### 学生认知模型（StudentModel）

多维度追踪学习状态：

| 维度        | 说明                               |
| :-------- | :------------------------------- |
| **知识掌握度** | 各知识点的掌握程度（0.0\~1.0，EMA 平滑更新）     |
| **认知层级**  | 当前 Bloom 认知层级（记忆→理解→应用→分析→评价→创造） |
| **学习偏好**  | 视觉型/分析型/语言型/均衡型（UDL 多元表达）        |
| **薄弱知识点** | 掌握度低于 40% 的知识点列表                 |
| **参与度**   | 学习活跃度评分（0.0\~1.0）                |
| **互动历史**  | 最近 200 条互动记录                     |

### 最近发展区（ZPD）

动态调整内容难度，确保"跳一跳够得着"：

```
┌─────────────────────────────────────────────────────────────┐
│  恐慌区 ──────── 挑战区 ──────── 舒适区 ──────── 已有知识   │
│    ↑               ↑               ↑                       │
│   禁止          需要引导        独立完成                    │
│   直接跳转      用于成长        建立信心                    │
└─────────────────────────────────────────────────────────────┘
```

### 持久化存储

学生画像自动保存到 `~/.mathlab/student_profiles/`，跨会话保持学习进度。

***

## 📚 教学法引导引擎

基于教育理论的内容生成与质量评估系统。

### 教学法约束注入

将教育理论转化为 LLM 可执行的教学约束：

| 理论               | 应用                  |
| :--------------- | :------------------ |
| **Bloom 分类法**    | 教学步骤覆盖认知层级梯度，每步标注层级 |
| **Vygotsky ZPD** | 内容难度落在最近发展区内        |
| **UDL**          | 多元表达：每个概念至少用两种方式呈现  |
| **苏格拉底式**        | 禁止直接给答案，以引导式提问结尾    |

### 三维度质量评估

| 维度         | 权重  | 评估内容                 |
| :--------- | :-- | :------------------- |
| **内容理解**   | 40% | 公式/解释/中间步骤/内容长度      |
| **上下文连贯性** | 25% | 认知层级梯度/跨度/逻辑连接词      |
| **教学设计**   | 35% | 苏格拉底约束/UDL多元表达/脚手架约束 |

### 质量评估闭环

```
教学内容生成 → 三维度评估 → 生成改进反馈 → 注入 LLM 迭代优化
```

***

## 🔄 结构化通信协议

替代原有基于回调函数的 ad-hoc 通信方式。

### 消息类型（MessageType）

| 类型                                    | 用途     |
| :------------------------------------ | :----- |
| `TASK_REQUEST`                        | 请求执行任务 |
| `TASK_RESULT`                         | 任务执行结果 |
| `TASK_PROGRESS`                       | 任务进度更新 |
| `TASK_ERROR`                          | 任务执行错误 |
| `QUERY` / `RESPONSE`                  | 查询与响应  |
| `COLLABORATION_REQUEST/ACCEPT/REJECT` | 协作请求   |
| `NOTIFICATION` / `BROADCAST`          | 通知与广播  |

### 消息流转示例

```
PlannerAgent → (TASK_REQUEST) → GeometryAgent
GeometryAgent → (TASK_RESULT) → PlannerAgent
PlannerAgent → (TASK_PROGRESS) → 广播给所有订阅者
```

***

## 🚀 快速开始

### 环境要求

| 项目         | 要求                                  |
| :--------- | :---------------------------------- |
| **Python** | 3.10 或更高版本                          |
| **操作系统**   | Windows 10+、macOS 12+、Ubuntu 20.04+ |
| **内存**     | 建议 8GB 以上                           |
| **磁盘空间**   | 至少 2GB 可用空间                         |

### 安装步骤

#### 方式一：从源码安装（推荐）

```bash
# 1. 克隆仓库
git clone https://github.com/jencaoking/Axiom-Mathematics-Panel.git
cd Axiom-Mathematics-Panel

# 2. 创建虚拟环境
python -m venv venv

# 3. 激活虚拟环境
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

# 4. 安装依赖
pip install -r mathlab/requirements.txt

# 5.（可选）安装可选依赖：AI / 神经网络 / 高级可视化
pip install -r mathlab/requirements-optional.txt

# 6. 安装开发工具（可选）
pip install pre-commit
pre-commit install
```

#### 方式二：使用预编译包

从 [Releases](https://github.com/jencaoking/Axiom-Mathematics-Panel/releases) 页面下载对应平台的安装包：

- **Windows**：`MathLab-3.8.0-win64.exe`
- **macOS**：`MathLab-3.8.0-macos.dmg`
- **Linux**：`MathLab-3.8.0-linux.AppImage`

### 启动应用

```bash
# 开发模式
python mathlab/main.py

# 或使用模块方式
python -m mathlab
```

### 快速验证

启动后，在命令面板中输入以下命令验证安装：

```python
# 测试几何引擎
draw_point("A", 0, 0)
draw_point("B", 3, 4)
draw_line("AB", "A", "B")

# 测试 CAS
from mathlab.core.cas_provider import CASProvider
cas = CASProvider()
result = cas.solve_equation("x**2 - 4", "x")
print(result)  # 应输出 [-2, 2]
```

***

## 🧪 测试

### 运行测试

```bash
# 运行所有测试
cd mathlab
python -m pytest tests/ -v

# 运行特定测试文件
python -m pytest tests/test_geometry.py -v

# 运行带标记的测试
python -m pytest -m "not slow"

# 生成覆盖率报告
python -m pytest --cov=mathlab tests/
```

### 测试配置

测试配置位于 `pyproject.toml`：

```toml
[tool.pytest.ini_options]
testpaths = ["mathlab/tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
addopts = "-v --tb=short --strict-markers"
markers = [
    "slow: marks tests as slow",
    "qt: marks tests that require Qt event loop",
]
```

### 测试分类

| 类别    | 说明      | 命令                          |
| :---- | :------ | :-------------------------- |
| 单元测试  | 核心引擎测试  | `pytest tests/unit/`        |
| 集成测试  | 模块间交互测试 | `pytest tests/integration/` |
| UI 测试 | Qt 界面测试 | `pytest -m qt tests/`       |
| 性能测试  | 性能基准测试  | `pytest -m slow tests/`     |

### 新增测试覆盖（3.8）

| 模块                      | 测试数量     | 覆盖率 |
| :---------------------- | :------- | :-- |
| `student_model.py`      | 36 项     | 92% |
| `pedagogical_engine.py` | 32 项     | 97% |
| `agent_message.py`      | 26 项     | 90% |
| `plugins/calculus_tools` + `plugins/animation_studio` | 32 项 | 88% / 62% |
| **新增小计**                  | **126 项** | —   |

> 全量测试规模：22 个测试文件，约 **419** 个测试用例（unit / integration / e2e 分层）。

***

## 🛠️ 开发指南

### 开发环境搭建

```bash
# 安装开发依赖
pip install -r mathlab/requirements.txt
pip install -r mathlab/requirements-optional.txt

# 安装 pre-commit hooks
pre-commit install
```

### IDE 配置

#### VS Code

推荐安装以下扩展：

- Python (ms-python.python)
- Pylance (ms-python.vsc-python-indent)
- Python Indent (KevinRose.vsc-python-indent)

项目已包含 `.vscode/settings.json` 配置。

#### PyCharm

1. 打开项目根目录
2. 配置 Python 解释器为 `venv/Scripts/python`
3. 标记 `mathlab` 为 Sources Root

### 代码规范

- **格式化**：使用 `black` 进行代码格式化
- **Lint**：使用 `ruff` 进行代码检查
- **类型注解**：推荐使用 type hints
- **文档字符串**：使用 Google 风格

```bash
# 格式化代码
black mathlab/

# 代码检查
ruff check mathlab/

# 类型检查（可选）
mypy mathlab/
```

### 调试技巧

#### 使用 VS Code 调试

项目包含 `.vscode/launch.json`，可直接按 F5 启动调试。

#### 日志系统

MathLab 内置完整的日志系统：

```python
from mathlab.utils.logger import get_logger

logger = get_logger(__name__)
logger.info("这是一条信息日志")
logger.debug("这是一条调试日志")
logger.warning("这是一条警告日志")
logger.error("这是一条错误日志")
```

日志文件位于 `mathlab/logs/` 目录。

### 提交规范

使用 Conventional Commits 规范：

```
feat: 新功能
fix: 修复 bug
docs: 文档更新
style: 代码格式调整
refactor: 重构
test: 测试相关
chore: 构建/工具相关
```

***

## 📁 项目结构

```
Axiom-Mathematics-Panel/
├── MathLab.CSharpEngine/             # C# 加速内核（通过 pythonnet 桥接）
│   ├── FastMath.cs                   # 基础数学运算
│   ├── FastGeometry.cs               # 几何加速计算
│   ├── FastComplex.cs                # 复数运算
│   ├── FastFFT.cs                    # 快速傅里叶变换
│   ├── FastCalculus.cs               # 数值微积分
│   ├── FastMesh3D.cs                 # 3D 网格生成
│   └── MathLab.CSharpEngine.csproj   # C# 项目文件
├── mathlab/                          # 主包目录
│   ├── __init__.py                   # 包初始化（延迟导入）
│   ├── main.py                       # 应用入口
│   ├── setup.py                      # setuptools 配置
│   ├── build_spec.spec               # PyInstaller 打包配置
│   ├── config/                       # 配置文件
│   │   ├── settings.json             # 默认配置
│   │   ├── ai_providers.json         # AI 提供商配置
│   │   ├── ai_tools_schema.py        # AI 工具 schema
│   │   └── prompts.yaml              # 提示词模板（含教学法模板库）
│   ├── core/                         # 核心引擎
│   │   ├── agent_bridge.py           # Agent 桥接
│   │   ├── agent_message.py          # 结构化通信协议（ACP）
│   │   ├── agent_registry.py         # 多智能体注册表（含消息总线）
│   │   ├── ai_manager.py             # AI 管理器（含 Worker）
│   │   ├── ai_provider_config.py      # AI 提供商配置
│   │   ├── ai_tools.py               # AI 工具定义
│   │   ├── algo_animator.py          # 算法动画器
│   │   ├── animation.py              # 动画引擎
│   │   ├── async_workers.py          # 异步工作线程
│   │   ├── canvas_tracker.py         # 画布状态追踪
│   │   ├── cas_provider.py           # CAS 符号计算（SymPy）
│   │   ├── command_manager.py        # 命令管理器
│   │   ├── context_assembler.py      # JIT 上下文组装器
│   │   ├── cs_*_engine.py            # C# 引擎桥接（6 个）
│   │   ├── error_manager.py          # 全局错误管理器
│   │   ├── extension_api.py          # 插件扩展 API
│   │   ├── geogebra_engine.py        # GeoGebra 兼容引擎
│   │   ├── geometry_engine.py        # 几何引擎核心（DAG）
│   │   ├── geometry_helpers.py        # 几何辅助函数
│   │   ├── ipc_client.py             # IPC 客户端
│   │   ├── ipc_server.py             # IPC 服务端
│   │   ├── jupyter_manager.py        # Jupyter 管理器
│   │   ├── memory_manager.py         # 内存管理器
│   │   ├── notebook.py               # 笔记本核心
│   │   ├── num_engine.py             # 数值计算引擎
│   │   ├── octave_bridge.py          # Octave 桥接
│   │   ├── pedagogical_engine.py     # 教学法引导引擎
│   │   ├── plugin_base.py            # 插件基类
│   │   ├── plugin_manager.py         # 插件管理器
│   │   ├── prompt_manager.py         # 提示词管理器
│   │   ├── python_repl.py            # Python REPL 子进程
│   │   ├── sandbox.py                # 沙盒环境
│   │   ├── sandbox_script.py         # 沙盒脚本
│   │   ├── sandbox_security.py       # 沙盒安全策略
│   │   ├── signals.py                # Qt 信号定义
│   │   ├── skill_manager.py          # AI 技能管理器
│   │   ├── smart_guides.py           # 智能辅助线
│   │   └── student_model.py          # 学生认知模型与自适应引擎
│   ├── data/                         # 数据层
│   ├── docs/                         # 项目文档
│   ├── locale/                       # 国际化
│   ├── plugins/                      # 内置插件
│   ├── resources/                    # 资源文件
│   ├── tests/                        # 测试用例
│   ├── ui/                           # 用户界面
│   ├── utils/                        # 工具函数
│   ├── scripts/                      # 脚本工具
│   ├── requirements.txt              # 核心依赖
│   └── requirements-optional.txt     # 可选依赖（AI/3D）
├── .github/                          # GitHub 配置
│   └── workflows/                    # CI/CD 工作流
├── DOCS/                             # 开发文档
├── pyproject.toml                    # pytest 配置
├── mathlab.spec                      # PyInstaller 配置
├── LICENSE                           # CASAL v4.0 许可证
└── README.md                         # 项目说明（本文档）
```

***

## 🔧 技术栈

### 核心依赖（运行必须）

| 类别           | 技术       | 版本     | 用途                             |
| :----------- | :------- | :----- | :----------------------------- |
| **GUI 框架**   | PySide6  | ≥6.5.0 | Qt for Python，跨平台桌面 UI         |
| **符号计算**     | SymPy    | ≥1.12  | CAS 符号计算引擎                     |
| **数值计算**     | NumPy    | ≥1.26  | 数组运算、线性代数                      |
| **科学计算**     | SciPy    | ≥1.11  | 高级数值算法（含 `least_squares` 约束求解） |
| **图论**       | NetworkX | ≥3.1   | 图数据结构与算法                       |
| **代码补全**     | Jedi     | ≥0.19  | Python 代码智能提示                  |
| **进程监控**     | psutil   | ≥5.9   | 系统资源监控                         |
| **HTTP 客户端** | requests | ≥2.31  | Jupyter IPC 与云端调用              |

### AI 集成（多提供商）

| 组件                                                | 用途           |
| :------------------------------------------------ | :----------- |
| OpenAI / DeepSeek / Claude / Gemini / 通义千问 等 11 家 | 大语言模型接入（可插拔） |
| Function Calling                                  | 工具调用协议       |
| Streaming                                         | 流式响应         |

### 可选依赖（按需安装）

```bash
# AI 机器学习能力
pip install mathlab[ai]

# 深度学习能力
pip install mathlab[neural]

# 高级可视化
pip install mathlab[visualization]

# 全部可选依赖
pip install mathlab[full]
```

### C# 加速内核

| 模块                                         | 用途                    |
| :----------------------------------------- | :-------------------- |
| `MathLab.CSharpEngine` (.NET Standard 2.0) | 通过 pythonnet 桥接的本地加速库 |
| FastMath                                   | 基础数学运算                |
| FastGeometry                               | 几何加速计算（圆锥曲线采样等）       |
| FastComplex                                | 复数运算                  |
| FastFFT                                    | 快速傅里叶变换               |
| FastCalculus                               | 数值微积分                 |
| FastMesh3D                                 | 3D 网格生成               |
| MathNet.Numerics                           | C# 数值计算基础库            |

### 开发工具

| 工具                   | 用途           |
| :------------------- | :----------- |
| pytest               | 单元测试         |
| pre-commit           | Git hooks    |
| PyInstaller / Nuitka | 应用打包         |
| TypeScript + Webpack | WebView 前端构建 |

***

## 🧩 插件系统

MathLab 支持插件扩展，内置以下插件：

### 内置插件

| 插件                     | 功能                                                            |
| :--------------------- | :---------------------------------------------------------- |
| **3D Viewer**          | 参数曲面、隐函数曲面、向量场可视化、交互式旋转/缩放                                  |
| **ECharts Viewer**     | 柱状图、折线图、饼图、散点图、热力图、实时数据更新                                   |
| **Matrix Tools**       | 矩阵可视化、特征值/特征向量、SVD 分解、矩阵运算                                  |
| **Calculus Tools**     | 导数与切线、定积分（带阴影区域）、极限、泰勒展开；计算结果可一键绘制到几何画板                     |
| **Animation Studio**   | 平移/旋转/缩放几何变换动画、函数参数动画（如 `sin(a*x)` 中 `a` 连续变化）、缓动函数、播放控制     |

### P0 插件功能详解

#### Calculus Tools（微积分工具）

基于 `CASProvider`（SymPy 封装）+ `GeometryEngine` 的可视化微积分面板：

- **导数与切线**：求 `f'(x)` 符号表达式，并在指定 `x₀` 处绘制切线 `FunctionPlot`
- **定积分**：计算 `∫ₐᵇ f(x)dx` 精确值，阴影区域通过多边形对象可视化
- **极限**：支持 `x → x₀` 与 `x → ±∞`，自动检测左右极限
- **泰勒展开**：在 `x₀` 处展开到 `n` 阶，将逼近多项式绘制为函数曲线

设计要点：
- `_plotted_ids` 追踪所有生成的几何对象，`cleanup()` 时统一清理
- 所有 CAS 调用通过 `try/except` 包装，错误信息回显到状态栏
- 通过 `getattr(self.api, "_main_window")` 防御式访问 `geometry_engine` 与 `cas_provider`

#### Animation Studio（动画演示）

基于 `QTimer` + `_anim_state` 状态机的动画引擎：

- **平移（Translate）**：所有选中点按 `Δx, Δy` 平移
- **旋转（Rotate）**：以 `(cx, cy)` 为中心、`θ°` 为角度旋转
- **缩放（Scale）**：以 `(cx, cy)` 为中心、`k` 为因子缩放
- **函数参数动画（Param Func）**：表达式 `f(a, x)` 中的参数 `a` 在 `[a_start, a_end]` 区间连续变化，实时刷新 `FunctionPlot`

设计要点：
- 缓动函数 `_ease_in_out(t) = 0.5 * (1 - cos(πt))` 实现平滑加减速
- `block_signals(True)` 批量更新点位置后手动 `_notify()` 触发画布刷新
- 停止/暂停时通过 `_restore_originals()` 恢复点原始坐标
- `_start_param_func` 返回 `True/False`，`_on_play` 检查返回值避免无效状态切换

### 开发自定义插件

```python
from mathlab.core.plugin_base import MathLabPlugin

class MyPlugin(MathLabPlugin):
    """自定义插件示例"""

    def __init__(self, api):
        super().__init__(api)
        self.name = "My Plugin"
        self.version = "1.0.0"

    def activate(self):
        """插件激活时调用"""
        self.api.register_command("my_command", self.my_handler)

    def deactivate(self):
        """插件停用时调用"""
        self.api.unregister_command("my_command")

    def my_handler(self, *args):
        """命令处理器"""
        # 你的逻辑
        pass
```

***

## 📡 API 接口

### Python 包 API（延迟导入）

MathLab 作为标准 Python 包暴露顶级类，支持按需延迟加载避免启动时阻塞：

```python
import mathlab

# 延迟加载核心类（仅在访问时触发实际导入）
geometry = mathlab.GeometryEngine()
cas = mathlab.CASProvider()
ai = mathlab.AIManager()
repl = mathlab.PythonREPL()
project = mathlab.ProjectManager()
sandbox = mathlab.SandboxManager()
```

### Python REPL 命名空间 API

应用启动时，`python_repl.update_namespace()` 会自动注入一系列快捷函数到 Jupyter 内核中：

```python
# ── 几何绘制 ──
draw_point(x, y)                # 绘制点
draw_segment(p1, p2)            # 绘制线段
draw_circle(center, radius)     # 绘制圆
draw_ellipse(center_id, a, b)   # 绘制椭圆
draw_hyperbola(center_id, a, b) # 绘制双曲线
draw_parabola(vertex_id, p, direction) # 绘制抛物线

# ── 函数绘图 ──
plot_function(expr, x_range=(-10, 10))  # 显式函数
plot_implicit(expr, x_range, y_range)    # 隐函数
plot_polar(expr, theta_range=(0, 2π))   # 极坐标函数

# ── CAS 运算 ──
solve(equation, var)          # 方程求解
simplify(expression)          # 化简
integrate(expr, var)          # 积分
differentiate(expr, var)      # 求导
limit(expr, var, point)       # 极限
```

### IPC 通信

MathLab 使用 UDP 协议进行进程间通信（Qt 主进程 ↔ Python 内核）：

- **发送端口**：45678（Python → Qt）
- **接收端口**：45679（Qt → Python）

***

## 📦 构建与发布

### 使用 PyInstaller 构建

```bash
# 构建可执行文件
pyinstaller mathlab/build_spec.spec

# 输出位于 dist/ 目录
```

### 使用 Nuitka 构建

```bash
# Nuitka 构建（性能更优）
python -m nuitka --standalone --enable-plugin=pyside6 mathlab/main.py
```

### CI/CD 工作流

项目使用 GitHub Actions 进行自动化：

| 工作流             | 触发条件                             | 执行内容                       |
| :-------------- | :------------------------------- | :------------------------- |
| **test.yml**    | Push 到 main/develop，Pull Request | 代码检查、单元测试、覆盖率报告            |
| **release.yml** | 创建 Tag（v\*）                      | 构建多平台发布包、创建 GitHub Release |

### 版本管理

版本号遵循语义化版本（Semantic Versioning）：

- **主版本号**：不兼容的 API 变更
- **次版本号**：向下兼容的功能新增
- **修订号**：向下兼容的问题修复

***

## 📝 路线图

### 版本历史

| 版本      | 代号    | 主要特性                                         |
| :------ | :---- | :------------------------------------------- |
| **1.0** | -     | 基础几何画板                                       |
| **2.0** | speed | 异步计算中枢、3D 渲染引擎、AI 集成                         |
| **2.5** | axiom | GeoGebra 约束求解、笔记本、动画引擎、插件系统                  |
| **2.6** | -     | JupyterLab 嵌入、UDP IPC 双向通信                   |
| **3.0** | -     | Agentic UI、NL2Draw 自然语言作图、视觉错题本              |
| **3.5** | -     | 多智能体架构、思执分离大纲双轨制、纠错重试环                       |
| **3.7** | -     | C# 加速内核、函数探索器、复数面板、信号实验、GPU 分形、Skill Library |
| **3.8** | -     | 🌟 自适应学习引擎（Bloom/ZPD/UDL）、教学法引导引擎、结构化通信协议、Calculus Tools 与 Animation Studio 插件 |

### 未来规划

#### 4.0 计划

- **同学 Agent**：多种性格的 AI 同学角色（Class Clown、Deep Thinker、Note Taker、Inquisitive Mind）
- **Web 同步**：跨设备数据同步
- **多人协作**：实时协作编辑
- **插件市场**：第三方插件生态
- **云端教学资源**：在线资源库

#### 长期愿景

- 支持更多数学引擎（Maxima、Giac）
- 完整的动画导出系统（GIF/MP4/SVG）
- 教学资源社区
- 移动端支持

***

## 🤝 贡献指南

我们欢迎所有形式的贡献！

### 如何贡献

1. **Fork** 本仓库
2. **创建特性分支**：`git checkout -b feature/amazing-feature`
3. **提交更改**：`git commit -m 'feat: Add amazing feature'`
4. **推送到分支**：`git push origin feature/amazing-feature`
5. **创建 Pull Request**

### 贡献类型

- 🐛 **Bug 修复**：修复已知问题
- ✨ **新功能**：添加新的特性
- 📝 **文档**：完善项目文档
- 🧪 **测试**：增加测试覆盖率
- 🎨 **UI/UX**：界面和交互优化
- 🔧 **重构**：代码质量改进

### 开发规范

- 遵循 Conventional Commits 规范
- 确保所有测试通过
- 更新相关文档
- 保持代码风格一致

***

## 📄 许可证

本项目采用 **Custom Advanced Source-Available License v1.0（CASAL v4.0）** 开源（源可用）许可证，版权归 **Jinpeng Cao (jencao)** 所有，发布于 2026 年 7 月 22 日。

> ⚠️ **重要提示**：CASAL 是一份**非 OSI 认证、源可用（source-available）的自定义许可证，与 Apache 2.0 有本质区别。它在允许查看、修改与分发源代码的同时，对**竞争性使用、**AI/ML 训练**以及**不道德应用**施加了严格限制，并包含强 Copyleft 义务。若需在闭源、商业竞争或 AI 训练场景下使用，须向版权方获取单独的商业授权。

核心条款摘要：

- **强制 Copyleft**：分发、托管（含 SaaS/云/API）衍生作品时，须以相同（或实质等同）许可证公开完整源代码。
- **署名保留**：所有副本与显著位置须保留版权声明、完整许可证文本与免责声明。
- **衍生作品改名**：修改后的分发版本须明确标注并采用区别于原项目（不得使用 "jencao"、"Cao" 等易混淆名称）的名称。
- **伦理限制**：禁止用于违法监控、侵犯人权、军事或核设施等场景。
- **非竞争条款**：不得利用本项目开发、推广或分发与原作者核心产品构成竞争的产品。
- **AI/ML 训练禁止**：禁止将本项目（含源码、文档、日志等）用于训练、微调或验证任何 AI/ML/LLM 系统。

完整条款请查阅 [LICENSE](LICENSE) 文件。

***

## 📬 联系方式

| 渠道       | 信息                                                                  |
| :------- | :------------------------------------------------------------------ |
| **项目主页** | <https://github.com/jencaoking/Axiom-Mathematics-Panel>             |
| **问题反馈** | <https://github.com/jencaoking/Axiom-Mathematics-Panel/issues>      |
| **讨论社区** | <https://github.com/jencaoking/Axiom-Mathematics-Panel/discussions> |
| **邮箱**   | <jencaoking@outlook.com>                                            |

***

## 🙏 致谢与引用

MathLab 受益于以下卓越的开源项目与框架：

- **[PySide6](https://doc.qt.io/qtforpython-6/)** — Qt for Python
- **[SymPy](https://www.sympy.org/)** — 符号计算库
- **[NumPy](https://numpy.org/)** — 数值计算基础
- **[SciPy](https://scipy.org/)** — 科学计算库
- **[NetworkX](https://networkx.org/)** — 图论库
- **[Jupyter](https://jupyter.org/)** — 交互式计算环境
- **[Three.js](https://threejs.org/)** — 3D 渲染
- **[ECharts](https://echarts.apache.org/)** — 数据可视化

### 引用本项目

如果您在学术研究中使用了 MathLab，请引用：

```bibtex
@software{mathlab_jupyter,
  title  = {MathLab (Axiom): Interactive Mathematics, AI and 3D Teaching Software},
  author = {MathLab Team},
  version = {3.8.0},
  year   = {2026},
  url    = {https://github.com/jencaoking/Axiom-Mathematics-Panel}
}
```

***

<div align="center">

**⭐ Star us on GitHub** · **🐛 Report a Bug** · **✨ Request a Feature**

Built with ❤️ by jencao

</div>
