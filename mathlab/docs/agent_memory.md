# 文件式记忆系统（Agent Memory）

> 对应模块：`mathlab/core/agent_memory.py`
> 设计范式：与 Codex / Claude Code 一致 —— **记忆就是磁盘上的 Markdown 文件**，
> 用户可以直接用编辑器改，AI 也可以自己写，不依赖数据库或向量库。

## 1. 目录布局

每个作用域一份，结构相同：

```
<root>/
├── MEMORY.md          # 长期记忆：策展后的稳定事实（用户偏好 / 项目约定 / 术语口径）
├── 2026-10-25.md      # 每日日志：append-only，只追加不覆盖
└── archive/           # 蒸馏后归档的历史日志
```

| 作用域 | 默认根目录 | 用途 |
| :--- | :--- | :--- |
| `project` | `mathlab/data/memory/` | 随工程走的项目级记忆 |
| `user` | `~/.mathlab/memory/` | 跨项目共享的用户级记忆 |

`project` 根目录可用环境变量 `MATHLAB_MEMORY_DIR` 覆盖（测试与便携化部署用）。
打包安装后 `mathlab/data/` 可能只读，此时写入自动降级到 `user` 作用域并记一条 warning。

## 2. 两条硬性约束

1. **读取零副作用** —— 目录/文件不存在时一律返回空字符串，读路径绝不创建文件。
   因此把它挂到 AI 主链路上不会在用户磁盘上留下垃圾。
2. **写入失败不阻断** —— 所有写操作 `try/except OSError` 后只记日志；
   `AIManager.ask` 与 `BaseMathAgent.solve_problem` 的注入点还额外包了一层
   `except Exception`，记忆层抛异常也不会打断对话或推理闭环。

## 3. 注入链路

```
AIManager.ask()              范式 A（Function Calling / 聊天）
  └─ FileMemorySystem.get_context_block()
BaseMathAgent.solve_problem()  范式 B（Agent 代码生成）
  └─ FileMemorySystem.get_context_block()
```

`get_context_block()` 按优先级拼装，**超出字符预算时从低优先级开始丢弃**：

| 优先级 | 内容 | 来源 |
| :--- | :--- | :--- |
| 1 | 项目指令 | 从工作目录向上最多 6 层查找 `AGENTS.md` / `MATHLAB.md`（Codex 同款），超长截断到 6000 字符 |
| 2 | 长期记忆 | 项目级 `MEMORY.md`，为空时回退用户级 |
| 3 | 近期日志 | 最近 2 天的 `YYYY-MM-DD.md` |

默认预算 3000 字符（`max_context_chars`）。

## 4. 使用方式

### 聊天指令

| 指令 | 作用 |
| :--- | :--- |
| `/remember <内容>` | 写入长期记忆 `MEMORY.md` |
| `/forget <关键词>` | 删除长期记忆中含关键词的条目 |
| `/log <内容>` | 追加一行到当日日志 |
| `/memory` | 展示记忆概况（根目录 / 文件数 / 长期记忆全文） |
| `/memory distill` | 把超过保留期的日志蒸馏进 `MEMORY.md` 并归档原文件 |
| `/memory clear confirm` | 清空全部记忆（需二次确认） |

### AI 主动写入：Function Calling 工具 `save_memory`

```json
{
  "fact": "用户偏好 SymPy 精确解而非数值近似",
  "target": "curated",   // curated=MEMORY.md（默认） | daily=当日日志
  "scope": "project"     // project（默认） | user
}
```

已注册进 `mathlab/core/ai_tools.py::AVAILABLE_TOOLS`，参数校验在
`_validate_save_memory`（`fact` 非空且 ≤500 字符，`target` / `scope` 走枚举白名单）。
UI 侧由 `AIToolsPanel._handle_save_memory` 落地执行。

### Python API

```python
from mathlab.core.agent_memory import get_file_memory

memory = get_file_memory()      # 进程级单例
memory.remember("用户偏好 SymPy 精确解")
memory.append_daily("完成一次几何推导")
memory.forget("SymPy")
memory.distill()                # 归档过期日志
memory.get_context_block()      # 注入 prompt 的 Markdown
memory.snapshot()               # UI 展示用的概况
```

## 5. 开关与调参

| 项 | 位置 | 默认 |
| :--- | :--- | :--- |
| 总开关 | `config_manager._DEFAULT_CONFIG["enable_file_memory"]` | `True`（关闭后不读不写） |
| 长期记忆上限 | `FileMemorySystem.max_curated_chars` | 4000 字符（超出丢弃最旧条目） |
| 上下文预算 | `FileMemorySystem.max_context_chars` | 3000 字符 |
| 日志保留期 | `FileMemorySystem.daily_retention_days` | 30 天 |

## 6. 测试

`mathlab/tests/unit/test_agent_memory.py`（31 条，`@pytest.mark.unit`）：

- 长期记忆读写、去重、空白拒绝、字符上限裁剪、遗忘、双作用域隔离
- 日志创建/追加/排序/缺失读取
- 读取零副作用、上下文装配与预算裁剪、优先级丢弃、`AGENTS.md` 向上查找、关闭态惰性
- 蒸馏归档、清空、概况统计
- 单例稳定性、`save_memory` 参数校验
- `AIManager.ask` 实际把记忆注入了 `system` 消息；记忆层抛异常时对话不受影响

全部用例使用 `tmp_path` 隔离根目录，不触碰真实记忆目录。
