# filepath: mathlab/core/ai_tools.py
import ast
import json

try:
    from mathlab.core.jupyter_manager import get_jupyter_sandbox
except ImportError:
    get_jupyter_sandbox = None

try:
    from mathlab.utils.logger import get_logger

    logger = get_logger(__name__)
except ImportError:
    import logging

    logger = logging.getLogger(__name__)

# ============================================================
#  沙箱画板桥接 (Geometry Canvas Bridge)
#  在 Jupyter 沙箱中注入下列函数，使 Agent 生成的代码能直接
#  调用 draw_point / draw_segment / draw_circle 等 API，
#  在交互几何画板上作图。所有命令收集到 __gbcmds 列表，
#  执行结束后由 execute_math_task 提取并传回 UI 层执行。
# ============================================================
_GEOM_BRIDGE_INJECT = r"""
# === Injected Geometry Canvas Bridge ===
__gbcmds = []

def draw_point(x, y, name=None):
    '''在画板上绘制一个点，返回命令字典。'''
    cmd = {"action": "add_point", "x": float(x), "y": float(y)}
    if name is not None:
        cmd["name"] = str(name)
    __gbcmds.append(cmd)
    return cmd

def draw_segment(p1, p2):
    '''用两点的坐标或 draw_point 返回值绘制线段。'''
    x1, y1 = _extract_xy(p1)
    x2, y2 = _extract_xy(p2)
    cmd = {"action": "add_segment_auto", "x1": x1, "y1": y1, "x2": x2, "y2": y2}
    __gbcmds.append(cmd)
    return cmd

def draw_circle(cx, cy, r):
    '''以 (cx,cy) 为圆心、r 为半径画圆。'''
    cmd = {"action": "add_circle_auto", "cx": float(cx), "cy": float(cy), "r": float(r)}
    __gbcmds.append(cmd)
    return cmd

def draw_line(x1, y1, x2, y2):
    '''过两点画一条无限直线（区别于线段）。'''
    cmd = {"action": "add_line_auto", "x1": float(x1), "y1": float(y1), "x2": float(x2), "y2": float(y2)}
    __gbcmds.append(cmd)
    return cmd

def draw_ellipse(cx, cy, rx, ry):
    '''以 (cx,cy) 为中心, rx/ry 为半轴画椭圆。'''
    cmd = {"action": "add_ellipse_auto", "cx": float(cx), "cy": float(cy), "rx": float(rx), "ry": float(ry)}
    __gbcmds.append(cmd)
    return cmd

def draw_polygon(points):
    '''用坐标列表 [(x1,y1),(x2,y2),...] 画多边形。'''
    pts = [(float(p[0]), float(p[1])) for p in points]
    cmd = {"action": "add_polygon_auto", "coords": pts}
    __gbcmds.append(cmd)
    return cmd

def clear_canvas():
    '''清空当前画板。'''
    __gbcmds.append({"action": "clear"})

def _extract_xy(pt):
    if isinstance(pt, dict) and "x" in pt:
        return float(pt["x"]), float(pt["y"])
    return float(pt[0]), float(pt[1])

# 与文档 API 保持一致的别名
add_point = draw_point
add_segment = draw_segment
add_circle = draw_circle
add_line = draw_line
add_ellipse = draw_ellipse
add_polygon = draw_polygon
"""

# 几何画板操控工具的说明书
GEOMETRY_DRAW_TOOL = {
    "type": "function",
    "function": {
        "name": "execute_geometry_draw",
        "description": "当用户在聊天中明确要求【画图、绘制、添加】某种几何图形时，调用此函数在用户的画板上执行绘制操作。注意：如果没有给定坐标，请利用几何常识合理分配数值，使其居中且美观。add_point 必须带 x,y；add_circle 必须带 center 和 radius；add_segment 必须带 p1,p2",
        "parameters": {
            "type": "object",
            "properties": {
                "commands": {
                    "type": "array",
                    "description": "需要按顺序执行的绘图指令数组",
                    "items": {
                        "type": "object",
                        "properties": {
                            "cmd": {
                                "type": "string",
                                "enum": [
                                    "add_point",
                                    "add_circle",
                                    "add_polygon",
                                    "add_segment",
                                ],
                                "description": "操作类型",
                            },
                            "x": {"type": "number", "description": "点的 X 坐标"},
                            "y": {"type": "number", "description": "点的 Y 坐标"},
                            "name": {
                                "type": "string",
                                "description": "图形的字母标签，如 'A', 'B'",
                            },
                            "radius": {"type": "number", "description": "圆的半径"},
                            "center": {
                                "type": "string",
                                "description": "圆心点的名称引用，如 'A'",
                            },
                            "points": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "多边形顶点的名称列表，如 ['A', 'B', 'C']",
                            },
                            "p1": {"type": "string", "description": "线段起点名称"},
                            "p2": {"type": "string", "description": "线段终点名称"},
                        },
                        "required": ["cmd"],
                    },
                }
            },
            "required": ["commands"],
        },
    },
}

