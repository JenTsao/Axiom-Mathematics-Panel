"""文件式记忆系统（core/agent_memory.py）单元测试。

覆盖：长期记忆读写与去重、字符上限、日志追加、遗忘、上下文装配与预算裁剪、
项目指令发现、蒸馏归档、关闭态行为，以及 AI 主链路的注入。
"""

from datetime import date, timedelta

import pytest

from mathlab.core.agent_memory import (
    CURATED_FILENAME,
    FileMemorySystem,
    MemoryScope,
    get_file_memory,
    reset_file_memory,
)
from mathlab.core.ai_tools import validate_tool_call


@pytest.fixture
def memory(tmp_path):
    """隔离到临时目录的记忆系统实例（项目级与用户级各自独立）。"""
    return FileMemorySystem(
        project_root=str(tmp_path / "project"),
        user_root=str(tmp_path / "user"),
        project_dir=str(tmp_path),
        enabled=True,
    )


class TestCuratedMemory:
    """长期记忆 MEMORY.md。"""

    @pytest.mark.unit
    def test_remember_writes_entry(self, memory, tmp_path):
        assert memory.remember("用户偏好 SymPy 精确解")

        path = tmp_path / "project" / CURATED_FILENAME
        assert path.is_file()
        content = path.read_text(encoding="utf-8")
        assert "用户偏好 SymPy 精确解" in content
        assert date.today().isoformat() in content

    @pytest.mark.unit
    def test_remember_dedupes(self, memory):
        assert memory.remember("同一条事实")
        assert not memory.remember("同一条事实")

    @pytest.mark.unit
    def test_remember_rejects_blank(self, memory):
        assert not memory.remember("")
        assert not memory.remember("   ")

    @pytest.mark.unit
    def test_curated_cap_drops_oldest(self, tmp_path):
        capped = FileMemorySystem(
            project_root=str(tmp_path / "project"),
            user_root=str(tmp_path / "user"),
            project_dir=str(tmp_path),
            max_curated_chars=260,
        )
        for i in range(12):
            capped.remember(f"第 {i} 条足够长的事实内容用于触发上限裁剪")

        content = capped.read_curated()
        assert len(content) <= 260
        assert "第 11 条" in content
        assert "第 0 条" not in content

    @pytest.mark.unit
    def test_forget_removes_matching_entries(self, memory):
        memory.remember("关于三角形的约定")
        memory.remember("关于圆形的约定")

        assert memory.forget("三角形") == 1
        assert "三角形" not in memory.read_curated()
        assert "圆形" in memory.read_curated()

    @pytest.mark.unit
    def test_forget_no_match_returns_zero(self, memory):
        memory.remember("某条事实")
        assert memory.forget("不存在的关键词") == 0

    @pytest.mark.unit
    def test_user_scope_is_independent(self, memory, tmp_path):
        memory.remember("项目级事实", scope=MemoryScope.PROJECT.value)
        memory.remember("用户级事实", scope=MemoryScope.USER.value)

        assert "项目级事实" in memory.read_curated(MemoryScope.PROJECT.value)
        assert "项目级事实" not in memory.read_curated(MemoryScope.USER.value)
        assert (tmp_path / "user" / CURATED_FILENAME).is_file()


class TestDailyLog:
    """每日日志 YYYY-MM-DD.md。"""

    @pytest.mark.unit
    def test_append_daily_creates_file(self, memory, tmp_path):
        assert memory.append_daily("完成一次几何推导")

        log_path = tmp_path / "project" / f"{date.today().isoformat()}.md"
        assert log_path.is_file()
        assert "完成一次几何推导" in log_path.read_text(encoding="utf-8")

    @pytest.mark.unit
    def test_append_daily_appends(self, memory):
        memory.append_daily("第一条")
        memory.append_daily("第二条")

        today = memory.read_daily(date.today())
        assert "第一条" in today
        assert "第二条" in today

    @pytest.mark.unit
    def test_list_daily_files_sorted(self, memory):
        old = date.today() - timedelta(days=3)
        memory.append_daily("旧日志", day=old)
        memory.append_daily("新日志")

        names = memory.list_daily_files()
        assert names == sorted(names)
        assert len(names) == 2

    @pytest.mark.unit
    def test_read_daily_missing_returns_empty(self, memory):
        assert memory.read_daily(date(1999, 1, 1)) == ""


