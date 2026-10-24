# ai_manager 拆分契约

> 背景：`mathlab/core/ai_manager.py` 一度膨胀到 1664 行，`PlannerAgent.solve_problem`
> 圈复杂度 59、`BaseMathAgent.solve_problem` 36，是全仓最难改的两块。
> 本文记录拆分后的模块边界与**必须保留的兼容约定**，改之前先读。

## 1. 模块边界

| 模块 | 职责 | 关键导出 |
| :--- | :--- | :--- |
| `core/ai_engine_worker.py` | **Qt / OpenAI 兼容层的唯一真源** + Function Calling 流式线程 | `QObject` `QThread` `Signal` `QT_AVAILABLE`、openai 异常类与 `OPENAI_AVAILABLE` / `OpenAI`、`describe_api_error`、`AIState`、`AIEngineWorker` |
| `core/planner_agent.py` | 教研组长（拆题 → 委派 → 汇总 → 质量评估） | `PlannerAgent`、`StepResultCollector` |
| `core/ai_manager.py` | 客户端与统计方法、缓存、资源限制、Agent 基类与两个薄壳子类 | `AIManager`、`ReasoningCache`、`ResourceConfig`、`SolveCallbacks`、`BaseMathAgent`、`GeometryAgent`、`DataVizAgent` |

依赖方向（**单向，不得反向**）：

```
planner_agent ──▶ ai_manager ──▶ ai_engine_worker
```

## 2. 兼容约定（改动前必读）

### 2.1 `ai_manager` 的 re-export

历史代码与测试从 `ai_manager` 取这些名字，全部通过 `__all__` 保留：

```python
from mathlab.core.ai_manager import AIState, AIEngineWorker, describe_api_error
from mathlab.core.ai_manager import OpenAI, QObject, QThread, Signal
from mathlab.core.ai_manager import OPENAI_AVAILABLE, QT_AVAILABLE
from mathlab.core.ai_manager import APIConnectionError, APIStatusError, APITimeoutError
from mathlab.core.ai_manager import AuthenticationError, RateLimitError
```

新增依赖请直接 `from mathlab.core.ai_engine_worker import ...`，不要再从 `ai_manager` 绕。

### 2.2 `PlannerAgent` 走 PEP 562 延迟转发

`planner_agent` 在**顶层** import `ai_manager`（取 `BaseMathAgent` / `ResourceConfig`），
所以 `ai_manager` **不能**在顶层反向 import `PlannerAgent`，否则成环。
解决办法是 `ai_manager.__getattr__`：

```python
# 仍然可用，但解析被推迟到首次访问时
from mathlab.core.ai_manager import PlannerAgent
```

新代码请直接 `from mathlab.core.planner_agent import PlannerAgent`。
**不要**把 `PlannerAgent` 加进 `ai_manager` 的顶层 import —— 会立刻引发循环导入。

## 3. solve_problem 的策略化结构

### 3.1 `BaseMathAgent`（cx 36 → 7）

```
solve_problem                      编排：校验 → 缓存 → 装配 → 重试循环
├─ _replay_cached_result           缓存命中时回放（四个回调各喂一遍）
├─ _build_initial_messages          系统提示 + 用户任务
│  ├─ _build_skill_context          RAG：本地技能库检索
│  ├─ _build_adaptive_context       自适应教学策略（学生模型）
│  ├─ _build_pedagogical_context    教学法约束（Bloom/ZPD/UDL/Socratic）
│  └─ _build_memory_context         文件式记忆（故障降级为空串）
├─ _execute_code                    沙箱执行，异常收敛成 {"status": "error"}
├─ _finalize_success                回传几何命令 + 后台提炼 + 写缓存 + 记互动
└─ _append_failure_feedback         报错回灌 + 历史裁剪（MAX_HISTORY_MSGS=8）
```

回调统一收进 `SolveCallbacks`（`thought` / `code` / `finish` / `geom`），
内部做 None 检查，主流程不再散落 `if on_xxx_cb:`。

### 3.2 `PlannerAgent`（cx 59 → 各环节 ≤11）

```
solve_problem                      编排：校验 → 拆解 → 调度 → 汇总
├─ _announce_start                 会话 ID + 总线广播
├─ _emit_student_profile           学生认知画像推送
├─ _emit_plan                      输出教学大纲
├─ _split_steps_by_mode            按 parallelizable 分并行/串行组
├─ _dispatch_steps                 先并行后串行，聚合 codes / geom
│  ├─ _run_parallel_steps          线程池并发，结果按 num 排序
│  └─ _run_step                    单步骤执行
│     ├─ _build_step_prompt        拼子提示 + Bloom 层级约束
│     ├─ _pick_sub_agent           按注册表描述动态路由
│     ├─ _notify_step_dispatch     总线广播派发意图（NOTIFICATION）
│     ├─ _run_step_by_self         子 Agent 缺失时自行执行
│     └─ _run_step_by_agent        委派子 Agent + StepResultCollector
└─ _aggregate                      拼接代码 + 教学质量评估 + 统一结果
```

`StepResultCollector` 替代了原先的四个嵌套闭包工厂
（`make_sub_thought_cb` / `make_sub_code_cb` / `make_sub_finish_cb` / `make_sub_geom_cb`），
状态与回调绑在同一对象上，`as_tuple()` 导出 `(num, success, code, geom)`。

## 4. 行为保持不变的红线

改这块代码时，以下行为是历史缺陷修复的成果，**不得回退**：

1. **子任务只执行一遍**。`_notify_step_dispatch` 必须发 `MessageType.NOTIFICATION`，
   不能发 `TASK_REQUEST` —— 后者会被 `MessageRouter` 同步转成一次 `solve_problem`，
   与下面的直调叠加成双份执行（双份 token、重复回传）。回归用例见
   `mathlab/tests/unit/test_p1_ai_correctness.py::TestPlannerSingleExecution`。
2. **错误信息不得泄露部署细节**。`describe_api_error` 只回中文短句，
   完整异常（含 base_url、上游响应体、请求 id）只写日志。
3. **`_pick_sub_agent` 不许硬编码 Agent 名**（BUG 7），必须查 `registry.agents` 的描述。
4. **对话历史必须裁剪**（BUG 6），`MAX_HISTORY_MSGS = 8`。

## 5. 测试

`mathlab/tests/unit/test_ai_refactor.py`（37 条，`@pytest.mark.unit`）：

- 兼容层 re-export 与 `__getattr__` 延迟转发（含 AttributeError 路径）
- tool_calls 分片聚合、JSON 解析与坏 JSON 容错、usage 上报、取消中断、状态切换
- `SolveCallbacks` / `StepResultCollector` 的 None 安全与转发语义
- Planner：并行分组、子 Agent 路由（可视化关键词 / 几何 / 跳过自身）、拆题降级与兜底大纲拷贝、
  未配置 Key 早退、空大纲回退基类、子 Agent 缺失自行执行、委派只调一次
- BaseMathAgent：未配置 Key 早退、缓存回放、沙箱异常收敛、历史裁剪、提示装配

另有既有用例 `test_p1_ai_correctness.py` 覆盖"子任务只执行一遍"与错误脱敏。
