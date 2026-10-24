"""文件式记忆系统（File-based Memory System）。

设计对齐 Codex / Claude Code 的「文件即记忆」范式：记忆以人类可读、可编辑的 Markdown
文件落在磁盘上，而不是塞进数据库或向量库。用户可以直接用编辑器改，AI 也可以自己写。

目录布局（每个作用域一份）::

    <root>/
    ├── MEMORY.md          # 长期记忆：策展后的稳定事实（用户偏好 / 项目约定 / 术语表）
    ├── YYYY-MM-DD.md      # 每日日志：append-only，只追加不覆盖
    └── archive/           # 蒸馏后归档的历史日志

作用域（scope）::

    project —— 项目级记忆，随工作目录走，默认落在包内 ``data/memory/``
    user    —— 用户级记忆，跨项目共享，落在 ``~/.mathlab/memory/``

两条硬性约束：

1. **读取零副作用** —— 目录或文件不存在时一律返回空字符串，绝不在读路径上创建文件，
   因此把记忆系统挂到 AI 主链路上不会在用户磁盘上留下垃圾。
2. **写入失败不阻断** —— 打包安装后 ``mathlab/data/`` 可能只读，此时自动降级到用户级
   目录；再失败只记日志，不向上抛异常。
"""

import os
import re
import threading
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple

from mathlab.utils.logger import get_logger

logger = get_logger(__name__)

# --- 常量 ---------------------------------------------------------------
# 环境变量覆盖项目级记忆根目录（测试与便携化部署用）
MEMORY_ROOT_ENV = "MATHLAB_MEMORY_DIR"

PROJECT_MEMORY_SUBDIR = os.path.join("data", "memory")
USER_MEMORY_SUBDIR = os.path.join(".mathlab", "memory")

CURATED_FILENAME = "MEMORY.md"
ARCHIVE_DIRNAME = "archive"
CURATED_SECTION_HEADING = "## 长期记忆"
ARCHIVE_SECTION_HEADING = "## 历史归档"

DAILY_FILENAME_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\.md$")
# Codex 同款：项目指令文件的候选名，按优先级排列
PROJECT_INSTRUCTION_FILES: Tuple[str, ...] = ("AGENTS.md", "MATHLAB.md")

DEFAULT_MAX_CURATED_CHARS = 4000
DEFAULT_MAX_CONTEXT_CHARS = 3000
DEFAULT_MAX_INSTRUCTION_CHARS = 6000
DEFAULT_DAILY_RETENTION_DAYS = 30
DEFAULT_RECENT_LOG_DAYS = 2
# 向上查找项目指令文件的最大层数
MAX_INSTRUCTION_LOOKUP_DEPTH = 6

_CURATED_TEMPLATE = """# MathLab 长期记忆

> 本文件由 AI 与用户共同维护。写入的是**跨会话稳定**的事实：
> 用户偏好、项目约定、术语口径、反复踩过的坑。
> 一次性过程信息请写进 `YYYY-MM-DD.md` 日志。

## 长期记忆

（暂无条目。可用 `/remember <内容>` 或让 AI 调用 `save_memory` 写入。）
"""


class MemoryScope(Enum):
    """记忆作用域。"""

    PROJECT = "project"
    USER = "user"


def _default_project_root() -> str:
    """项目级记忆根目录：包内 ``data/memory``，可用环境变量覆盖。"""
    env_root = os.environ.get(MEMORY_ROOT_ENV)
    if env_root:
        return os.path.abspath(env_root)
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "data", "memory")


def _default_user_root() -> str:
    """用户级记忆根目录：``~/.mathlab/memory``。"""
    return os.path.join(os.path.expanduser("~"), ".mathlab", "memory")