class TestContextAssembly:
    """上下文装配与预算裁剪。"""

    @pytest.mark.unit
    def test_read_has_no_side_effect(self, memory, tmp_path):
        assert memory.get_context_block() == ""
        assert not (tmp_path / "project").exists()
        assert not (tmp_path / "user").exists()

    @pytest.mark.unit
    def test_context_contains_curated_and_log(self, memory, tmp_path):
        (tmp_path / "AGENTS.md").write_text("# 项目约定\n请优先使用 SymPy。", encoding="utf-8")
        memory.remember("长期事实 A")
        memory.append_daily("昨天的日志", day=date.today() - timedelta(days=1))

        block = memory.get_context_block()
        assert "长期事实 A" in block
        assert "昨天的日志" in block
        assert "项目约定" in block

    @pytest.mark.unit
    def test_context_respects_budget(self, memory):
        memory.remember("事实 " + "长" * 200)
        memory.append_daily("日志 " + "长" * 200)

        block = memory.get_context_block(max_chars=120)
        assert len(block) <= 200  # 允许标题与截断提示的少量溢出

    @pytest.mark.unit
    def test_context_priority_drops_logs_first(self, memory):
        memory.remember("重要事实")
        memory.append_daily("次要日志 " + "长" * 300)

        block = memory.get_context_block(max_chars=80)
        assert "重要事实" in block
        assert "次要日志" not in block

    @pytest.mark.unit
    def test_context_falls_back_to_user_scope(self, memory):
        memory.remember("用户级长期事实", scope=MemoryScope.USER.value)
        block = memory.get_context_block()
        assert "用户级长期事实" in block

    @pytest.mark.unit
    def test_project_instructions_lookup_walks_up(self, memory, tmp_path):
        nested = tmp_path / "a" / "b"
        nested.mkdir(parents=True)
        (tmp_path / "AGENTS.md").write_text("顶层项目指令", encoding="utf-8")

        assert "顶层项目指令" in memory.load_project_instructions(project_dir=str(nested))

    @pytest.mark.unit
    def test_disabled_system_is_inert(self, tmp_path):
        off = FileMemorySystem(
            project_root=str(tmp_path / "project"),
            user_root=str(tmp_path / "user"),
            project_dir=str(tmp_path),
            enabled=False,
        )
        assert not off.remember("不该写入")
        assert not off.append_daily("不该写入")
        assert off.get_context_block() == ""
        assert not (tmp_path / "project").exists()


class TestMaintenance:
    """蒸馏归档与清空。"""

    @pytest.mark.unit
    def test_distill_archives_stale_logs(self, memory, tmp_path):
        stale = date.today() - timedelta(days=60)
        memory.append_daily("很早以前的日志", day=stale)
        memory.append_daily("今天的日志")

        archived = memory.distill()
        assert archived == [f"{stale.isoformat()}.md"]
        assert not (tmp_path / "project" / f"{stale.isoformat()}.md").exists()
        assert (tmp_path / "project" / "archive" / f"{stale.isoformat()}.md").is_file()
        assert f"{stale.isoformat()}.md" in memory.read_curated()

    @pytest.mark.unit
    def test_distill_keeps_recent_logs(self, memory):
        memory.append_daily("今天的日志")
        assert memory.distill() == []

    @pytest.mark.unit
    def test_clear_removes_files(self, memory):
        memory.remember("事实")
        memory.append_daily("日志")
        assert memory.clear() >= 2
        assert memory.read_curated() == ""

    @pytest.mark.unit
    def test_snapshot_reports_roots(self, memory, tmp_path):
        memory.remember("事实")
        snap = memory.snapshot()
        assert snap[MemoryScope.PROJECT.value]["root"] == str(tmp_path / "project")
        assert CURATED_FILENAME in snap[MemoryScope.PROJECT.value]["files"]


