from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

doc = Document()

# ── 样式设置 ──────────────────────────────────────────────
style = doc.styles['Normal']
style.font.name = 'Microsoft YaHei'
style.font.size = Pt(11)
style._element.rPr.rFonts.set(qn('w:eastAsia'), 'Microsoft YaHei')

# 标题1
h1 = doc.styles['Heading 1']
h1.font.name = 'Microsoft YaHei'
h1.font.size = Pt(20)
h1.font.bold = True
h1.font.color.rgb = RGBColor(0x1F, 0x3A, 0x5F)
h1._element.rPr.rFonts.set(qn('w:eastAsia'), 'Microsoft YaHei')

# 标题2
h2 = doc.styles['Heading 2']
h2.font.name = 'Microsoft YaHei'
h2.font.size = Pt(16)
h2.font.bold = True
h2.font.color.rgb = RGBColor(0x2C, 0x5F, 0x8E)
h2._element.rPr.rFonts.set(qn('w:eastAsia'), 'Microsoft YaHei')

# 标题3
h3 = doc.styles['Heading 3']
h3.font.name = 'Microsoft YaHei'
h3.font.size = Pt(13)
h3.font.bold = True
h3.font.color.rgb = RGBColor(0x3A, 0x7C, 0xBD)
h3._element.rPr.rFonts.set(qn('w:eastAsia'), 'Microsoft YaHei')


def add_heading1(text):
    p = doc.add_heading(text, level=1)
    return p


def add_heading2(text):
    p = doc.add_heading(text, level=2)
    return p


def add_heading3(text):
    p = doc.add_heading(text, level=3)
    return p


def add_para(text, bold=False, italic=False):
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.bold = bold
    run.italic = italic
    return p


def add_bullet(text):
    p = doc.add_paragraph(text, style='List Bullet')
    return p


def add_table(headers, rows, col_widths=None):
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = 'Light Grid Accent 1'
    hdr_cells = table.rows[0].cells
    for i, h in enumerate(headers):
        hdr_cells[i].text = h
        for paragraph in hdr_cells[i].paragraphs:
            for run in paragraph.runs:
                run.bold = True
                run.font.size = Pt(10)
    for row_data in rows:
        row_cells = table.add_row().cells
        for i, cell_data in enumerate(row_data):
            row_cells[i].text = str(cell_data)
            for paragraph in row_cells[i].paragraphs:
                for run in paragraph.runs:
                    run.font.size = Pt(10)
    if col_widths:
        for i, w in enumerate(col_widths):
            for cell in table.columns[i].cells:
                cell.width = Inches(w)
    return table


# ═══════════════════════════════════════════════════════
#  封面
# ═══════════════════════════════════════════════════════
doc.add_paragraph()
doc.add_paragraph()
doc.add_paragraph()

title = doc.add_paragraph()
title.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = title.add_run('MathLab (Axiom)')
run.font.size = Pt(36)
run.bold = True
run.font.color.rgb = RGBColor(0x1F, 0x3A, 0x5F)

subtitle = doc.add_paragraph()
subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = subtitle.add_run('多智能体交互式数学教育与科研桌面平台')
run.font.size = Pt(18)
run.font.color.rgb = RGBColor(0x55, 0x55, 0x55)

doc.add_paragraph()
doc.add_paragraph()
doc.add_paragraph()

info = doc.add_paragraph()
info.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = info.add_run('项目分析报告')
run.font.size = Pt(22)
run.bold = True
run.font.color.rgb = RGBColor(0x2C, 0x5F, 0x8E)

doc.add_paragraph()
doc.add_paragraph()

meta = doc.add_paragraph()
meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = meta.add_run('版本：3.5.0  |  许可证：Apache 2.0')
run.font.size = Pt(12)
run.font.color.rgb = RGBColor(0x77, 0x77, 0x77)

doc.add_page_break()

# ═══════════════════════════════════════════════════════
#  目录
# ═══════════════════════════════════════════════════════
add_heading1('目录')