class FileMemorySystem:
    """文件式记忆系统。

    Args:
        project_root: 项目级记忆根目录；None 表示用默认路径。
        user_root: 用户级记忆根目录；None 表示用默认路径。
        project_dir: 项目指令（AGENTS.md）的查找起点；None 表示取当前工作目录。
        enabled: 总开关，关闭后所有读取返回空、所有写入静默跳过。
        max_curated_chars: ``MEMORY.md`` 的字符上限，超出后丢弃最旧的条目。
        max_context_chars: 注入 system prompt 的上下文字符预算。
        daily_retention_days: 每日日志保留天数，超过后可蒸馏归档。
    """

    def __init__(
        self,
        project_root: Optional[str] = None,
        user_root: Optional[str] = None,
        project_dir: Optional[str] = None,
        enabled: bool = True,
        max_curated_chars: int = DEFAULT_MAX_CURATED_CHARS,
        max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
        daily_retention_days: int = DEFAULT_DAILY_RETENTION_DAYS,
    ):
        self.enabled = enabled
        self.max_curated_chars = max_curated_chars
        self.max_context_chars = max_context_chars
        self.daily_retention_days = daily_retention_days
        self.project_dir = project_dir
        self._lock = threading.RLock()
        self._roots: Dict[str, str] = {
            MemoryScope.PROJECT.value: project_root or _default_project_root(),
            MemoryScope.USER.value: user_root or _default_user_root(),
        }
        self._fallback_logged = False

    # ------------------------------------------------------------------
    # 路径解析
    # ------------------------------------------------------------------
    def root_of(self, scope: str = MemoryScope.PROJECT.value) -> str:
        """返回指定作用域的记忆根目录。"""
        return self._roots.get(scope, self._roots[MemoryScope.PROJECT.value])

    def _curated_path(self, scope: str) -> str:
        return os.path.join(self.root_of(scope), CURATED_FILENAME)

    def _daily_path(self, scope: str, day: date) -> str:
        return os.path.join(self.root_of(scope), f"{day.isoformat()}.md")

    def _archive_dir(self, scope: str) -> str:
        return os.path.join(self.root_of(scope), ARCHIVE_DIRNAME)

    def _writable_root(self, scope: str) -> str:
        """返回可写根目录；项目级不可写时降级到用户级。

        Returns:
            可写根目录路径。两个作用域都不可写时仍返回原项目级路径（由调用方捕获异常）。
        """
        preferred = self.root_of(scope)
        try:
            os.makedirs(preferred, exist_ok=True)
            return preferred
        except OSError as exc:
            if scope != MemoryScope.USER.value:
                if not self._fallback_logged:
                    logger.warning("项目级记忆目录不可写 (%s)，降级到用户级目录", exc)
                    self._fallback_logged = True
                return self.root_of(MemoryScope.USER.value)
            raise

    # ------------------------------------------------------------------
    # 读取（零副作用）
    # ------------------------------------------------------------------
    def read_curated(self, scope: str = MemoryScope.PROJECT.value) -> str:
        """读取长期记忆全文；文件不存在返回空字符串。"""
        path = self._curated_path(scope)
        if not os.path.isfile(path):
            return ""
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return fh.read()
        except OSError as exc:
            logger.error("读取长期记忆失败: %s", exc)
            return ""

    def read_daily(self, day: date, scope: str = MemoryScope.PROJECT.value) -> str:
        """读取指定日期的日志；不存在返回空字符串。"""
        path = self._daily_path(scope, day)
        if not os.path.isfile(path):
            return ""
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return fh.read()
        except OSError as exc:
            logger.error("读取日志失败: %s", exc)
            return ""

    def list_daily_files(self, scope: str = MemoryScope.PROJECT.value) -> List[str]:
        """列出该作用域下的日志文件名（``YYYY-MM-DD.md``），按日期升序。"""
        root = self.root_of(scope)
        if not os.path.isdir(root):
            return []
        try:
            names = [n for n in os.listdir(root) if DAILY_FILENAME_RE.match(n)]
        except OSError as exc:
            logger.error("列举日志失败: %s", exc)
            return []
        return sorted(names)

    def snapshot(self) -> Dict[str, Dict[str, object]]:
        """返回各作用域的记忆概况，供 UI 展示。

        Returns:
            ``{scope: {"root": str, "files": [str], "curated_chars": int}}``
        """
        result: Dict[str, Dict[str, object]] = {}
        for scope in (MemoryScope.PROJECT.value, MemoryScope.USER.value):
            root = self.root_of(scope)
            files: List[str] = []
            if os.path.isdir(root):
                try:
                    files = sorted(n for n in os.listdir(root) if n.endswith(".md"))
                except OSError as exc:
                    logger.error("列举记忆文件失败: %s", exc)
            result[scope] = {
                "root": root,
                "files": files,
                "curated_chars": len(self.read_curated(scope)),
            }
        return result

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------
    def remember(self, fact: str, scope: str = MemoryScope.PROJECT.value) -> bool:
        """向长期记忆追加一条事实。

        Args:
            fact: 要记住的一句话事实（不要写时间戳，方法内部会加）。
            scope: 目标作用域。

        Returns:
            True 表示已写入；False 表示内容为空、已存在重复条目，或记忆系统已关闭。
        """
        if not self.enabled:
            return False
        fact = (fact or "").strip()
        if not fact:
            return False

        with self._lock:
            try:
                root = self._writable_root(scope)
                path = os.path.join(root, CURATED_FILENAME)
                content = self._read_or_template(path)
                entry = f"- [{date.today().isoformat()}] {fact}"
                if self._has_entry(content, entry):
                    logger.debug("记忆条目已存在，跳过: %s", fact[:40])
                    return False
                content = self._append_under_heading(content, CURATED_SECTION_HEADING, entry)
                content = self._enforce_curated_cap(content)
                self._atomic_write(path, content)
            except OSError as exc:
                logger.error("写入长期记忆失败: %s", exc, exc_info=True)
                return False
        logger.info("📝 已记住: %s", fact[:60])
        return True

    def forget(self, keyword: str, scope: str = MemoryScope.PROJECT.value) -> int:
        """删除长期记忆中包含关键词的条目。

        Args:
            keyword: 关键词（大小写不敏感）。
            scope: 目标作用域。

        Returns:
            被删除的条目数。
        """
        if not self.enabled or not (keyword or "").strip():
            return 0
        needle = keyword.strip().lower()
        removed = 0

        with self._lock:
            try:
                root = self._writable_root(scope)
                path = os.path.join(root, CURATED_FILENAME)
                if not os.path.isfile(path):
                    return 0
                content = self._read_or_template(path)
                kept: List[str] = []
                for line in content.splitlines():
                    is_entry = line.lstrip().startswith("- ")
                    if is_entry and needle in line.lower():
                        removed += 1
                        continue
                    kept.append(line)
                if removed:
                    self._atomic_write(path, "\n".join(kept).rstrip() + "\n")
            except OSError as exc:
                logger.error("删除记忆条目失败: %s", exc, exc_info=True)
                return 0
        if removed:
            logger.info("🧹 已遗忘 %d 条含「%s」的记忆", removed, keyword)
        return removed

    def append_daily(self, note: str, scope: str = MemoryScope.PROJECT.value, day: Optional[date] = None) -> bool:
        """向当日（或指定日期）日志追加一行。

        Args:
            note: 日志内容。
            scope: 目标作用域。
            day: 指定日期，默认今天。

        Returns:
            True 表示已写入。
        """
        if not self.enabled:
            return False
        note = (note or "").strip()
        if not note:
            return False

        target_day = day or date.today()
        with self._lock:
            try:
                root = self._writable_root(scope)
                path = os.path.join(root, f"{target_day.isoformat()}.md")
                existing = ""
                if os.path.isfile(path):
                    with open(path, "r", encoding="utf-8") as fh:
                        existing = fh.read()
                if not existing:
                    existing = f"# {target_day.isoformat()} 工作日志\n"
                stamp = datetime.now().strftime("%H:%M:%S")
                line = f"- {stamp} {note}\n"
                if not existing.endswith("\n"):
                    existing += "\n"
                self._atomic_write(path, existing + line)
            except OSError as exc:
                logger.error("写入日志失败: %s", exc, exc_info=True)
                return False
        return True

    def distill(self, scope: Optional[str] = None, keep_days: Optional[int] = None) -> List[str]:
        """把超出保留期的日志蒸馏进 ``MEMORY.md`` 并归档原文件。

        只做整理、不调用大模型；调用方（如用户执行 `/memory distill`）决定何时触发。

        Args:
            scope: 目标作用域；None 表示两个作用域都处理。
            keep_days: 保留天数；None 表示用实例配置。

        Returns:
            被归档的日志文件名列表。
        """
        if not self.enabled:
            return []
        retention = keep_days if keep_days is not None else self.daily_retention_days
        cutoff = date.today() - timedelta(days=retention)
        scopes = [scope] if scope else [MemoryScope.PROJECT.value, MemoryScope.USER.value]
        archived: List[str] = []

        for sc in scopes:
            for name in self.list_daily_files(sc):
                match = DAILY_FILENAME_RE.match(name)
                if not match:
                    continue
                day = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
                if day >= cutoff:
                    continue
                if self._archive_log(sc, name, day):
                    archived.append(name)
        if archived:
            logger.info("🗂️ 已蒸馏归档 %d 份过期日志", len(archived))
        return archived

    def clear(self, scope: Optional[str] = None) -> int:
        """清空记忆（长期记忆 + 日志），用于重置。

        Args:
            scope: 目标作用域；None 表示清空两个作用域。

        Returns:
            被删除的文件数。
        """
        scopes = [scope] if scope else [MemoryScope.PROJECT.value, MemoryScope.USER.value]
        removed = 0
        with self._lock:
            for sc in scopes:
                root = self.root_of(sc)
                if not os.path.isdir(root):
                    continue
                targets = [CURATED_FILENAME] + self.list_daily_files(sc)
                for name in targets:
                    path = os.path.join(root, name)
                    try:
                        if os.path.isfile(path):
                            os.remove(path)
                            removed += 1
                    except OSError as exc:
                        logger.error("删除记忆文件失败: %s", exc)
        return removed

    # ------------------------------------------------------------------
    # 上下文装配
    # ------------------------------------------------------------------
    def load_project_instructions(self, project_dir: Optional[str] = None) -> str:
        """Codex 同款：从工作目录向上查找项目指令文件并读取。

        依次尝试 ``AGENTS.md``、``MATHLAB.md``，最多向上查找 6 层。

        Args:
            project_dir: 查找起点；None 表示用实例配置或当前工作目录。

        Returns:
            指令文件内容（超长时截断），未找到返回空字符串。
        """
        if not self.enabled:
            return ""
        start = project_dir or self.project_dir or os.getcwd()
        current = os.path.abspath(start)
        for _ in range(MAX_INSTRUCTION_LOOKUP_DEPTH):
            for filename in PROJECT_INSTRUCTION_FILES:
                candidate = os.path.join(current, filename)
                if os.path.isfile(candidate):
                    try:
                        with open(candidate, "r", encoding="utf-8") as fh:
                            text = fh.read()
                    except OSError as exc:
                        logger.error("读取项目指令失败: %s", exc)
                        return ""
                    if len(text) > DEFAULT_MAX_INSTRUCTION_CHARS:
                        text = text[:DEFAULT_MAX_INSTRUCTION_CHARS] + "\n\n…（已截断）"
                    return text
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent
        return ""

    def get_context_block(
        self,
        max_chars: Optional[int] = None,
        recent_log_days: int = DEFAULT_RECENT_LOG_DAYS,
        include_instructions: bool = True,
    ) -> str:
        """组装注入 system prompt 的记忆上下文。

        优先级：项目指令 > 长期记忆 > 近期日志。超出字符预算时从低优先级开始丢弃。

        Args:
            max_chars: 字符预算；None 表示用实例配置。
            recent_log_days: 注入最近几天的日志。
            include_instructions: 是否载入项目指令文件。

        Returns:
            Markdown 文本；无内容或已关闭时返回空字符串。
        """
        if not self.enabled:
            return ""
        budget = max_chars if max_chars is not None else self.max_context_chars

        sections: List[Tuple[str, str]] = []
        if include_instructions:
            instructions = self.load_project_instructions()
            if instructions.strip():
                sections.append(("项目指令（来自项目 AGENTS.md）", instructions.strip()))

        curated = self._curated_body()
        if curated:
            sections.append(("长期记忆（MEMORY.md）", curated))

        recent = self._recent_logs(recent_log_days)
        if recent:
            sections.append(("近期日志", recent))

        if not sections:
            return ""

        chunks: List[str] = []
        used = 0
        for title, body in sections:
            header = f"#### {title}\n"
            room = budget - used - len(header)
            if room <= 0:
                continue
            snippet = body if len(body) <= room else body[:room].rstrip() + "\n…（已截断）"
            chunks.append(header + snippet)
            used += len(header) + len(snippet)

        if not chunks:
            return ""
        return "### 记忆上下文（文件式记忆系统）\n" + "\n".join(chunks)

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    def _curated_body(self) -> str:
        """长期记忆正文：优先项目级，为空时回退用户级。"""
        for scope in (MemoryScope.PROJECT.value, MemoryScope.USER.value):
            text = self.read_curated(scope)
            body = self._strip_template_placeholder(text)
            if body.strip():
                return body.strip()
        return ""

    def _recent_logs(self, days: int) -> str:
        """拼接最近 N 天的日志内容。"""
        if days <= 0:
            return ""
        chunks: List[str] = []
        today = date.today()
        for offset in range(days):
            day = today - timedelta(days=offset)
            for scope in (MemoryScope.PROJECT.value, MemoryScope.USER.value):
                text = self.read_daily(day, scope)
                body = "\n".join(ln for ln in text.splitlines() if not ln.startswith("# ")).strip()
                if body:
                    chunks.append(f"##### {day.isoformat()}\n{body}")
                    break
        return "\n\n".join(chunks)

    @staticmethod
    def _strip_template_placeholder(text: str) -> str:
        """裁掉文件头与「暂无条目」占位，只保留正文，避免把模板套话喂给模型。"""
        if not text:
            return ""
        lines = [ln for ln in text.splitlines() if "（暂无条目" not in ln]
        for i, line in enumerate(lines):
            if line.startswith("## "):
                return "\n".join(lines[i:])
        return "\n".join(lines)

    @staticmethod
    def _has_entry(content: str, entry: str) -> bool:
        """判断条目是否已存在（忽略行首的时间戳差异，比较正文部分）。"""
        body = entry.split("] ", 1)[-1]
        for line in content.splitlines():
            stripped = line.lstrip()
            if stripped.startswith("- [") and stripped.split("] ", 1)[-1] == body:
                return True
        return False

    @staticmethod
    def _append_under_heading(content: str, heading: str, entry: str) -> str:
        """把条目追加到指定标题下；标题不存在则补一个。"""
        # 首次写入时清掉模板里的「暂无条目」占位
        lines = [ln for ln in content.splitlines() if "（暂无条目" not in ln]
        if heading not in lines:
            if lines and lines[-1].strip():
                lines.append("")
            lines.append(heading)
            lines.append("")
            lines.append(entry)
            return "\n".join(lines) + "\n"

        idx = lines.index(heading)
        insert_at = len(lines)
        for i in range(idx + 1, len(lines)):
            if lines[i].startswith("## "):
                insert_at = i
                break
        # 跳过标题后的空行，插到该段落末尾
        while insert_at > idx + 1 and not lines[insert_at - 1].strip():
            insert_at -= 1
        lines.insert(insert_at, entry)
        return "\n".join(lines) + "\n"

    def _enforce_curated_cap(self, content: str) -> str:
        """超出字符上限时丢弃最旧的条目（标题与说明保留）。"""
        if len(content) <= self.max_curated_chars:
            return content
        lines = content.splitlines()
        while len("\n".join(lines)) > self.max_curated_chars:
            victim = -1
            for i, line in enumerate(lines):
                if line.lstrip().startswith("- ["):
                    victim = i
                    break
            if victim < 0:
                break
            lines.pop(victim)
        result = "\n".join(lines)
        if len(result) > self.max_curated_chars:
            result = result[: self.max_curated_chars].rstrip() + "\n…（已按上限截断）"
        return result

    def _read_or_template(self, path: str) -> str:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as fh:
                return fh.read()
        return _CURATED_TEMPLATE

    @staticmethod
    def _atomic_write(path: str, content: str) -> None:
        """先写临时文件再替换，避免写一半崩溃留下损坏的记忆文件。"""
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp_path, path)

    def _archive_log(self, scope: str, name: str, day: date) -> bool:
        """把单份过期日志并入 MEMORY.md 并移入 archive/。"""
        with self._lock:
            try:
                root = self._writable_root(scope)
                src = os.path.join(root, name)
                if not os.path.isfile(src):
                    return False

                curated_path = os.path.join(root, CURATED_FILENAME)
                content = self._read_or_template(curated_path)
                entry = f"- [{day.isoformat()}] 日志归档：{name}"
                if not self._has_entry(content, entry):
                    content = self._append_under_heading(content, ARCHIVE_SECTION_HEADING, entry)
                    content = self._enforce_curated_cap(content)
                    self._atomic_write(curated_path, content)

                # 用 _writable_root 而非 _archive_dir，保证降级到用户级目录时归档也落在同一处
                archive_dir = os.path.join(root, ARCHIVE_DIRNAME)
                os.makedirs(archive_dir, exist_ok=True)
                os.replace(src, os.path.join(archive_dir, name))
                return True
            except OSError as exc:
                logger.error("归档日志失败: %s", exc, exc_info=True)
                return False


