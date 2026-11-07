"""MathLab 工程文件（``.mathlab``）的唯一 schema 定义与读写入口。

历史上存在三套互不兼容的写入格式：

* ``ui/_mixin_file_io.py``：``{objects, name_counter}``（几何引擎直出）。
* ``data/project.py``：``{objects, console_history, settings{created, modified, version}}``。
* ``data/file_manager.py``：``{version, name, category, created, modified,
  objects, console_history, settings}``。

三者互相无法可靠读取：UI 存的文件没有 ``name_counter`` 以外的元数据，
而 ``ProjectManager`` 打开 UI 存的文件会丢失命名计数器，几何对象名称在
重新保存后可能重复或错位。

本模块定义 **canonical 超集格式 v2.0**，所有写入方一律经
``build_project()`` + ``write_project_file()``，所有读取方一律经
``read_project_file()`` + ``normalize_project()``。
``normalize_project()`` 负责把三种历史格式归一到同一形状且保证幂等，
因此旧工程文件仍可正常打开。

canonical 字段
--------------
``version`` / ``name`` / ``category`` / ``created`` / ``modified``（顶层元数据）、
``objects``（几何对象字典）、``console_history``（控制台历史）、
``settings``（任意用户设置，其中 ``name_counter`` 为几何引擎命名计数器）。
"""

from __future__ import annotations

import copy
import json
import os
from datetime import datetime
from typing import Any, Dict, Optional

PROJECT_SCHEMA_VERSION = "2.0"

# 旧 UI 格式把几何引擎命名计数器放在顶层，新格式收进 settings
_ENGINE_COUNTER_KEY = "name_counter"
_DEFAULT_CATEGORY = "untitled"


def _now() -> str:
    """返回 ISO 8601 时间戳。"""
    return datetime.now().isoformat()


def _as_dict(value: Any) -> Dict[str, Any]:
    """仅接受 dict，其它类型一律回落为空字典。"""
    return copy.deepcopy(value) if isinstance(value, dict) else {}


def _as_list(value: Any) -> list:
    """仅接受 list，其它类型一律回落为空列表。"""
    return copy.deepcopy(value) if isinstance(value, list) else []


def build_project(
    objects: Optional[Dict[str, Any]] = None,
    console_history: Optional[list] = None,
    settings: Optional[Dict[str, Any]] = None,
    *,
    name: str = "",
    category: str = _DEFAULT_CATEGORY,
    created: Optional[str] = None,
    modified: Optional[str] = None,
) -> Dict[str, Any]:
    """构建 canonical 工程字典。

    Args:
        objects: 几何对象字典（``GeometryEngine.serialize_all()["objects"]``）。
        console_history: 控制台历史。
        settings: 任意用户设置；几何引擎的 ``name_counter`` 也放在这里。
        name: 工程名。
        category: 工程分类。
        created: 创建时间，缺省取当前时间。
        modified: 修改时间，缺省取当前时间。

    Returns:
        符合 v2.0 schema 的字典（不写盘）。
    """
    now = _now()
    st = _as_dict(settings)
    st.setdefault("created", created or now)
    st.setdefault("modified", modified or now)
    st.setdefault("version", PROJECT_SCHEMA_VERSION)
    return {
        "version": PROJECT_SCHEMA_VERSION,
        "name": name,
        "category": category,
        "created": created or now,
        "modified": modified or now,
        "objects": _as_dict(objects),
        "console_history": _as_list(console_history),
        "settings": st,
    }


def normalize_project(data: Dict[str, Any]) -> Dict[str, Any]:
    """把任意历史格式的工程字典归一到 canonical v2.0。

    兼容三类旧文件：仅含 ``objects``/``name_counter`` 的 UI 格式、
    ``ProjectManager`` 格式、``FileManager`` 格式。函数对已归一化的结果幂等。

    Args:
        data: 从磁盘读到的原始字典。

    Returns:
        canonical 字典；输入不变（返回深拷贝）。

    Raises:
        ValueError: 输入不是字典。
    """
    if not isinstance(data, dict):
        raise ValueError("project data must be a dict")

    raw = copy.deepcopy(data)
    settings = _as_dict(raw.get("settings"))

    # 旧 UI 格式：命名计数器在顶层
    if _ENGINE_COUNTER_KEY in raw and _ENGINE_COUNTER_KEY not in settings:
        settings[_ENGINE_COUNTER_KEY] = raw[_ENGINE_COUNTER_KEY]

    created = raw.get("created") or settings.get("created") or _now()
    modified = raw.get("modified") or settings.get("modified") or created
    settings.setdefault("created", created)
    settings.setdefault("modified", modified)
    settings.setdefault("version", str(raw.get("version") or PROJECT_SCHEMA_VERSION))

    return {
        "version": PROJECT_SCHEMA_VERSION,
        "name": raw.get("name") or settings.get("name") or "",
        "category": raw.get("category") or settings.get("category") or _DEFAULT_CATEGORY,
        "created": created,
        "modified": modified,
        "objects": _as_dict(raw.get("objects")),
        "console_history": _as_list(raw.get("console_history")),
        "settings": settings,
    }


def engine_payload(project: Dict[str, Any]) -> Dict[str, Any]:
    """把 canonical 工程转成 ``GeometryEngine.deserialize_all()`` 需要的形状。

    Args:
        project: canonical 工程字典。

    Returns:
        ``{objects: {...}, name_counter: {...}}``。
    """
    settings = project.get("settings") if isinstance(project.get("settings"), dict) else {}
    return {
        "objects": project.get("objects", {}),
        _ENGINE_COUNTER_KEY: settings.get(_ENGINE_COUNTER_KEY, {}),
    }


def read_project_file(file_path: str) -> Dict[str, Any]:
    """读取并归一化 ``.mathlab`` 文件（兼容全部历史格式）。

    Args:
        file_path: 工程文件路径。

    Returns:
        canonical 工程字典。

    Raises:
        ValueError: 文件内容不是 JSON 对象。
        OSError / json.JSONDecodeError: 文件不存在或内容损坏，交由调用方处理。
    """
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return normalize_project(data)


def write_project_file(file_path: str, project: Dict[str, Any]) -> None:
    """把工程字典按 canonical v2.0 原子写入 ``.mathlab`` 文件。

    写入前会归一化（因此直接传入旧格式字典也是安全的），并刷新
    顶层与 ``settings`` 里的 ``modified`` 时间戳。

    Args:
        file_path: 目标路径。
        project: 工程字典。
    """
    canonical = normalize_project(project)
    now = _now()
    canonical["modified"] = now
    canonical["settings"]["modified"] = now

    file_path = os.fspath(file_path)
    tmp_path = file_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(canonical, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, file_path)