toc_items = [
    '1. 项目概述',
    '2. 系统架构',
    '3. 核心模块分析',
    '4. 技术栈',
    '5. 功能模块详解',
    '6. 插件系统',
    '7. 测试与质量保证',
    '8. 构建与发布',
    '9. 已知问题与风险',
    '10. 路线图与发展规划',
    '11. 代码质量评估',
    '12. 总结与建议',
]

for item in toc_items:
    p = doc.add_paragraph(item)
    p.paragraph_format.space_after = Pt(4)

doc.add_page_break()

# ═══════════════════════════════════════════════════════
#  1. 项目概述
# ═══════════════════════════════════════════════════════
add_heading1('1. 项目概述')

add_heading2('1.1 项目简介')
add_para(
    'MathLab（又称 Axiom）是一款面向未来的多智能体交互式数学教育与科研桌面软件。'
    '它突破了传统"套壳聊天框"的局限，打造了一套工业级、L5 自动化自治的多智能体（Multi-Agent）桌面环境。'
    '从基础的几何作图、代数求解，到复杂的定理证明和交互式教学大纲驱动，'
    'MathLab 融合了本地高性能图形引擎与云端大语言模型，并配以 Agentic UI 设计。'
)

add_heading2('1.2 基本信息')
add_table(
    ['项目属性', '描述'],
    [
        ['项目名称', 'MathLab (Axiom)'],
        ['当前版本', '3.5.0'],
        ['许可证', 'Apache License 2.0'],
        ['Python 版本', '3.10+'],
        ['GUI 框架', 'PySide6 (Qt for Python)'],
        ['项目类型', '桌面应用 / 数学教育软件'],
        ['核心语言', 'Python + C# (数值计算引擎)'],
        ['仓库地址', 'github.com/jencaoking/Axiom-Mathematics-Panel'],
    ],
    col_widths=[1.8, 4.2],
)

add_heading2('1.3 核心亮点')
add_bullet('L5 Agentic 架构：多智能体分工协作，支持意图识别与自动任务分发')
add_bullet('DAG 几何引擎：基于有向无环图的依赖管理，支持实时约束求解')
add_bullet('JIT 上下文组装：按需注入相关上下文，解决 Token 爆炸和注意力稀释问题')
add_bullet('思执分离双轨制：教研规划层与课堂讲解层分离，实现沉浸式教学')
add_bullet('沙盒安全机制：Python REPL、WebEngine、Plugin VM 三层隔离')
add_bullet('插件化架构：支持功能扩展，内置 3D Viewer、ECharts、Matrix Tools 等插件')

doc.add_page_break()

# ═══════════════════════════════════════════════════════
#  2. 系统架构
# ═══════════════════════════════════════════════════════
add_heading1('2. 系统架构')

add_heading2('2.1 五层架构体系')
add_para(
    'MathLab 采用分层架构设计，自底向上分为数据层、安全隔离层、扩展与数据引擎层、'
    '业务逻辑层和用户界面层，各层职责清晰，耦合度低。'
)

add_table(
    ['层级', '模块', '职责描述'],
    [
        ['用户界面层', '2D画板、3D画板、笔记本、命令面板、Agent UI、Jupyter', '人机交互，可视化展示'],
        ['业务逻辑层', '几何引擎(DAG)、CAS数学总线、动画引擎、多智能体路由', '核心业务逻辑处理'],
        ['扩展与数据引擎层', 'Plugin VM、NumEngine、WebEngine Sandbox', '扩展能力与数据处理'],
        ['安全隔离层', 'Python REPL (subprocess)、WebEngine Sandbox、Plugin VM', '安全隔离与资源管控'],
        ['数据与协作层', '项目文件(.mlproj)、资源库、WebSocket协作、云端同步', '数据持久化与协作'],
    ],
    col_widths=[1.2, 2.2, 2.6],
)