VISUAL_HIGHLIGHT_TOOL = {
    "type": "function",
    "function": {
        "name": "highlight_geometry_elements",
        "description": "苏格拉底教学专用工具：当你想引导用户关注画板上的特定图形（点、线、多边形）时，调用此工具让它们在画板上高亮闪烁，充当你的激光笔。",
        "parameters": {
            "type": "object",
            "properties": {
                "element_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "需要高亮的图形名称列表，例如 ['A', 'B', 'AB', 'Triangle_ABC']",
                },
                "color": {
                    "type": "string",
                    "enum": ["red", "blue", "green", "orange"],
                    "description": "高亮的颜色。如果是警告/纠错用红色，启发思考用橙色或蓝色",
                },
                "reason": {
                    "type": "string",
                    "description": "为什么要高亮这些元素（后台记录，不在 UI 显示）",
                },
            },
            "required": ["element_names", "color"],
        },
    },
}

QUIZ_GENERATOR_SCHEMA = {
    "type": "function",
    "function": {
        "name": "generate_math_quiz",
        "description": "根据当前的知识点或用户的画布状态，生成一道针对性的数学测试题。",
        "parameters": {
            "type": "object",
            "properties": {
                "knowledge_point": {
                    "type": "string",
                    "description": "本题考查的核心知识点，如 '勾股定理' 或 '导数极值'",
                },
                "question_text": {
                    "type": "string",
                    "description": "题目正文，支持 LaTeX 公式（用 $$ 包裹）",
                },
                "question_type": {
                    "type": "string",
                    "enum": ["multiple_choice", "fill_in_blank"],
                    "description": "题目类型：选择题 或 填空题",
                },
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "如果是选择题，提供4个选项数组；如果是填空题，此项传空数组",
                },
                "correct_answer": {
                    "type": "string",
                    "description": "标准答案（如 'A' 或具体的计算数值）",
                },
                "explanation": {
                    "type": "string",
                    "description": "详细的解题思路和步骤",
                },
            },
            "required": [
                "knowledge_point",
                "question_text",
                "question_type",
                "correct_answer",
                "explanation",
            ],
        },
    },
}

AGENT_TRANSFER_TOOL = {
    "type": "function",
    "function": {
        "name": "transfer_to_agent",
        "description": "【核心调度工具】当用户的请求超出了你的专长，或者需要跨部门协作时（例如：你需要画图但没有画笔，你需要出题但你不是考官），必须调用此工具将任务移交给最合适的专家。",
        "parameters": {
            "type": "object",
            "properties": {
                "target_agent": {
                    "type": "string",
                    "enum": ["planner", "general", "geometry", "quiz", "dataviz"],
                    "description": "接手任务的目标专家 ID",
                },
                "handover_notes": {
                    "type": "string",
                    "description": "内部交接说明。请向下一个专家详细描述：当前的上下文是什么？你需要他具体执行什么操作？",
                },
            },
            "required": ["target_agent", "handover_notes"],
        },
    },
}