class TestSingleton:
    """进程级单例。"""

    @pytest.mark.unit
    def test_singleton_is_stable(self):
        reset_file_memory()
        try:
            assert get_file_memory() is get_file_memory()
        finally:
            reset_file_memory()

    @pytest.mark.unit
    def test_force_new_rebuilds(self):
        reset_file_memory()
        try:
            first = get_file_memory()
            assert get_file_memory(force_new=True) is not first
        finally:
            reset_file_memory()


class TestSaveMemoryTool:
    """save_memory 工具的参数校验。"""

    @pytest.mark.unit
    def test_valid_defaults(self):
        ok, msg = validate_tool_call("save_memory", {"fact": "用户偏好精确解"})
        assert ok, msg

    @pytest.mark.unit
    def test_rejects_empty_fact(self):
        ok, _ = validate_tool_call("save_memory", {"fact": "   "})
        assert not ok

    @pytest.mark.unit
    def test_rejects_unknown_target(self):
        ok, _ = validate_tool_call("save_memory", {"fact": "x", "target": "nope"})
        assert not ok

    @pytest.mark.unit
    def test_rejects_unknown_scope(self):
        ok, _ = validate_tool_call("save_memory", {"fact": "x", "scope": "nope"})
        assert not ok

    @pytest.mark.unit
    def test_rejects_overlong_fact(self):
        ok, _ = validate_tool_call("save_memory", {"fact": "x" * 501})
        assert not ok


class TestAIManagerInjection:
    """记忆是否真正进入 AI 请求。"""

    @pytest.mark.unit
    def test_ask_injects_memory_block(self, ai_manager, tmp_path, monkeypatch):
        from mathlab.core import ai_manager as ai_module

        fake_memory = FileMemorySystem(
            project_root=str(tmp_path / "project"),
            user_root=str(tmp_path / "user"),
            project_dir=str(tmp_path),
            enabled=True,
        )
        fake_memory.remember("用户偏好 SymPy 精确解")
        ai_manager.file_memory = fake_memory

        recorded = {}

        class _DummySignal:
            def connect(self, *_args, **_kwargs):
                return None

            def disconnect(self, *_args, **_kwargs):
                return None

        class _RecorderWorker:
            def __init__(self, client, model, messages, tools=None):
                recorded["messages"] = messages

            def isRunning(self):
                return False

            def cancel(self):
                return None

            def wait(self, *_args):
                return True

            def start(self):
                return None

            state_changed = _DummySignal()
            chunk_received = _DummySignal()
            tool_call_received = _DummySignal()
            usage_reported = _DummySignal()
            finished_text = _DummySignal()
            error_occurred = _DummySignal()

        monkeypatch.setattr(ai_module, "AIEngineWorker", _RecorderWorker)
        ai_manager.client = object()  # 绕过 "未配置 API Key" 的早退

        ai_manager.ask(user_prompt="解这个方程", system_prompt="你是数学助手。")

        system_message = recorded["messages"][0]
        assert system_message["role"] == "system"
        assert "用户偏好 SymPy 精确解" in system_message["content"]

    @pytest.mark.unit
    def test_ask_survives_memory_failure(self, ai_manager, monkeypatch):
        """记忆层抛异常时不得阻断对话。"""
        from mathlab.core import ai_manager as ai_module

        class _Boom:
            enabled = True

            def get_context_block(self, *args, **kwargs):
                raise RuntimeError("disk on fire")

        ai_manager.file_memory = _Boom()
        recorded = {}

        class _DummySignal:
            def connect(self, *_args, **_kwargs):
                return None

            def disconnect(self, *_args, **_kwargs):
                return None

        class _RecorderWorker:
            def __init__(self, client, model, messages, tools=None):
                recorded["messages"] = messages

            def isRunning(self):
                return False

            def cancel(self):
                return None

            def wait(self, *_args):
                return True

            def start(self):
                return None

            state_changed = _DummySignal()
            chunk_received = _DummySignal()
            tool_call_received = _DummySignal()
            usage_reported = _DummySignal()
            finished_text = _DummySignal()
            error_occurred = _DummySignal()

        monkeypatch.setattr(ai_module, "AIEngineWorker", _RecorderWorker)
        ai_manager.client = object()

        ai_manager.ask(user_prompt="你好", system_prompt="你是数学助手。")
        assert recorded["messages"][0]["content"] == "你是数学助手。"