add_heading2('2.2 核心引擎架构')
add_heading3('2.2.1 GeometryEngine（几何引擎）')
add_bullet('基于有向无环图（DAG）的依赖管理')
add_bullet('支持几何对象的创建、更新和约束求解')
add_bullet('内置 C# 加速引擎（MathLab.CSharpEngine）可选')
add_bullet('支持点、线段、直线、圆、圆锥曲线、函数图像、多边形、轨迹等 19 种几何对象')

add_heading3('2.2.2 CASProvider（符号计算引擎）')
add_bullet('封装 SymPy 提供符号计算能力')
add_bullet('支持方程求解、表达式化简、微积分、极限、因式分解、级数展开等')

add_heading3('2.2.3 Agent Registry & Tools（多智能体系统）')
add_bullet('全科助教（general）：意图识别与任务分发')
add_bullet('几何专家（geometry）：几何作图与证明')
add_bullet('出题考官（quiz）：智能出题与难度评估')
add_bullet('教研组长（planner）：教学规划与大纲生成')

add_heading2('2.3 数据流与通信')
add_para(
    '系统采用 IPC（进程间通信）机制实现 Qt 界面与 Python 内核之间的双向通信。'
    '使用 UDP 协议，发送端口 45678（Python → Qt），接收端口 45679（Qt → Python）。'
    '变量同步机制确保 Python 内核与 Qt 界面的状态一致性。'
)

doc.add_page_break()

# ═══════════════════════════════════════════════════════
#  3. 核心模块分析
# ═══════════════════════════════════════════════════════
add_heading1('3. 核心模块分析')

add_heading2('3.1 目录结构')
add_table(
    ['目录', '主要职责', '关键文件数量'],
    [
        ['mathlab/core/', '核心引擎与业务逻辑', '约 35 个模块'],
        ['mathlab/ui/', '用户界面组件', '约 30 个模块'],
        ['mathlab/plugins/', '内置插件', '3 个插件'],
        ['mathlab/data/', '数据层与项目管理', '2 个模块'],
        ['mathlab/utils/', '工具函数与基础设施', '5 个模块'],
        ['mathlab/tests/', '单元测试与集成测试', '9 个测试文件'],
        ['MathLab.CSharpEngine/', 'C# 数值计算加速引擎', '6 个 C# 文件'],
    ],
    col_widths=[2.0, 3.0, 1.2],
)

add_heading2('3.2 核心模块详解')

add_heading3('3.2.1 mathlab/main.py — 应用入口')
add_bullet('初始化全局日志系统与错误处理')
add_bullet('创建 QApplication 与主窗口')
add_bullet('初始化所有核心引擎（GeometryEngine、CASProvider、AIManager 等）')
add_bullet('建立 Python REPL 命名空间映射')
add_bullet('加载插件系统')
add_bullet('支持 PyInstaller 打包与启动画面')

add_heading3('3.2.2 core/geometry_engine.py — 几何引擎')
add_bullet('GeometricObject 基类，定义 19 种几何对象类型')
add_bullet('DAG 依赖追踪系统（父子对象关系）')
add_bullet('约束求解：平行、垂直、相切、共线、共圆')
add_bullet('圆锥曲线支持：椭圆、双曲线、抛物线、一般二次曲线')
add_bullet('函数绘图：显式函数、隐函数、极坐标函数')
add_bullet('轨迹追踪（Locus）与动态几何')
add_bullet('可选 C# 加速后端（cs_geometry_engine）')

add_heading3('3.2.3 core/ai_manager.py — AI 管理器')
add_bullet('多智能体路由与意图识别')
add_bullet('Function Calling 工具调用系统')
add_bullet('Transfer Protocol 交接流转协议')
add_bullet('Fail Fast 失败重试机制')
add_bullet('Self-Reflection 自我纠错能力')
add_bullet('QThread 异步请求，避免 UI 阻塞')
add_bullet('ChatMemoryManager 对话记忆管理')

add_heading3('3.2.4 core/sandbox.py — 沙盒环境')
add_bullet('Python REPL 子进程隔离')
add_bullet('安全策略与权限控制')
add_bullet('代码执行环境限制')