SUBMIT_TEACHING_PLAN_TOOL = {
    "type": "function",
    "function": {
        "name": "submit_teaching_plan",
        "description": "【教研组长专用】分析用户的数学问题与画布状态，将其拆解为3-5个由浅入深、循序渐进的教学大纲步骤。禁止直接给出最终答案。",
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "本次课题的总主题，如'探索圆锥曲线的切线性质'",
                },
                "steps": {
                    "type": "array",
                    "description": "大纲步骤列表",
                    "items": {
                        "type": "object",
                        "properties": {
                            "num": {
                                "type": "integer",
                                "description": "步骤序号 (1, 2, 3...)",
                            },
                            "title": {
                                "type": "string",
                                "description": "本步骤的核心探讨点（如：观察直角边、添加直径辅助线、应用相似三角形定理）",
                            },
                            "hint_for_teacher": {
                                "type": "string",
                                "description": "给授课老师的后台提示，指导该步骤如何教学",
                            },
                        },
                        "required": ["num", "title", "hint_for_teacher"],
                    },
                },
            },
            "required": ["topic", "steps"],
        },
    },
}

SAVE_MEMORY_TOOL = {
    "type": "function",
    "function": {
        "name": "save_memory",
        "description": (
            "把【跨会话稳定】的事实写入文件式记忆系统（Markdown 文件，用户可直接在编辑器里改）。"
            "适合记录：用户偏好、项目约定、术语口径、反复踩过的坑。"
            "不适合记录：一次性的中间过程（那类信息请用 target='daily' 写进当日日志）。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "fact": {
                    "type": "string",
                    "description": "要记住的一句话事实，例如「用户习惯用 SymPy 而非数值近似解根」",
                },
                "target": {
                    "type": "string",
                    "enum": ["curated", "daily"],
                    "description": "curated=写入长期记忆 MEMORY.md（默认）；daily=写入当日日志 YYYY-MM-DD.md",
                },
                "scope": {
                    "type": "string",
                    "enum": ["project", "user"],
                    "description": "project=项目级记忆（默认）；user=跨项目共享的用户级记忆",
                },
            },
            "required": ["fact"],
        },
    },
}

AVAILABLE_TOOLS = [
    GEOMETRY_DRAW_TOOL,
    VISUAL_HIGHLIGHT_TOOL,
    QUIZ_GENERATOR_SCHEMA,
    AGENT_TRANSFER_TOOL,
    SUBMIT_TEACHING_PLAN_TOOL,
    SAVE_MEMORY_TOOL,
]


# ============================================================
#  工具参数校验层 (Tool Parameter Validation)
#  在工具执行前验证参数类型和边界，防止无效输入导致崩溃
# ============================================================

_VALID_CMD_TYPES = {"add_point", "add_circle", "add_polygon", "add_segment"}
_VALID_HIGHLIGHT_COLORS = {"red", "blue", "green", "orange"}
_VALID_QUIZ_TYPES = {"multiple_choice", "fill_in_blank"}
_VALID_AGENT_IDS = {"planner", "general", "geometry", "quiz", "dataviz"}

_MAX_COMMANDS = 200
_MAX_ELEMENT_NAMES = 50
_MAX_QUIZ_OPTIONS = 6
_MAX_TEACHING_STEPS = 10
_MAX_MEMORY_FACT_CHARS = 500
_VALID_MEMORY_TARGETS = {"curated", "daily"}
_VALID_MEMORY_SCOPES = {"project", "user"}


def validate_tool_call(tool_name: str, args_dict: dict):
    """校验工具调用参数的类型和边界。

    Args:
        tool_name: 工具函数名称。
        args_dict: AI 返回的参数字典。

    Returns:
        (is_valid, error_msg) 元组。校验通过时 error_msg 为空字符串。
    """
    if not isinstance(args_dict, dict):
        return False, f"参数必须是字典类型，收到 {type(args_dict).__name__}"

    if tool_name == "execute_geometry_draw":
        return _validate_geometry_draw(args_dict)
    elif tool_name == "highlight_geometry_elements":
        return _validate_highlight(args_dict)
    elif tool_name == "generate_math_quiz":
        return _validate_quiz(args_dict)
    elif tool_name == "transfer_to_agent":
        return _validate_transfer(args_dict)
    elif tool_name == "submit_teaching_plan":
        return _validate_teaching_plan(args_dict)
    elif tool_name == "speak_at_location":
        return _validate_speak(args_dict)
    elif tool_name == "save_memory":
        return _validate_save_memory(args_dict)
    else:
        # 未知工具不阻断，仅记录警告
        logger.warning(f"未知工具名称: {tool_name}，跳过校验")
        return True, ""