# --- 进程级单例 ---------------------------------------------------------
_MEMORY_SINGLETON: Optional[FileMemorySystem] = None
_MEMORY_LOCK = threading.Lock()


def _config_enabled() -> bool:
    """读取配置开关，配置不可用时默认开启。"""
    try:
        from mathlab.utils.config_manager import get_config

        return bool(get_config("enable_file_memory", True))
    except Exception as exc:  # noqa: BLE001 - 配置层故障不应击穿记忆系统
        logger.debug("读取记忆开关失败，按默认开启处理: %s", exc)
        return True


def get_file_memory(force_new: bool = False) -> FileMemorySystem:
    """获取进程级记忆系统单例。

    Args:
        force_new: 丢弃现有单例重建（测试与配置重载用）。

    Returns:
        :class:`FileMemorySystem` 实例。
    """
    global _MEMORY_SINGLETON
    with _MEMORY_LOCK:
        if _MEMORY_SINGLETON is None or force_new:
            _MEMORY_SINGLETON = FileMemorySystem(enabled=_config_enabled())
        return _MEMORY_SINGLETON


def reset_file_memory() -> None:
    """清空单例，供测试隔离使用。"""
    global _MEMORY_SINGLETON
    with _MEMORY_LOCK:
        _MEMORY_SINGLETON = None