add_heading3('3.2.5 core/plugin_manager.py — 插件管理')
add_bullet('插件生命周期管理（activate/deactivate）')
add_bullet('MathLabAPI 扩展接口')
add_bullet('插件发现与自动加载')

doc.add_page_break()

# ═══════════════════════════════════════════════════════
#  4. 技术栈
# ═══════════════════════════════════════════════════════
add_heading1('4. 技术栈')

add_heading2('4.1 核心依赖')
add_table(
    ['类别', '技术', '版本要求', '用途'],
    [
        ['GUI 框架', 'PySide6', '≥6.5.0', 'Qt for Python，跨平台桌面 UI'],
        ['符号计算', 'SymPy', '≥1.12', 'CAS 符号计算引擎'],
        ['数值计算', 'NumPy', '≥1.26', '数组运算、线性代数'],
        ['科学计算', 'SciPy', '≥1.11', '高级数值算法'],
        ['图论', 'NetworkX', '≥3.1', '图数据结构与算法'],
        ['代码补全', 'Jedi', '≥0.19', 'Python 代码智能提示'],
        ['进程监控', 'psutil', '≥5.9', '系统资源监控'],
        ['机器学习', 'scikit-learn', '可选', 'AI 辅助功能'],
        ['深度学习', 'PyTorch / ONNX Runtime', '可选', '神经网络推理'],
    ],
    col_widths=[1.0, 1.4, 1.0, 2.6],
)

add_heading2('4.2 Jupyter 集成')
add_table(
    ['组件', '版本要求', '用途'],
    [
        ['JupyterLab', '≥4.0', '交互式计算环境'],
        ['Jupyter Client', '≥8.0', 'Jupyter 协议客户端'],
        ['ipykernel', '≥6.0', 'IPython 内核'],
        ['Jupyter Server', '≥2.0', 'Jupyter 服务器'],
    ],
    col_widths=[1.5, 1.2, 3.3],
)

add_heading2('4.3 开发工具链')
add_table(
    ['工具', '用途'],
    [
        ['pytest + pytest-qt', '单元测试与 Qt 测试'],
        ['black', '代码格式化'],
        ['ruff', '代码检查 / Lint'],
        ['pre-commit', 'Git hooks 代码质量门禁'],
        ['PyInstaller / Nuitka', '可执行文件打包'],
        ['GitHub Actions', 'CI/CD 自动化流水线'],
    ],
    col_widths=[2.0, 4.0],
)

add_heading2('4.4 C# 加速引擎')
add_para(
    '项目包含 MathLab.CSharpEngine 子项目，基于 .NET Standard 2.0 构建，'
    '使用 MathNet.Numerics 库提供高性能数值计算。包括以下模块：'
)
add_bullet('FastMath.cs — 快速数学运算')
add_bullet('FastCalculus.cs — 微积分计算')
add_bullet('FastComplex.cs — 复数运算')
add_bullet('FastFFT.cs — 快速傅里叶变换')
add_bullet('FastGeometry.cs — 几何计算')
add_bullet('FastMesh3D.cs — 3D 网格处理')

doc.add_page_break()

# ═══════════════════════════════════════════════════════
#  5. 功能模块详解
# ═══════════════════════════════════════════════════════
add_heading1('5. 功能模块详解')

add_heading2('5.1 2D 几何画板')
add_bullet('自由绘制：点、线段、直线、圆、多边形')
add_bullet('约束系统：平行、垂直、相切、共线、共圆')
add_bullet('测量工具：距离、角度、面积、周长、斜率')
add_bullet('变换操作：反射、旋转、平移、缩放')
add_bullet('轨迹追踪：实时绘制点的运动轨迹')
add_bullet('代数面板：对象属性查看与编辑')

add_heading2('5.2 3D 渲染引擎')
add_bullet('基于 Three.js + PyQtWebEngine 的 3D 可视化')
add_bullet('参数曲面、隐函数曲面绘制')
add_bullet('三维向量场可视化')
add_bullet('等值面渲染')
add_bullet('交互式旋转、缩放、平移')