def _validate_geometry_draw(args: dict):
    commands = args.get("commands")
    if not isinstance(commands, list):
        return False, "execute_geometry_draw: 'commands' 必须是数组"
    if not commands and "cmd" in args:
        commands = [args]
    if not commands:
        return False, "execute_geometry_draw: 'commands' 不能为空"
    if len(commands) > _MAX_COMMANDS:
        return (
            False,
            f"execute_geometry_draw: 命令数量超限 ({len(commands)} > {_MAX_COMMANDS})",
        )

    for i, cmd in enumerate(commands):
        if not isinstance(cmd, dict):
            return False, f"execute_geometry_draw: 第 {i+1} 条命令必须是对象"
        cmd_type = cmd.get("cmd")
        if cmd_type not in _VALID_CMD_TYPES:
            return (
                False,
                f"execute_geometry_draw: 第 {i+1} 条命令的 cmd='{cmd_type}' 无效，允许值: {_VALID_CMD_TYPES}",
            )

        if cmd_type == "add_point":
            if not _is_number(cmd.get("x")) or not _is_number(cmd.get("y")):
                return (
                    False,
                    f"execute_geometry_draw: 第 {i+1} 条 add_point 缺少有效的 x/y 坐标",
                )
        elif cmd_type == "add_circle":
            if not cmd.get("center") or not _is_number(cmd.get("radius")):
                return (
                    False,
                    f"execute_geometry_draw: 第 {i+1} 条 add_circle 缺少 center 或 radius",
                )
            if float(cmd["radius"]) <= 0:
                return (
                    False,
                    f"execute_geometry_draw: 第 {i+1} 条 add_circle 的 radius 必须为正数",
                )
        elif cmd_type == "add_polygon":
            pts = cmd.get("points")
            if not isinstance(pts, list) or len(pts) < 3:
                return (
                    False,
                    f"execute_geometry_draw: 第 {i+1} 条 add_polygon 的 points 至少需要 3 个顶点",
                )
        elif cmd_type == "add_segment":
            if not cmd.get("p1") or not cmd.get("p2"):
                return (
                    False,
                    f"execute_geometry_draw: 第 {i+1} 条 add_segment 缺少 p1 或 p2",
                )

    return True, ""


def _validate_highlight(args: dict):
    element_names = args.get("element_names")
    if not isinstance(element_names, list) or not element_names:
        return False, "highlight_geometry_elements: 'element_names' 必须是非空数组"
    if len(element_names) > _MAX_ELEMENT_NAMES:
        return (
            False,
            f"highlight_geometry_elements: 元素数量超限 ({len(element_names)} > {_MAX_ELEMENT_NAMES})",
        )
    color = args.get("color", "orange")
    if color not in _VALID_HIGHLIGHT_COLORS:
        return (
            False,
            f"highlight_geometry_elements: color='{color}' 无效，允许值: {_VALID_HIGHLIGHT_COLORS}",
        )
    return True, ""


def _validate_quiz(args: dict):
    required = [
        "knowledge_point",
        "question_text",
        "question_type",
        "correct_answer",
        "explanation",
    ]
    for field in required:
        val = args.get(field)
        if not val or not isinstance(val, str):
            return False, f"generate_math_quiz: 缺少必填字段 '{field}' 或类型非字符串"

    qt = args.get("question_type")
    if qt not in _VALID_QUIZ_TYPES:
        return (
            False,
            f"generate_math_quiz: question_type='{qt}' 无效，允许值: {_VALID_QUIZ_TYPES}",
        )

    options = args.get("options", [])
    if not isinstance(options, list):
        return False, "generate_math_quiz: 'options' 必须是数组"
    if qt == "multiple_choice" and len(options) > _MAX_QUIZ_OPTIONS:
        return (
            False,
            f"generate_math_quiz: 选项数量超限 ({len(options)} > {_MAX_QUIZ_OPTIONS})",
        )

    return True, ""


def _validate_transfer(args: dict):
    target = args.get("target_agent")
    if not target or not isinstance(target, str):
        return False, "transfer_to_agent: 'target_agent' 必须是非空字符串"
    if target not in _VALID_AGENT_IDS:
        return (
            False,
            f"transfer_to_agent: target_agent='{target}' 无效，允许值: {_VALID_AGENT_IDS}",
        )
    notes = args.get("handover_notes")
    if not notes or not isinstance(notes, str):
        return False, "transfer_to_agent: 'handover_notes' 必须是非空字符串"
    return True, ""