add_heading2('5.3 算法可视化')
add_bullet('排序算法：冒泡、快速、归并、堆排序')
add_bullet('图论算法：Dijkstra 最短路径、BFS/DFS 遍历')
add_bullet('动态规划：背包问题、最长公共子序列')
add_bullet('树操作：二叉树遍历、AVL 旋转')

add_heading2('5.4 AI 对话系统')
add_bullet('意图识别：自动判断作图/出题/讲解需求')
add_bullet('工具调用：Function Calling 实现画板操作')
add_bullet('上下文管理：JIT Context Assembly 按需加载')
add_bullet('多轮对话：支持上下文记忆')
add_bullet('多智能体协作：专家角色分工与交接')

add_heading2('5.5 Jupyter 集成')
add_bullet('内嵌 JupyterLab 交互式计算环境')
add_bullet('实时 Python 代码执行')
add_bullet('LaTeX 数学公式即时显示')
add_bullet('Python ↔ Qt 双向变量同步')
add_bullet('.ipynb 文件读写支持')

add_heading2('5.6 命令面板')
add_bullet('快捷键：Ctrl+K / Ctrl+Shift+P')
add_bullet('模糊搜索：关键词快速定位功能')
add_bullet('最近使用：记录常用操作')
add_bullet('自定义命令：支持用户扩展')

add_heading2('5.7 交互式笔记本')
add_bullet('SageMath 风格的 Cell 笔记本')
add_bullet('支持 CODE、MARKDOWN、MATH、GEO、PLOT 五种单元格类型')
add_bullet('Markdown + LaTeX 富文本支持')

doc.add_page_break()

# ═══════════════════════════════════════════════════════
#  6. 插件系统
# ═══════════════════════════════════════════════════════
add_heading1('6. 插件系统')

add_heading2('6.1 插件架构')
add_para(
    'MathLab 采用插件化架构设计，通过 MathLabPlugin 基类定义插件生命周期，'
    '支持动态加载与卸载。插件通过 MathLabAPI 与核心系统交互。'
)

add_heading2('6.2 内置插件')
add_table(
    ['插件名称', '目录', '主要功能', '技术实现'],
    [
        ['3D Viewer', 'plugin_3d_viewer', '3D 曲面、向量场、等值面可视化', 'Three.js + PyQtWebEngine'],
        ['ECharts Viewer', 'echarts_viewer', '柱状图、折线图、饼图、热力图', 'ECharts + WebEngine'],
        ['Matrix Tools', 'matrix_tools', '矩阵可视化、特征值、SVD 分解', 'NumPy + SciPy'],
    ],
    col_widths=[1.2, 1.5, 2.2, 1.5],
)

add_heading2('6.3 插件开发接口')
add_para('插件需继承 MathLabPlugin 基类，实现以下生命周期方法：')
add_bullet('__init__(api) — 构造函数，接收 MathLabAPI 实例')
add_bullet('activate() — 插件激活时调用，注册命令与面板')
add_bullet('deactivate() — 插件停用时调用，清理资源')

doc.add_page_break()

# ═══════════════════════════════════════════════════════
#  7. 测试与质量保证
# ═══════════════════════════════════════════════════════
add_heading1('7. 测试与质量保证')

add_heading2('7.1 测试框架')
add_bullet('测试框架：pytest + pytest-qt')
add_bullet('测试目录：mathlab/tests/')
add_bullet('配置文件：pyproject.toml [tool.pytest.ini_options]')

add_heading2('7.2 测试模块')
add_table(
    ['测试文件', '测试范围'],
    [
        ['test_core.py', '核心引擎基础功能'],
        ['test_geometry.py', '几何引擎功能测试'],
        ['test_analytic_geometry.py', '解析几何测试'],
        ['test_num_engine.py', '数值计算引擎测试'],
        ['test_function_explorer.py', '函数探索器测试'],
        ['test_octave_bridge.py', 'Octave 桥接测试'],
        ['test_sandbox_security.py', '沙盒安全性测试'],
        ['test_session_context.py', '会话上下文测试'],
        ['test_utils.py', '工具函数测试'],
    ],
    col_widths=[2.2, 3.8],
)

add_heading2('7.3 测试分类与标记')
add_table(
    ['标记', '说明'],
    [
        ['slow', '标记慢速测试，可通过 -m "not slow" 跳过'],
        ['qt', '标记需要 Qt 事件循环的测试'],
    ],
    col_widths=[1.5, 4.5],
)

add_heading2('7.4 代码规范')
add_bullet('格式化工具：black')
add_bullet('Lint 工具：ruff')
add_bullet('类型注解：推荐使用 type hints')
add_bullet('文档字符串：Google 风格')
add_bullet('提交规范：Conventional Commits')

doc.add_page_break()

# ═══════════════════════════════════════════════════════
#  8. 构建与发布
# ═══════════════════════════════════════════════════════
add_heading1('8. 构建与发布')

add_heading2('8.1 构建方式')
add_table(
    ['构建工具', '特点', '适用场景'],
    [
        ['PyInstaller', '成熟稳定，打包体积大', '常规发布'],
        ['Nuitka', '编译为 C 扩展，性能更优', '高性能需求'],
    ],
    col_widths=[1.5, 2.5, 2.0],
)

add_heading2('8.2 CI/CD 工作流')
add_table(
    ['工作流文件', '触发条件', '主要任务'],
    [
        ['test.yml', 'Push 到 main/develop, Pull Request', '代码检查、单元测试、覆盖率报告'],
        ['release.yml', 'Tag 创建 (v*)', '多平台构建、创建 GitHub Release'],
    ],
    col_widths=[1.4, 2.2, 2.4],
)

add_heading2('8.3 版本管理')
add_bullet('遵循语义化版本（Semantic Versioning）')
add_bullet('主版本号：不兼容的 API 变更')
add_bullet('次版本号：向下兼容的功能新增')
add_bullet('修订号：向下兼容的问题修复')

doc.add_page_break()

# ═══════════════════════════════════════════════════════
#  9. 已知问题与风险
# ═══════════════════════════════════════════════════════
add_heading1('9. 已知问题与风险')

add_heading2('9.1 已修复的 P0 级问题')
add_table(
    ['位置', '问题描述', '状态'],
    [
        ['ai_manager.py:171', 'Tool call 参数从未 JSON 反序列化', '已修复'],
        ['ai_manager.py:226,255', 'QThread.wait() 无超时导致 GUI 冻结', '已修复'],
    ],
    col_widths=[2.0, 3.0, 1.0],
)

add_heading2('9.2 现存 P1 级问题')
add_table(
    ['位置', '问题描述', '严重程度'],
    [
        ['ai_manager.py:253-270', '旧 QThread worker 未 deleteLater()，可能内存泄漏', '高'],
        ['sandbox.py:113-114', 'stdin.write() 无 try/except，异常可能崩溃', '高'],
        ['geometry_engine.py:364-365', '线段交点忽略线段边界，计算可能不准确', '高'],
    ],
    col_widths=[2.0, 3.0, 1.0],
)

add_heading2('9.3 潜在风险')
add_bullet('WebEngine 内存泄漏：Chromium 进程长期运行可能累积内存')
add_bullet('线程安全：多线程环境下的 Qt 对象生命周期管理')
add_bullet('插件兼容性：第三方插件可能影响系统稳定性')
add_bullet('大模型依赖：AI 功能依赖外部 API 可用性与费用')

doc.add_page_break()

# ═══════════════════════════════════════════════════════
#  10. 路线图与发展规划
# ═══════════════════════════════════════════════════════
add_heading1('10. 路线图与发展规划')

add_heading2('10.1 版本历史')
add_table(
    ['版本', '代号', '主要特性'],
    [
        ['1.0', '-', '基础几何画板'],
        ['2.0', 'speed', '异步计算中枢、3D 渲染引擎、AI 集成'],
        ['2.5', 'axiom', 'GeoGebra 约束求解、笔记本、动画引擎、插件系统'],
        ['3.0', '-', 'Agentic UI、NL2Draw 自然语言作图、视觉错题本'],
        ['3.5', '-', '多智能体架构、思执分离大纲双轨制、纠错重试环'],
    ],
    col_widths=[1.0, 1.0, 4.0],
)