def _validate_teaching_plan(args: dict):
    topic = args.get("topic")
    if not topic or not isinstance(topic, str):
        return False, "submit_teaching_plan: 'topic' 必须是非空字符串"
    steps = args.get("steps")
    if not isinstance(steps, list) or not steps:
        return False, "submit_teaching_plan: 'steps' 必须是非空数组"
    if len(steps) > _MAX_TEACHING_STEPS:
        return (
            False,
            f"submit_teaching_plan: 步骤数量超限 ({len(steps)} > {_MAX_TEACHING_STEPS})",
        )
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            return False, f"submit_teaching_plan: 第 {i+1} 步必须是对象"
        if not isinstance(step.get("num"), int) or step["num"] < 1:
            return False, f"submit_teaching_plan: 第 {i+1} 步的 num 必须是正整数"
        if not step.get("title") or not isinstance(step["title"], str):
            return False, f"submit_teaching_plan: 第 {i+1} 步缺少 title"
    return True, ""


def _validate_speak(args: dict):
    target = args.get("target_element")
    if not target or not isinstance(target, str):
        return False, "speak_at_location: 'target_element' 必须是非空字符串"
    text = args.get("text")
    if not text or not isinstance(text, str):
        return False, "speak_at_location: 'text' 必须是非空字符串"
    if len(text) > 200:
        return False, f"speak_at_location: 'text' 过长 ({len(text)} > 200 字符)"
    return True, ""


def _validate_save_memory(args: dict):
    fact = args.get("fact")
    if not isinstance(fact, str) or not fact.strip():
        return False, "save_memory: 'fact' 必须是非空字符串"
    if len(fact) > _MAX_MEMORY_FACT_CHARS:
        return False, f"save_memory: 'fact' 过长 ({len(fact)} > {_MAX_MEMORY_FACT_CHARS} 字符)"
    target = args.get("target", "curated")
    if target not in _VALID_MEMORY_TARGETS:
        return False, f"save_memory: 'target' 无效，允许值: {_VALID_MEMORY_TARGETS}"
    scope = args.get("scope", "project")
    if scope not in _VALID_MEMORY_SCOPES:
        return False, f"save_memory: 'scope' 无效，允许值: {_VALID_MEMORY_SCOPES}"
    return True, ""


def _is_number(val) -> bool:
    """检查值是否为 int/float（排除 bool）。"""
    return isinstance(val, (int, float)) and not isinstance(val, bool)


def execute_math_task(code_snippet: str):
    """
    供 AI Agent 调用的沙箱执行入口。
    自动注入几何画板桥接函数（draw_point/section/circle 等），
    并把 Agent 代码中累积的绘图命令随返回值一起传出。
    """
    # 将画板桥接函数注入到用户代码中
    wrapped_code = _GEOM_BRIDGE_INJECT + "\n" + code_snippet + "\n" + "print('__GEOBRIDGE_CMDS__' + repr(__gbcmds))"
    result = get_jupyter_sandbox().execute_code(wrapped_code)

    # 从输出中分离绘图命令
    output_text = result.get("text", "")
    geom_commands = []
    _MARKER = "__GEOBRIDGE_CMDS__"
    if _MARKER in output_text:
        idx = output_text.index(_MARKER)
        cmds_str = output_text[idx + len(_MARKER) :].strip()
        output_text = output_text[:idx].rstrip()
        result["text"] = output_text
        try:
            # BUG 4 修复：使用 ast.literal_eval 替代 eval，只允许字面量解析
            geom_commands = ast.literal_eval(cmds_str)
        except (ValueError, SyntaxError) as e:
            # SUGGESTION 14：添加错误日志
            logger.warning(f"解析几何命令失败: {cmds_str[:200]} - {e}")

    tb = result.get("traceback") or []
    error_text = "\n".join(tb) if isinstance(tb, list) else str(tb)
    return json.dumps(
        {
            "status": result.get("status"),
            "output": output_text,
            "error": error_text if result.get("status") == "error" else None,
            "geom_commands": geom_commands,
        }
    )