add_heading2('10.2 4.0 规划')
add_bullet('Web 同步：跨设备数据同步')
add_bullet('多人协作：实时协作编辑')
add_bullet('插件市场：第三方插件生态')
add_bullet('云端教学资源：在线资源库')

add_heading2('10.3 长期愿景')
add_bullet('支持更多数学引擎（Maxima、Giac）')
add_bullet('完整的动画导出系统（GIF/MP4/SVG）')
add_bullet('教学资源社区')
add_bullet('移动端支持')

doc.add_page_break()

# ═══════════════════════════════════════════════════════
#  11. 代码质量评估
# ═══════════════════════════════════════════════════════
add_heading1('11. 代码质量评估')

add_heading2('11.1 架构设计评分')
add_table(
    ['评估维度', '评分', '说明'],
    [
        ['模块化程度', '优秀', '核心模块与 UI 分离清晰，插件化架构完善'],
        ['可扩展性', '优秀', '插件系统 + 扩展 API，功能扩展方便'],
        ['代码复用', '良好', 'DAG 引擎、工具函数等可复用程度高'],
        ['可测试性', '良好', '核心逻辑与 Qt UI 分离，便于单元测试'],
        ['文档完整性', '良好', 'README 详细，API 文档齐全'],
    ],
    col_widths=[1.5, 1.0, 3.5],
)

add_heading2('11.2 优点')
add_bullet('分层架构清晰，各层职责明确')
add_bullet('多智能体架构设计先进，支持 L5 Agentic 能力')
add_bullet('DAG 几何引擎设计合理，支持复杂约束求解')
add_bullet('插件化架构便于功能扩展')
add_bullet('沙盒安全机制保障代码执行安全')
add_bullet('C# 加速引擎提升数值计算性能')

add_heading2('11.3 改进建议')
add_bullet('修复现存 P1 级问题（内存泄漏、异常处理、几何计算精度）')
add_bullet('增加测试覆盖率，尤其是集成测试和 UI 测试')
add_bullet('完善类型注解，提升代码可维护性')
add_bullet('引入静态类型检查（mypy）')
add_bullet('优化 WebEngine 内存管理，防止泄漏')
add_bullet('完善插件安全沙盒机制')

doc.add_page_break()

# ═══════════════════════════════════════════════════════
#  12. 总结与建议
# ═══════════════════════════════════════════════════════
add_heading1('12. 总结与建议')

add_heading2('12.1 项目总结')
add_para(
    'MathLab 是一个设计精良、功能丰富的数学教育与科研桌面平台。'
    '其多智能体架构和 DAG 几何引擎体现了较高的技术水平，'
    '插件化架构为未来扩展提供了良好的基础。项目代码结构清晰，'
    '文档完善，测试体系初步建立，是一个成熟度较高的开源项目。'
)

add_heading2('12.2 优先改进项')
add_bullet('修复 ai_manager.py 中的 QThread 内存泄漏问题')
add_bullet('为 sandbox.py 添加异常处理，提高稳定性')
add_bullet('修正几何引擎中线段交点计算的边界判断')
add_bullet('补充核心模块的单元测试，目标覆盖率 ≥ 80%')
add_bullet('完善插件文档与示例，降低插件开发门槛')

add_heading2('12.3 发展建议')
add_bullet('持续优化多智能体协作效率，降低 LLM 调用成本')
add_bullet('加强移动端适配探索，拓展使用场景')
add_bullet('建设插件生态，鼓励第三方开发者贡献')
add_bullet('构建教学资源社区，形成内容护城河')

# ── 保存文件 ────────────────────────────────────────
output_path = '/workspace/MathLab_项目分析报告.docx'
doc.save(output_path)
print(f'文档已生成: {output_path}')
